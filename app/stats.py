"""Auswertungen. Alles reines SQL + etwas Python drumherum, keine Magie.

Jede Funktion hier gibt fertige Dicts/Listen zurueck, die main.py 1:1 als JSON
ausliefert. Wer eine neue Statistik will, schreibt hier eine Funktion und haengt
in main.py eine Route dran.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict

from . import db
from .config import settings

DAY = 86400
SESSION_GAP = 3 * 3600  # Events desselben Spielers/Spiels innerhalb 3h = eine Session

# Die Store-API liefert Genres in STORE_LANG (bei uns deutsch), die kuratierte
# Seed-Liste ist englisch. Hier normalisieren wir beides auf einen Nenner.
GENRE_ALIASES = {
    "abenteuer": "adventure",
    "strategie": "strategy",
    "rollenspiel": "rpg",
    "gelegenheitsspiele": "casual",
    "rennspiel": "racing",
    "rennspiele": "racing",
    "sport": "sports",
    "fruehzugang": "early access",
    "frühzugang": "early access",
    "massenhaft-mehrspieler": "massively multiplayer",
    "kostenlos spielbar": "free to play",
}


def _norm_genre(name: str) -> str:
    g = (name or "").strip().lower()
    return GENRE_ALIASES.get(g, g)


def _players(con: sqlite3.Connection) -> list[dict]:
    return db.rows(
        con,
        """SELECT steamid, COALESCE(nick, personaname, steamid) AS name, personaname,
                  avatar, profileurl, country, timecreated, lastlogoff, personastate, visibility
             FROM players ORDER BY name COLLATE NOCASE""",
    )


def _player_count(con: sqlite3.Connection) -> int:
    row = con.execute("SELECT COUNT(*) c FROM players").fetchone()
    return row["c"] if row else 0


# --------------------------------------------------------------------- uebersicht


def overview(con: sqlite3.Connection) -> dict:
    n = _player_count(con)
    agg = db.one(
        con,
        """SELECT COUNT(DISTINCT appid) AS games,
                  SUM(playtime_forever) AS minutes,
                  SUM(CASE WHEN playtime_forever = 0 THEN 1 ELSE 0 END) AS unplayed
             FROM ownership""",
    ) or {}
    shared = db.one(
        con,
        """SELECT COUNT(*) AS c FROM (
               SELECT appid FROM ownership GROUP BY appid HAVING COUNT(*) = ?)""",
        (n,),
    ) or {}
    shared_mp = db.one(
        con,
        """SELECT COUNT(*) AS c FROM (
               SELECT o.appid FROM ownership o
                 JOIN games g ON g.appid = o.appid
                WHERE g.is_multiplayer = 1
                GROUP BY o.appid HAVING COUNT(*) = ?)""",
        (n,),
    ) or {}
    ach = db.one(
        con, "SELECT COUNT(*) AS c FROM achievements WHERE achieved = 1"
    ) or {}
    since = int(time.time()) - 14 * DAY
    recent = db.one(
        con,
        "SELECT COALESCE(SUM(delta), 0) AS m FROM playtime_snapshots WHERE ts >= ?",
        (since,),
    ) or {}
    value = db.one(
        con,
        """SELECT COALESCE(SUM(g.price_cents), 0) AS cents
             FROM ownership o JOIN games g ON g.appid = o.appid
            WHERE g.price_cents IS NOT NULL""",
    ) or {}
    last_run = db.one(
        con,
        "SELECT started_at, finished_at, ok, note FROM collect_runs ORDER BY id DESC LIMIT 1",
    )
    return {
        "players": n,
        "games_distinct": agg.get("games") or 0,
        "minutes_total": agg.get("minutes") or 0,
        "unplayed_entries": agg.get("unplayed") or 0,
        "shared_all": shared.get("c") or 0,
        "shared_all_multiplayer": shared_mp.get("c") or 0,
        "achievements_unlocked": ach.get("c") or 0,
        "minutes_last_14d": recent.get("m") or 0,
        "library_value_cents": value.get("cents") or 0,
        "last_run": last_run,
    }


def players_detail(con: sqlite3.Connection) -> list[dict]:
    out = []
    since = int(time.time()) - 14 * DAY
    for p in _players(con):
        sid = p["steamid"]
        agg = db.one(
            con,
            """SELECT COUNT(*) AS games, COALESCE(SUM(playtime_forever),0) AS minutes,
                      SUM(CASE WHEN playtime_forever=0 THEN 1 ELSE 0 END) AS unplayed,
                      MAX(last_played) AS last_played
                 FROM ownership WHERE steamid=?""",
            (sid,),
        ) or {}
        ach = db.one(
            con,
            "SELECT COUNT(*) AS c FROM achievements WHERE steamid=? AND achieved=1",
            (sid,),
        ) or {}
        recent = db.one(
            con,
            "SELECT COALESCE(SUM(delta),0) AS m FROM playtime_snapshots WHERE steamid=? AND ts>=?",
            (sid, since),
        ) or {}
        top = db.rows(
            con,
            """SELECT o.appid, g.name, o.playtime_forever AS minutes
                 FROM ownership o JOIN games g ON g.appid=o.appid
                WHERE o.steamid=? ORDER BY o.playtime_forever DESC LIMIT 5""",
            (sid,),
        )
        out.append(
            {
                **p,
                "games": agg.get("games") or 0,
                "minutes": agg.get("minutes") or 0,
                "unplayed": agg.get("unplayed") or 0,
                "last_played": agg.get("last_played") or 0,
                "achievements": ach.get("c") or 0,
                "minutes_last_14d": recent.get("m") or 0,
                "top_games": top,
            }
        )
    return out


# ---------------------------------------------------------------------- library


def library(
    con: sqlite3.Connection,
    min_owners: int = 1,
    multiplayer_only: bool = False,
    unplayed_only: bool = False,
    search: str = "",
    sort: str = "owners",
    limit: int = 300,
) -> list[dict]:
    """Gemeinsame Bibliothek inkl. Wer-hat-was."""
    order = {
        "owners": "owners DESC, total_minutes DESC",
        "playtime": "total_minutes DESC",
        "name": "g.name COLLATE NOCASE",
        "recent": "last_played DESC",
    }.get(sort, "owners DESC, total_minutes DESC")

    sql = f"""
        SELECT g.appid, g.name, g.icon, g.header_image, g.short_desc, g.genres,
               g.is_multiplayer, g.is_coop, g.is_pvp, g.metacritic, g.price_cents,
               g.release_date, g.meta_ok,
               COUNT(o.steamid) AS owners,
               SUM(o.playtime_forever) AS total_minutes,
               MAX(o.last_played) AS last_played,
               group_concat(o.steamid) AS owner_ids
          FROM ownership o
          JOIN games g ON g.appid = o.appid
         WHERE (:search = '' OR g.name LIKE '%' || :search || '%')
           AND (:mp = 0 OR g.is_multiplayer = 1)
         GROUP BY g.appid
        HAVING owners >= :min_owners
           AND (:unplayed = 0 OR total_minutes = 0)
         ORDER BY {order}
         LIMIT :limit
    """
    rows = db.rows(
        con,
        sql,
        {
            "search": search or "",
            "mp": int(multiplayer_only),
            "min_owners": min_owners,
            "unplayed": int(unplayed_only),
            "limit": limit,
        },
    )
    all_ids = {p["steamid"]: p["name"] for p in _players(con)}
    for r in rows:
        owners = (r.pop("owner_ids") or "").split(",")
        r["owner_names"] = [all_ids.get(o, o) for o in owners if o]
        r["missing_names"] = [n for sid, n in all_ids.items() if sid not in owners]
        r["genres"] = json.loads(r["genres"]) if r.get("genres") else []
    return rows


def matrix(con: sqlite3.Connection) -> dict:
    """Overlap-Matrix: wie viele Spiele hat jedes Spielerpaar gemeinsam."""
    ps = _players(con)
    ids = [p["steamid"] for p in ps]
    cells = []
    for a in ids:
        row = []
        for b in ids:
            if a == b:
                r = db.one(con, "SELECT COUNT(*) c FROM ownership WHERE steamid=?", (a,))
            else:
                r = db.one(
                    con,
                    """SELECT COUNT(*) c FROM ownership x
                         JOIN ownership y ON y.appid = x.appid AND y.steamid = ?
                        WHERE x.steamid = ?""",
                    (b, a),
                )
            row.append((r or {}).get("c") or 0)
        cells.append(row)
    return {"players": ps, "cells": cells}


# --------------------------------------------------------------------- activity


def activity(con: sqlite3.Connection, days: int = 14, limit: int = 60) -> list[dict]:
    """Feed der letzten Sessions, aus den Snapshot-Deltas rekonstruiert."""
    since = int(time.time()) - days * DAY
    events = db.rows(
        con,
        """SELECT s.steamid, s.appid, s.ts, s.delta,
                  COALESCE(p.nick, p.personaname, s.steamid) AS player,
                  p.avatar, g.name AS game, g.icon, g.header_image
             FROM playtime_snapshots s
             JOIN players p ON p.steamid = s.steamid
             JOIN games g ON g.appid = s.appid
            WHERE s.ts >= ? AND s.delta > 0
            ORDER BY s.ts ASC""",
        (since,),
    )

    merged: list[dict] = []
    index: dict[tuple, dict] = {}
    for e in events:
        key = (e["steamid"], e["appid"])
        cur = index.get(key)
        if cur and e["ts"] - cur["end"] <= SESSION_GAP:
            cur["minutes"] += e["delta"]
            cur["end"] = e["ts"]
            continue
        item = {
            "steamid": e["steamid"],
            "player": e["player"],
            "avatar": e["avatar"],
            "appid": e["appid"],
            "game": e["game"],
            "icon": e["icon"],
            "header_image": e["header_image"],
            "minutes": e["delta"],
            "start": e["ts"],
            "end": e["ts"],
        }
        merged.append(item)
        index[key] = item

    merged.sort(key=lambda x: x["end"], reverse=True)
    return merged[:limit]


def timeline(con: sqlite3.Connection, days: int = 30) -> dict:
    """Taegliche Spielminuten pro Spieler - Futter fuer den Chart."""
    since = int(time.time()) - days * DAY
    rows = db.rows(
        con,
        """SELECT s.steamid, COALESCE(p.nick, p.personaname, s.steamid) AS player,
                  date(s.ts, 'unixepoch', 'localtime') AS day,
                  SUM(s.delta) AS minutes
             FROM playtime_snapshots s
             JOIN players p ON p.steamid = s.steamid
            WHERE s.ts >= ? AND s.delta > 0
            GROUP BY s.steamid, day
            ORDER BY day""",
        (since,),
    )
    by_player: dict[str, dict[str, int]] = defaultdict(dict)
    names: dict[str, str] = {}
    for r in rows:
        by_player[r["steamid"]][r["day"]] = r["minutes"]
        names[r["steamid"]] = r["player"]

    today = time.time()
    labels = [
        time.strftime("%Y-%m-%d", time.localtime(today - (days - 1 - i) * DAY))
        for i in range(days)
    ]
    series = [
        {"steamid": sid, "player": names[sid], "data": [by_player[sid].get(d, 0) for d in labels]}
        for sid in by_player
    ]
    return {"labels": labels, "series": series}


def hours_heatmap(con: sqlite3.Connection) -> dict:
    """Wann wird gespielt? Basierend auf Achievement-Unlocks (Steam liefert dafuer Zeitstempel)."""
    rows = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player,
                  CAST(strftime('%H', a.unlocktime, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                  COUNT(*) AS c
             FROM achievements a JOIN players p ON p.steamid = a.steamid
            WHERE a.achieved = 1 AND a.unlocktime > 0
            GROUP BY player, hour""",
    )
    grid: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    for r in rows:
        if r["hour"] is not None:
            grid[r["player"]][r["hour"]] = r["c"]
    return {"hours": list(range(24)), "players": [{"player": k, "data": v} for k, v in grid.items()]}


