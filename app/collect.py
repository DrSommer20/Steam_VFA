"""Der Sammler: holt Steam-Daten und schreibt sie in die SQLite-DB.

Laeuft per Cron/systemd-Timer z.B. alle 30 Minuten. Er ist inkrementell:
- Bibliotheken werden jedes Mal komplett gelesen (1 Call pro Spieler, guenstig)
- Store-Metadaten und Achievements werden pro Lauf gedeckelt und ueber mehrere
  Laeufe hinweg nachgezogen (aeltester Stand zuerst)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import time

from . import db
from .config import load_players, settings
from .steam import SteamClient, classify_categories

log = logging.getLogger("collect")

STORE_PER_RUN = 60          # appdetails-Calls pro Lauf (inoffizielle API, sanft bleiben)
ACH_CALLS_PER_RUN = 250     # GetPlayerAchievements-Calls pro Lauf


async def sync_players(client: SteamClient, con) -> list[str]:
    players = load_players()
    if not players:
        log.warning("Keine Spieler konfiguriert - siehe: python -m app.cli add <profil-url>")
        return []

    ids = [p["steamid"] for p in players]
    nicks = {p["steamid"]: p.get("nick") for p in players}

    for sid in ids:
        con.execute(
            "INSERT INTO players(steamid, nick) VALUES(?,?) "
            "ON CONFLICT(steamid) DO UPDATE SET nick=COALESCE(excluded.nick, players.nick)",
            (sid, nicks.get(sid)),
        )

    for s in await client.player_summaries(ids):
        con.execute(
            """UPDATE players SET personaname=?, avatar=?, profileurl=?, country=?,
                   timecreated=?, lastlogoff=?, personastate=?, visibility=?
               WHERE steamid=?""",
            (
                s.get("personaname"),
                s.get("avatarfull") or s.get("avatarmedium"),
                s.get("profileurl"),
                s.get("loccountrycode"),
                s.get("timecreated"),
                s.get("lastlogoff"),
                s.get("personastate"),
                s.get("communityvisibilitystate"),
                s["steamid"],
            ),
        )
    return ids


async def sync_library(client: SteamClient, con, steamid: str) -> tuple[int, int, int]:
    """Bibliothek eines Spielers einlesen. -> (spiele, neue_spiele, neue_minuten)"""
    games = await client.owned_games(steamid)
    if not games:
        log.warning("Keine Spiele fuer %s (privates Profil?)", steamid)
        return 0, 0, 0

    now = int(time.time())
    known = {
        r["appid"]: r["playtime_forever"]
        for r in db.rows(
            con, "SELECT appid, playtime_forever FROM ownership WHERE steamid=?", (steamid,)
        )
    }

    new_games = 0
    new_minutes = 0
    for g in games:
        appid = g["appid"]
        pt = g.get("playtime_forever", 0) or 0
        prev = known.get(appid)

        con.execute(
            "INSERT INTO games(appid, name, icon) VALUES(?,?,?) "
            "ON CONFLICT(appid) DO UPDATE SET name=COALESCE(excluded.name, games.name)",
            (appid, g.get("name"), g.get("img_icon_url")),
        )
        con.execute(
            """INSERT INTO ownership(steamid, appid, playtime_forever, playtime_2weeks, last_played, last_seen)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(steamid, appid) DO UPDATE SET
                   playtime_forever=excluded.playtime_forever,
                   playtime_2weeks=excluded.playtime_2weeks,
                   last_played=excluded.last_played,
                   last_seen=excluded.last_seen""",
            (
                steamid,
                appid,
                pt,
                g.get("playtime_2weeks", 0) or 0,
                g.get("rtime_last_played", 0) or 0,
                now,
            ),
        )

        if prev is None:
            new_games += 1
            # Basis-Snapshot, damit spaetere Deltas eine Referenz haben
            con.execute(
                "INSERT OR IGNORE INTO playtime_snapshots(steamid, appid, ts, playtime_forever, delta)"
                " VALUES(?,?,?,?,0)",
                (steamid, appid, now, pt),
            )
        elif pt > prev:
            delta = pt - prev
            new_minutes += delta
            con.execute(
                "INSERT OR REPLACE INTO playtime_snapshots(steamid, appid, ts, playtime_forever, delta)"
                " VALUES(?,?,?,?,?)",
                (steamid, appid, now, pt, delta),
            )

    return len(games), new_games, new_minutes


async def sync_store_meta(client: SteamClient, con, limit: int = STORE_PER_RUN) -> int:
    """Store-Details fuer Spiele holen - Prioritaet: viele Besitzer, viel Spielzeit."""
    todo = db.rows(
        con,
        """SELECT g.appid
             FROM games g
             JOIN (SELECT appid, COUNT(*) AS owners, SUM(playtime_forever) AS pt
                     FROM ownership GROUP BY appid) o ON o.appid = g.appid
            WHERE g.meta_fetched_at IS NULL
            ORDER BY o.owners DESC, o.pt DESC
            LIMIT ?""",
        (limit,),
    )
    done = 0
    for row in todo:
        appid = row["appid"]
        data = await client.app_details(appid)
        now = int(time.time())
        if not data:
            con.execute(
                "UPDATE games SET meta_fetched_at=?, meta_ok=0 WHERE appid=?", (now, appid)
            )
            continue
        cats, is_mp, is_coop, is_pvp = classify_categories(data.get("categories", []) or [])
        genres = [g.get("description") for g in (data.get("genres") or []) if g.get("description")]
        price = (data.get("price_overview") or {}).get("initial")
        con.execute(
            """UPDATE games SET meta_fetched_at=?, meta_ok=1, short_desc=?, header_image=?,
                   release_date=?, metacritic=?, price_cents=?, genres=?, categories=?,
                   is_multiplayer=?, is_coop=?, is_pvp=?
               WHERE appid=?""",
            (
                now,
                (data.get("short_description") or "")[:400],
                data.get("header_image"),
                (data.get("release_date") or {}).get("date"),
                (data.get("metacritic") or {}).get("score"),
                price,
                json.dumps(genres, ensure_ascii=False),
                json.dumps(cats),
                int(is_mp),
                int(is_coop),
                int(is_pvp),
                appid,
            ),
        )
        done += 1
        con.commit()
    return done


async def ensure_ach_schema(client: SteamClient, con, appid: int) -> None:
    have = con.execute("SELECT 1 FROM ach_schema WHERE appid=? LIMIT 1", (appid,)).fetchone()
    if have:
        return
    schema = await client.game_schema(appid)
    if not schema:
        return
    pct = await client.global_achievement_pct(appid)
    for a in schema:
        con.execute(
            """INSERT INTO ach_schema(appid, apiname, display, description, icon, global_pct)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(appid, apiname) DO UPDATE SET
                   display=excluded.display, description=excluded.description,
                   icon=excluded.icon, global_pct=excluded.global_pct""",
            (
                appid,
                a.get("name"),
                a.get("displayName"),
                a.get("description"),
                a.get("icon"),
                pct.get(a.get("name")),
            ),
        )


async def sync_achievements(client: SteamClient, con, limit: int = ACH_CALLS_PER_RUN) -> int:
    """Achievements fuer die relevantesten (Spieler, Spiel)-Paare nachziehen.

    Relevant = Spiel wird von mehreren besessen ODER gehoert zu den meistgespielten
    Spielen des Spielers. Wir fragen nur neu ab, wenn Spielzeit dazukam oder der
    letzte Abruf laenger als ACH_REFRESH_HOURS zurueckliegt.
    """
    cutoff = int(time.time()) - settings.ach_refresh_hours * 3600
    todo = db.rows(
        con,
        """WITH shared AS (
               SELECT appid FROM ownership GROUP BY appid HAVING COUNT(*) > 1
           ),
           ranked AS (
               SELECT steamid, appid, playtime_forever,
                      ROW_NUMBER() OVER (PARTITION BY steamid ORDER BY playtime_forever DESC) AS rn
                 FROM ownership WHERE playtime_forever > 0
           )
           SELECT r.steamid, r.appid, r.playtime_forever
             FROM ranked r
             LEFT JOIN ach_state s ON s.steamid = r.steamid AND s.appid = r.appid
            WHERE (r.rn <= ? OR r.appid IN (SELECT appid FROM shared))
              AND (COALESCE(s.last_playtime, -1) <> r.playtime_forever
                   OR COALESCE(s.last_fetch, 0) < ?)
            ORDER BY COALESCE(s.last_fetch, 0) ASC, r.playtime_forever DESC
            LIMIT ?""",
        (settings.ach_top_games, cutoff, limit),
    )

    calls = 0
    for t in todo:
        sid, appid = t["steamid"], t["appid"]
        achs = await client.player_achievements(sid, appid)
        calls += 1
        now = int(time.time())
        if achs is None:
            con.execute(
                """INSERT INTO ach_state(steamid, appid, last_fetch, last_playtime, ok) VALUES(?,?,?,?,0)
                   ON CONFLICT(steamid, appid) DO UPDATE SET last_fetch=excluded.last_fetch,
                       last_playtime=excluded.last_playtime, ok=0""",
                (sid, appid, now, t["playtime_forever"]),
            )
            continue

        await ensure_ach_schema(client, con, appid)
        for a in achs:
            con.execute(
                """INSERT INTO achievements(steamid, appid, apiname, achieved, unlocktime)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(steamid, appid, apiname) DO UPDATE SET
                       achieved=excluded.achieved, unlocktime=excluded.unlocktime""",
                (
                    sid,
                    appid,
                    a.get("apiname"),
                    int(a.get("achieved", 0)),
                    a.get("unlocktime", 0) or 0,
                ),
            )
        con.execute(
            """INSERT INTO ach_state(steamid, appid, last_fetch, last_playtime, ok) VALUES(?,?,?,?,1)
               ON CONFLICT(steamid, appid) DO UPDATE SET last_fetch=excluded.last_fetch,
                   last_playtime=excluded.last_playtime, ok=1""",
            (sid, appid, now, t["playtime_forever"]),
        )
        con.commit()
    return calls


async def run(full: bool = False, skip_achievements: bool = False) -> dict:
    db.init()
    started = int(time.time())
    stats = {"players": 0, "games": 0, "new_games": 0, "minutes_new": 0, "store": 0, "ach": 0}
    note = ""
    ok = 1

    try:
        async with SteamClient() as client:
            with db.session() as con:
                ids = await sync_players(client, con)
                stats["players"] = len(ids)
                for sid in ids:
                    n, new, mins = await sync_library(client, con, sid)
                    stats["games"] += n
                    stats["new_games"] += new
                    stats["minutes_new"] += mins
                    con.commit()

                stats["store"] = await sync_store_meta(
                    client, con, 10_000 if full else STORE_PER_RUN
                )
                con.commit()

                if not skip_achievements:
                    stats["ach"] = await sync_achievements(
                        client, con, 100_000 if full else ACH_CALLS_PER_RUN
                    )
    except Exception as exc:  # noqa: BLE001 - ein Fehler soll den Timer nicht killen
        ok = 0
        note = f"{type(exc).__name__}: {exc}"
        log.exception("Sammellauf fehlgeschlagen")

    with db.session() as con:
        con.execute(
            """INSERT INTO collect_runs(started_at, finished_at, ok, players, games,
                                        new_games, minutes_new, note)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                started,
                int(time.time()),
                ok,
                stats["players"],
                stats["games"],
                stats["new_games"],
                stats["minutes_new"],
                note or "store={} ach={}".format(stats["store"], stats["ach"]),
            ),
        )
    stats["ok"] = ok
    stats["note"] = note
    return stats


