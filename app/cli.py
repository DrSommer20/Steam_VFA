"""Kleines Verwaltungs-CLI.

    python -m app.cli add https://steamcommunity.com/id/beispiel  --nick "Timmi"
    python -m app.cli add 76561198000000000
    python -m app.cli list
    python -m app.cli remove 76561198000000000
    python -m app.cli collect --full
    python -m app.cli serve
    python -m app.cli demo          # Demo-Daten zum Ausprobieren ohne API-Key
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time

from . import collect, db
from .config import load_players, save_players, settings
from .steam import SteamClient


async def cmd_add(ident: str, nick: str | None) -> None:
    async with SteamClient() as client:
        sid = await client.resolve_any(ident)
        if not sid:
            print(f"Konnte '{ident}' nicht aufloesen. SteamID64 oder Profil-URL angeben.")
            return
        summaries = await client.player_summaries([sid])
        name = summaries[0].get("personaname") if summaries else None
        vis = summaries[0].get("communityvisibilitystate") if summaries else None

    players = load_players()
    if any(p["steamid"] == sid for p in players):
        print(f"{sid} ist bereits eingetragen.")
        return
    players.append({"steamid": sid, "nick": nick or name})
    save_players(players)
    print(f"Hinzugefuegt: {nick or name} ({sid})")
    if vis is not None and vis != 3:
        print(
            "  Achtung: Profil ist nicht oeffentlich. Fuer Spielzeiten/Achievements muessen\n"
            "  'Spieldetails' in den Steam-Privatsphaeneeinstellungen auf 'Oeffentlich' stehen."
        )


def cmd_list() -> None:
    players = load_players()
    if not players:
        print("Noch keine Spieler eingetragen.")
        return
    db.init()
    with db.session() as con:
        for p in players:
            row = db.one(
                con,
                """SELECT COUNT(*) games, COALESCE(SUM(playtime_forever),0) mins
                     FROM ownership WHERE steamid=?""",
                (p["steamid"],),
            ) or {}
            print(
                f"{p.get('nick') or '-':<20} {p['steamid']}  "
                f"{row.get('games', 0):>5} Spiele  {(row.get('mins') or 0) // 60:>6} h"
            )


def cmd_remove(sid: str, purge: bool) -> None:
    players = [p for p in load_players() if p["steamid"] != sid]
    save_players(players)
    print(f"Aus der Spielerliste entfernt: {sid}")
    if purge:
        db.init()
        with db.session() as con:
            for table in ("ownership", "playtime_snapshots", "achievements", "ach_state", "votes"):
                con.execute(f"DELETE FROM {table} WHERE steamid=?", (sid,))
            con.execute("DELETE FROM players WHERE steamid=?", (sid,))
        print("Daten aus der Datenbank geloescht.")


async def cmd_verify_seed(fix: bool) -> None:
    """Prueft die appids der kuratierten Vorschlagsliste gegen den Steam-Store.

    Die Liste ist handgepflegt - dieser Befehl deckt Tippfehler und
    umbenannte/entfernte Apps auf und kann Namen + Genres automatisch korrigieren.
    """
    with settings.seed_file.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    problems = 0
    async with SteamClient() as client:
        for entry in seed:
            data = await client.app_details(entry["appid"])
            if not data:
                print(f"  FEHLT   {entry['appid']:>8}  {entry['name']}  (Store liefert nichts)")
                problems += 1
                continue
            real = data.get("name", "")
            if real.lower().replace("®", "").strip() != entry["name"].lower().strip():
                print(f"  ABWEICH {entry['appid']:>8}  Liste: {entry['name']!r} -> Store: {real!r}")
                problems += 1
                if fix:
                    entry["name"] = real
            if fix:
                genres = [g.get("description") for g in (data.get("genres") or []) if g.get("description")]
                if genres:
                    entry["genres"] = genres

    if fix:
        with settings.seed_file.open("w", encoding="utf-8") as fh:
            json.dump(seed, fh, indent=1, ensure_ascii=False)
        print("Datei aktualisiert:", settings.seed_file)
    print(f"{len(seed)} Eintraege geprueft, {problems} auffaellig.")


def cmd_demo() -> None:
    """Fuellt die DB mit Beispieldaten, damit man das Frontend ohne API-Key sieht."""
    db.init()
    now = int(time.time())
    demo_players = [
        ("76561190000000001", "Timmi", "https://avatars.fastly.steamstatic.com/0.jpg"),
        ("76561190000000002", "Jonas", "https://avatars.fastly.steamstatic.com/0.jpg"),
        ("76561190000000003", "Mel", "https://avatars.fastly.steamstatic.com/0.jpg"),
        ("76561190000000004", "Ben", "https://avatars.fastly.steamstatic.com/0.jpg"),
    ]
    demo_games = [
        (244850, "Space Engineers", ["Simulation", "Sandbox"], 1, 1, 0, 82, 1999),
        (214950, "Total War: ROME II", ["Strategy"], 1, 1, 1, 76, 4499),
        (105600, "Terraria", ["Action", "Adventure"], 1, 1, 0, 83, 999),
        (892970, "Valheim", ["Survival", "Adventure"], 1, 1, 0, None, 1999),
        (322330, "Don't Starve Together", ["Survival"], 1, 1, 0, 83, 1299),
        (108600, "Project Zomboid", ["Survival", "Simulation"], 1, 1, 0, None, 1999),
        (394360, "Hearts of Iron IV", ["Strategy", "Simulation"], 1, 1, 1, 83, 4999),
        (255710, "Cities: Skylines", ["Simulation", "Strategy"], 0, 0, 0, 85, 2799),
        (620, "Portal 2", ["Action", "Adventure"], 1, 1, 0, 95, 999),
        (1222670, "The Sims 4", ["Simulation"], 0, 0, 0, None, 3999),
        (739630, "Phasmophobia", ["Horror", "Adventure"], 1, 1, 0, None, 1399),
        (1966720, "Lethal Company", ["Horror", "Action"], 1, 1, 0, None, 999),
        (632360, "Risk of Rain 2", ["Action"], 1, 1, 0, 85, 2499),
        (881100, "Noita", ["Action", "Adventure"], 0, 0, 0, 85, 1999),
        (289070, "Civilization VI", ["Strategy"], 1, 0, 1, 88, 5999),
    ]
    with db.session() as con:
        for sid, nick, avatar in demo_players:
            con.execute(
                """INSERT INTO players(steamid, nick, personaname, avatar, profileurl, visibility)
                   VALUES(?,?,?,?,?,3)
                   ON CONFLICT(steamid) DO UPDATE SET nick=excluded.nick""",
                (sid, nick, nick, avatar, f"https://steamcommunity.com/profiles/{sid}"),
            )
        for appid, name, genres, mp, coop, pvp, mc, price in demo_games:
            con.execute(
                """INSERT INTO games(appid, name, meta_fetched_at, meta_ok, genres, categories,
                                     is_multiplayer, is_coop, is_pvp, metacritic, price_cents,
                                     header_image, short_desc, release_date)
                   VALUES(?,?,?,1,?,'[]',?,?,?,?,?,?,?,?)
                   ON CONFLICT(appid) DO UPDATE SET name=excluded.name""",
                (
                    appid,
                    name,
                    now,
                    json.dumps(genres),
                    mp,
                    coop,
                    pvp,
                    mc,
                    price,
                    f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
                    "Demo-Datensatz.",
                    "2015",
                ),
            )

        rng = random.Random(42)
        for sid, *_ in demo_players:
            for appid, name, *_rest in demo_games:
                if rng.random() < 0.25:
                    continue  # nicht jeder hat alles
                mins = rng.choice([0, 0, 15, 120, 640, 1800, 5400])
                last = now - rng.randint(0, 240) * 86400 if mins else 0
                con.execute(
                    """INSERT INTO ownership(steamid, appid, playtime_forever, playtime_2weeks, last_played)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(steamid, appid) DO UPDATE SET playtime_forever=excluded.playtime_forever""",
                    (sid, appid, mins, 0, last),
                )
                # ein paar Sessions der letzten 30 Tage erfinden
                running = max(mins - rng.randint(0, 400), 0)
                for d in range(30, 0, -1):
                    if mins and rng.random() < 0.12:
                        delta = rng.randint(20, 180)
                        running += delta
                        ts = now - d * 86400 + rng.randint(0, 20000)
                        con.execute(
                            """INSERT OR REPLACE INTO playtime_snapshots(steamid, appid, ts, playtime_forever, delta)
                               VALUES(?,?,?,?,?)""",
                            (sid, appid, ts, running, delta),
                        )
        # Achievements: pro Spiel ein paar Definitionen, davon einige freigeschaltet
        for appid, name, *_rest in demo_games:
            for i in range(1, 13):
                con.execute(
                    """INSERT OR REPLACE INTO ach_schema(appid, apiname, display, description, icon, global_pct)
                       VALUES(?,?,?,?,?,?)""",
                    (
                        appid,
                        f"ACH_{i:02d}",
                        f"{name}: Meilenstein {i}",
                        "Demo-Errungenschaft.",
                        "",
                        round(rng.uniform(0.4, 70.0), 1),
                    ),
                )
            for sid, *_ in demo_players:
                owned = con.execute(
                    "SELECT playtime_forever FROM ownership WHERE steamid=? AND appid=?", (sid, appid)
                ).fetchone()
                if not owned or not owned["playtime_forever"]:
                    continue
                for i in range(1, 13):
                    got = rng.random() < min(0.15 + owned["playtime_forever"] / 6000, 0.95)
                    con.execute(
                        """INSERT OR REPLACE INTO achievements(steamid, appid, apiname, achieved, unlocktime)
                           VALUES(?,?,?,?,?)""",
                        (
                            sid,
                            appid,
                            f"ACH_{i:02d}",
                            int(got),
                            now - rng.randint(0, 300) * 86400 - rng.randint(0, 86000) if got else 0,
                        ),
                    )

        con.execute(
            """INSERT INTO collect_runs(started_at, finished_at, ok, players, games, note)
               VALUES(?,?,1,?,?,'demo')""",
            (now - 60, now, len(demo_players), len(demo_games)),
        )
    print(f"Demo-Daten geschrieben nach {settings.db_path}")
    print("Jetzt starten:  python -m app.cli serve")


def main() -> None:
    ap = argparse.ArgumentParser(prog="app.cli", description="Steam Group Hub - Verwaltung")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="Spieler hinzufuegen (SteamID64, Profil-URL oder Vanity-Name)")
    a.add_argument("ident")
    a.add_argument("--nick", default=None)

    sub.add_parser("list", help="Spieler anzeigen")

    r = sub.add_parser("remove", help="Spieler entfernen")
    r.add_argument("steamid")
    r.add_argument("--purge", action="store_true", help="auch alle Daten aus der DB loeschen")

    c = sub.add_parser("collect", help="Sammellauf starten")
    c.add_argument("--full", action="store_true")
    c.add_argument("--no-achievements", action="store_true")

    v = sub.add_parser("verify-seed", help="appids der Vorschlagsliste gegen den Store pruefen")
    v.add_argument("--fix", action="store_true", help="Namen und Genres automatisch uebernehmen")

    sub.add_parser("serve", help="Webserver starten")
    sub.add_parser("demo", help="Demo-Daten erzeugen (kein API-Key noetig)")
    sub.add_parser("init", help="Datenbank anlegen")

    args = ap.parse_args()

    if args.cmd == "add":
        asyncio.run(cmd_add(args.ident, args.nick))
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "remove":
        cmd_remove(args.steamid, args.purge)
    elif args.cmd == "collect":
        res = asyncio.run(collect.run(full=args.full, skip_achievements=args.no_achievements))
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif args.cmd == "verify-seed":
        asyncio.run(cmd_verify_seed(args.fix))
    elif args.cmd == "serve":
        from .main import main as serve

        serve()
    elif args.cmd == "demo":
        cmd_demo()
    elif args.cmd == "init":
        db.init()
        print(f"Datenbank bereit: {settings.db_path}")


if __name__ == "__main__":
    main()