# ----------------------------------------------------------------- achievements


def rare_achievements(con: sqlite3.Connection, max_pct: float = 10.0, limit: int = 40) -> list[dict]:
    return db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player, p.avatar,
                  g.name AS game, a.appid, s.display, s.description, s.icon,
                  s.global_pct, a.unlocktime
             FROM achievements a
             JOIN ach_schema s ON s.appid = a.appid AND s.apiname = a.apiname
             JOIN players p ON p.steamid = a.steamid
             JOIN games g ON g.appid = a.appid
            WHERE a.achieved = 1 AND s.global_pct IS NOT NULL AND s.global_pct <= ?
            ORDER BY s.global_pct ASC, a.unlocktime DESC
            LIMIT ?""",
        (max_pct, limit),
    )


def recent_achievements(con: sqlite3.Connection, limit: int = 40) -> list[dict]:
    return db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player, p.avatar,
                  g.name AS game, a.appid, s.display, s.description, s.icon,
                  s.global_pct, a.unlocktime
             FROM achievements a
             JOIN ach_schema s ON s.appid = a.appid AND s.apiname = a.apiname
             JOIN players p ON p.steamid = a.steamid
             JOIN games g ON g.appid = a.appid
            WHERE a.achieved = 1 AND a.unlocktime > 0
            ORDER BY a.unlocktime DESC
            LIMIT ?""",
        (limit,),
    )