async def loop(interval: int, full_first: bool, skip_achievements: bool) -> None:
    """Dauerlauf fuer den Container: erster Lauf sofort, danach alle `interval` Sekunden.

    Ersetzt den systemd-Timer - im Container laeuft der Sammler einfach als
    eigener, langlebiger Prozess.
    """
    first = True
    while True:
        res = await run(full=full_first and first, skip_achievements=skip_achievements)
        log.info("Lauf beendet: %s", json.dumps(res, ensure_ascii=False))
        first = False
        # kleiner Jitter, damit mehrere Instanzen nicht im Gleichtakt bei Steam anklopfen
        wait = interval + random.randint(0, max(interval // 10, 1))
        log.info("naechster Lauf in %d s", wait)
        await asyncio.sleep(wait)


def main() -> None:
    ap = argparse.ArgumentParser(description="Steam-Daten einsammeln")
    ap.add_argument("--full", action="store_true", help="Limits pro Lauf aufheben (erster Lauf)")
    ap.add_argument("--no-achievements", action="store_true")
    ap.add_argument(
        "--interval",
        type=int,
        default=0,
        metavar="SEKUNDEN",
        help="Dauerlauf-Modus: alle N Sekunden sammeln (fuer Docker/Container)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.interval > 0:
        try:
            asyncio.run(loop(args.interval, args.full, args.no_achievements))
        except KeyboardInterrupt:
            log.info("beendet")
        return

    res = asyncio.run(run(full=args.full, skip_achievements=args.no_achievements))
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