def completion(con: sqlite3.Connection, limit: int = 30) -> list[dict]:
    """Fortschritt pro Spieler/Spiel - inkl. 100%-Spiele."""
    return db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player, a.steamid,
                  g.name AS game, a.appid, g.icon,
                  SUM(a.achieved) AS unlocked, COUNT(*) AS total,
                  ROUND(100.0 * SUM(a.achieved) / COUNT(*), 1) AS pct,
                  o.playtime_forever AS minutes
             FROM achievements a
             JOIN players p ON p.steamid = a.steamid
             JOIN games g ON g.appid = a.appid
             LEFT JOIN ownership o ON o.steamid = a.steamid AND o.appid = a.appid
            GROUP BY a.steamid, a.appid
           HAVING total > 0 AND unlocked > 0
            ORDER BY pct DESC, total DESC
            LIMIT ?""",
        (limit,),
    )


# ------------------------------------------------------------------ leaderboard


def leaderboards(con: sqlite3.Connection) -> dict:
    boards: dict[str, list[dict]] = {}

    boards["playtime"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, p.steamid) AS player, p.avatar,
                  COALESCE(SUM(o.playtime_forever),0) AS value
             FROM players p LEFT JOIN ownership o ON o.steamid = p.steamid
            GROUP BY p.steamid ORDER BY value DESC""",
    )
    boards["games"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, p.steamid) AS player, p.avatar,
                  COUNT(o.appid) AS value
             FROM players p LEFT JOIN ownership o ON o.steamid = p.steamid
            GROUP BY p.steamid ORDER BY value DESC""",
    )
    boards["backlog"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, p.steamid) AS player, p.avatar,
                  SUM(CASE WHEN o.playtime_forever = 0 THEN 1 ELSE 0 END) AS value
             FROM players p LEFT JOIN ownership o ON o.steamid = p.steamid
            GROUP BY p.steamid ORDER BY value DESC""",
    )
    boards["achievements"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, p.steamid) AS player, p.avatar,
                  COALESCE(SUM(a.achieved),0) AS value
             FROM players p LEFT JOIN achievements a ON a.steamid = p.steamid
            GROUP BY p.steamid ORDER BY value DESC""",
    )
    boards["perfect_games"] = db.rows(
        con,
        """SELECT player, avatar, COUNT(*) AS value FROM (
               SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player, p.avatar,
                      a.appid, SUM(a.achieved) AS done, COUNT(*) AS total
                 FROM achievements a JOIN players p ON p.steamid = a.steamid
                GROUP BY a.steamid, a.appid HAVING done = total AND total > 0)
            GROUP BY player ORDER BY value DESC""",
    )
    boards["rarest"] = db.rows(
        con,
        """SELECT player, avatar, MIN(global_pct) AS value, display, game FROM (
               SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player, p.avatar,
                      s.global_pct, s.display, g.name AS game
                 FROM achievements a
                 JOIN ach_schema s ON s.appid=a.appid AND s.apiname=a.apiname
                 JOIN players p ON p.steamid=a.steamid
                 JOIN games g ON g.appid=a.appid
                WHERE a.achieved=1 AND s.global_pct IS NOT NULL
                ORDER BY s.global_pct ASC)
            GROUP BY player ORDER BY value ASC""",
    )
    boards["library_value"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, p.steamid) AS player, p.avatar,
                  COALESCE(SUM(g.price_cents),0) AS value
             FROM players p
             LEFT JOIN ownership o ON o.steamid = p.steamid
             LEFT JOIN games g ON g.appid = o.appid
            GROUP BY p.steamid ORDER BY value DESC""",
    )
    boards["last_14d"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, p.steamid) AS player, p.avatar,
                  COALESCE(SUM(s.delta),0) AS value
             FROM players p
             LEFT JOIN playtime_snapshots s ON s.steamid = p.steamid AND s.ts >= ?
            GROUP BY p.steamid ORDER BY value DESC""",
        (int(time.time()) - 14 * DAY,),
    )
    return boards


def awards(con: sqlite3.Connection) -> list[dict]:
    """Ein paar halb-ernste Titel fuer die Runde."""
    out = []
    b = leaderboards(con)

    def top(board: str, label: str, fmt, desc: str):
        rows = [r for r in b.get(board, []) if (r.get("value") or 0) > 0]
        if rows:
            r = rows[0]
            out.append(
                {
                    "title": label,
                    "player": r["player"],
                    "avatar": r.get("avatar"),
                    "value": fmt(r["value"]),
                    "desc": desc,
                }
            )

    hours = lambda v: f"{v // 60} h"  # noqa: E731
    top("playtime", "Der Ausdauernde", hours, "meiste Gesamtspielzeit")
    top("backlog", "Pile of Shame", lambda v: f"{v} Spiele", "die meisten nie gestarteten Spiele")
    top("achievements", "Der Sammler", lambda v: f"{v} Errungenschaften", "meiste Achievements")
    top("perfect_games", "Der Komplettist", lambda v: f"{v} Spiele", "auf 100 % gebracht")
    top("last_14d", "Aktuell im Rausch", hours, "meiste Spielzeit der letzten 14 Tage")
    top(
        "library_value",
        "Der Investor",
        lambda v: "{:,.0f} EUR".format(v / 100).replace(",", "."),
        "teuerste Bibliothek (Listenpreise)",
    )

    rar = [r for r in b.get("rarest", []) if r.get("value") is not None]
    if rar:
        r = rar[0]
        out.append(
            {
                "title": "Der Perfektionist",
                "player": r["player"],
                "avatar": r.get("avatar"),
                "value": f"{r['value']:.2f} %",
                "desc": f"seltenstes Achievement: {r.get('display')} ({r.get('game')})",
            }
        )

    night = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player, p.avatar, COUNT(*) AS c
             FROM achievements a JOIN players p ON p.steamid = a.steamid
            WHERE a.achieved=1 AND a.unlocktime > 0
              AND CAST(strftime('%H', a.unlocktime, 'unixepoch', 'localtime') AS INTEGER) BETWEEN 0 AND 5
            GROUP BY a.steamid ORDER BY c DESC LIMIT 1""",
    )
    if night:
        out.append(
            {
                "title": "Die Nachteule",
                "player": night[0]["player"],
                "avatar": night[0].get("avatar"),
                "value": f"{night[0]['c']} Unlocks",
                "desc": "Errungenschaften zwischen 0 und 6 Uhr",
            }
        )

    mono = db.rows(
        con,
        """SELECT player, avatar, game, ROUND(100.0 * mins / total, 0) AS pct FROM (
               SELECT COALESCE(p.nick, p.personaname, o.steamid) AS player, p.avatar,
                      g.name AS game, o.playtime_forever AS mins,
                      (SELECT SUM(playtime_forever) FROM ownership WHERE steamid = o.steamid) AS total
                 FROM ownership o JOIN players p ON p.steamid=o.steamid JOIN games g ON g.appid=o.appid
                WHERE o.playtime_forever > 0)
            WHERE total > 0 ORDER BY pct DESC LIMIT 1""",
    )
    if mono:
        out.append(
            {
                "title": "Der Monogame",
                "player": mono[0]["player"],
                "avatar": mono[0].get("avatar"),
                "value": f"{mono[0]['pct']:.0f} %",
                "desc": f"der eigenen Spielzeit steckt in {mono[0]['game']}",
            }
        )
    return out


# ------------------------------------------------------------- empfehlungen


def _genre_taste(con: sqlite3.Connection) -> dict[str, float]:
    """Gewichtet Genres nach Gruppenspielzeit -> grober Geschmacksvektor."""
    rows = db.rows(
        con,
        """SELECT g.genres, SUM(o.playtime_forever) AS mins
             FROM ownership o JOIN games g ON g.appid = o.appid
            WHERE g.genres IS NOT NULL AND o.playtime_forever > 0
            GROUP BY g.appid""",
    )
    taste: dict[str, float] = defaultdict(float)
    for r in rows:
        try:
            genres = json.loads(r["genres"]) or []
        except (TypeError, ValueError):
            continue
        for gname in genres:
            taste[_norm_genre(gname)] += r["mins"]
    total = sum(taste.values()) or 1.0
    return {k: v / total for k, v in taste.items()}


def recommendations(con: sqlite3.Connection, limit: int = 15) -> dict:
    n = _player_count(con)
    now = int(time.time())

    ready = db.rows(
        con,
        """SELECT g.appid, g.name, g.header_image, g.icon, g.short_desc, g.is_coop, g.is_pvp,
                  COUNT(o.steamid) AS owners, SUM(o.playtime_forever) AS total_minutes,
                  MAX(o.last_played) AS last_played
             FROM ownership o JOIN games g ON g.appid = o.appid
            WHERE g.is_multiplayer = 1
            GROUP BY g.appid
           HAVING owners = ?
            ORDER BY (CASE WHEN MAX(o.last_played) = 0 THEN 0 ELSE MAX(o.last_played) END) ASC,
                     total_minutes DESC
            LIMIT ?""",
        (n, limit),
    )
    for r in ready:
        r["reason"] = "Alle besitzen es"
        r["days_since"] = (now - r["last_played"]) // DAY if r["last_played"] else None

    almost = db.rows(
        con,
        """SELECT g.appid, g.name, g.header_image, g.icon, g.short_desc, g.is_coop, g.is_pvp,
                  COUNT(o.steamid) AS owners, SUM(o.playtime_forever) AS total_minutes,
                  group_concat(o.steamid) AS owner_ids, g.price_cents
             FROM ownership o JOIN games g ON g.appid = o.appid
            WHERE g.is_multiplayer = 1
            GROUP BY g.appid
           HAVING owners = ? AND total_minutes > 0
            ORDER BY total_minutes DESC
            LIMIT ?""",
        (max(n - 1, 1), limit),
    )
    names = {p["steamid"]: p["name"] for p in _players(con)}
    for r in almost:
        owners = set((r.pop("owner_ids") or "").split(","))
        missing = [nm for sid, nm in names.items() if sid not in owners]
        r["missing_names"] = missing
        r["reason"] = ("Fehlt nur " + ", ".join(missing)) if missing else "Fast komplett"

    gems = db.rows(
        con,
        """SELECT g.appid, g.name, g.header_image, g.icon, g.short_desc, g.is_coop, g.is_pvp,
                  COUNT(o.steamid) AS owners, SUM(o.playtime_forever) AS total_minutes,
                  g.metacritic
             FROM ownership o JOIN games g ON g.appid = o.appid
            WHERE g.is_multiplayer = 1
            GROUP BY g.appid
           HAVING owners >= ? AND total_minutes = 0
            ORDER BY COALESCE(g.metacritic, 0) DESC, owners DESC
            LIMIT ?""",
        (max(n - 1, 2), limit),
    )
    for r in gems:
        r["reason"] = "Gekauft, nie gestartet"

    trending = db.rows(
        con,
        """SELECT g.appid, g.name, g.header_image, g.icon, g.short_desc,
                  SUM(s.delta) AS minutes, COUNT(DISTINCT s.steamid) AS active_players,
                  (SELECT COUNT(*) FROM ownership WHERE appid = g.appid) AS owners
             FROM playtime_snapshots s JOIN games g ON g.appid = s.appid
            WHERE s.ts >= ? AND s.delta > 0
            GROUP BY g.appid
            ORDER BY minutes DESC
            LIMIT ?""",
        (now - 14 * DAY, limit),
    )
    for r in trending:
        r["reason"] = f"{r['active_players']} von {n} haben es zuletzt gespielt"

    return {
        "ready_to_play": ready,
        "almost_there": almost,
        "backlog_gems": gems,
        "trending": trending,
    }


def discover(con: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Vorschlaege aus der kuratierten Koop-Liste, die noch niemand besitzt.

    Score = Genre-Uebereinstimmung mit dem Geschmack der Gruppe (aus Spielzeit
    abgeleitet) + kleiner Bonus fuer Gruppengroesse-Tauglichkeit.
    """
    if not settings.seed_file.exists():
        return []
    with settings.seed_file.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    owned = {r["appid"] for r in db.rows(con, "SELECT DISTINCT appid FROM ownership")}
    partly = {
        r["appid"]: r["c"]
        for r in db.rows(con, "SELECT appid, COUNT(*) c FROM ownership GROUP BY appid")
    }
    taste = _genre_taste(con)
    n = _player_count(con)

    out = []
    for s in seed:
        appid = s.get("appid")
        owners = partly.get(appid, 0)
        if owners >= n and n > 0:
            continue  # haben schon alle
        tags = [_norm_genre(t) for t in s.get("genres", [])]
        score = sum(taste.get(t, 0.0) for t in tags)
        fit = s.get("players", [1, 99])
        size_ok = fit[0] <= max(n, 1) <= fit[1]
        score = score * 100 + (10 if size_ok else 0) + (5 if owners else 0)
        out.append(
            {
                **s,
                "owners": owners,
                "already_owned": appid in owned,
                "score": round(score, 2),
                "reason": (
                    f"{owners} aus der Gruppe besitzen es schon"
                    if owners
                    else "Passt zum Geschmack der Gruppe"
                ),
            }
        )
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------- voting


def votes(con: sqlite3.Connection) -> list[dict]:
    return db.rows(
        con,
        """SELECT v.appid, g.name, g.header_image, g.icon,
                  SUM(v.value) AS score, COUNT(*) AS votes,
                  group_concat(CASE WHEN v.value > 0
                       THEN COALESCE(p.nick, p.personaname, v.steamid) END) AS yes_names,
                  group_concat(CASE WHEN v.value < 0
                       THEN COALESCE(p.nick, p.personaname, v.steamid) END) AS no_names
             FROM votes v
             JOIN games g ON g.appid = v.appid
             LEFT JOIN players p ON p.steamid = v.steamid
            GROUP BY v.appid
            ORDER BY score DESC, votes DESC""",
    )


def cast_vote(con: sqlite3.Connection, steamid: str, appid: int, value: int) -> None:
    if value == 0:
        con.execute("DELETE FROM votes WHERE steamid=? AND appid=?", (steamid, appid))
        return
    con.execute(
        """INSERT INTO votes(steamid, appid, value, ts) VALUES(?,?,?,strftime('%s','now'))
           ON CONFLICT(steamid, appid) DO UPDATE SET value=excluded.value, ts=excluded.ts""",
        (steamid, appid, 1 if value > 0 else -1),
    )


# ------------------------------------------------------------------ spiel-detail


def game_detail(con: sqlite3.Connection, appid: int) -> dict | None:
    g = db.one(con, "SELECT * FROM games WHERE appid=?", (appid,))
    if not g:
        return None
    g["genres"] = json.loads(g["genres"]) if g.get("genres") else []
    g["categories"] = json.loads(g["categories"]) if g.get("categories") else []
    g["owners"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, o.steamid) AS player, p.avatar, o.steamid,
                  o.playtime_forever AS minutes, o.last_played
             FROM ownership o JOIN players p ON p.steamid = o.steamid
            WHERE o.appid = ? ORDER BY o.playtime_forever DESC""",
        (appid,),
    )
    g["achievements"] = db.rows(
        con,
        """SELECT COALESCE(p.nick, p.personaname, a.steamid) AS player,
                  SUM(a.achieved) AS unlocked, COUNT(*) AS total
             FROM achievements a JOIN players p ON p.steamid = a.steamid
            WHERE a.appid = ? GROUP BY a.steamid ORDER BY unlocked DESC""",
        (appid,),
    )
    g["history"] = db.rows(
        con,
        """SELECT date(ts,'unixepoch','localtime') AS day,
                  COALESCE(p.nick, p.personaname, s.steamid) AS player, SUM(delta) AS minutes
             FROM playtime_snapshots s JOIN players p ON p.steamid = s.steamid
            WHERE s.appid = ? AND s.delta > 0
            GROUP BY day, s.steamid ORDER BY day DESC LIMIT 200""",
        (appid,),
    )
    return g
