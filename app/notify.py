"""Discord-Benachrichtigungen aus dem Sammellauf.

Kein Bot, kein Gateway: ein Webhook reicht. Der Sammler weiss nach jedem Lauf
ohnehin, was neu ist - hier wird daraus eine Handvoll Meldungen, die im Channel
auch wirklich jemanden interessieren.

Was gemeldet wird:
  * seltene Errungenschaften (Standard: weltweit unter 5 %)
  * Spiele, die jemand auf 100 % gebracht hat
  * Neuzugaenge im Regal, die die Runde komplettieren (oder fast)
  * sonntags ein Wochenrueckblick

Doppelmeldungen verhindert die Tabelle `discord_sent`: jedes Ereignis hat einen
Schluessel, gesendet wird nur, was dort noch nicht steht. Beim ersten Aktivieren
wird der aktuelle Bestand einmal stumm eingetragen - sonst prasseln beim
Einschalten Hunderte alter Errungenschaften in den Channel.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime

import httpx

from . import db, embeds, stats
from .config import settings

log = logging.getLogger("notify")

MAX_EMBEDS_PER_MESSAGE = 10  # Discord-Limit
MAX_PER_RUN = 20             # der Rest wartet auf den naechsten Lauf
FRESH_DAYS = 14              # aelteres gilt als Nachzuegler und wird nicht gemeldet
NEW_GAME_HOURS = 48


# ------------------------------------------------------------------ gedaechtnis


def _seen(con: sqlite3.Connection, kind: str, key: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM discord_sent WHERE kind=? AND key=?", (kind, str(key))
        ).fetchone()
    )


def _mark(con: sqlite3.Connection, kind: str, key: str) -> None:
    con.execute(
        "INSERT OR IGNORE INTO discord_sent(kind, key) VALUES(?,?)", (kind, str(key))
    )


def _first_activation(con: sqlite3.Connection) -> bool:
    row = con.execute("SELECT COUNT(*) AS c FROM discord_sent").fetchone()
    return not (row["c"] if row else 0)


# -------------------------------------------------------------------- ereignisse


def _rare(con: sqlite3.Connection) -> list[tuple[str, str, dict]]:
    since = int(time.time()) - FRESH_DAYS * 86400
    rows = db.rows(
        con,
        """SELECT a.steamid, a.appid, a.apiname, a.unlocktime,
                  COALESCE(p.nick, p.personaname, a.steamid) AS player,
                  g.name AS game, s.display, s.description,
                  s.icon AS ach_icon, s.global_pct
             FROM achievements a
             JOIN ach_schema s ON s.appid = a.appid AND s.apiname = a.apiname
             JOIN players p ON p.steamid = a.steamid
             JOIN games g ON g.appid = a.appid
            WHERE a.achieved = 1 AND a.unlocktime >= ?
              AND s.global_pct IS NOT NULL AND s.global_pct <= ?
            ORDER BY a.unlocktime ASC
            LIMIT 60""",
        (since, settings.notify_rare_pct),
    )
    return [
        ("rare", f"{r['steamid']}:{r['appid']}:{r['apiname']}", embeds.rare_achievement(r))
        for r in rows
    ]


def _perfect(con: sqlite3.Connection) -> list[tuple[str, str, dict]]:
    since = int(time.time()) - FRESH_DAYS * 86400
    rows = db.rows(
        con,
        """SELECT a.steamid, a.appid, COALESCE(p.nick, p.personaname, a.steamid) AS player,
                  g.name AS game, g.icon, g.header_image,
                  COUNT(*) AS total, MAX(a.unlocktime) AS last_unlock,
                  o.playtime_forever AS minutes
             FROM achievements a
             JOIN players p ON p.steamid = a.steamid
             JOIN games g ON g.appid = a.appid
             LEFT JOIN ownership o ON o.steamid = a.steamid AND o.appid = a.appid
            GROUP BY a.steamid, a.appid
           HAVING total >= 5 AND SUM(a.achieved) = total AND last_unlock >= ?
            ORDER BY last_unlock ASC
            LIMIT 20""",
        (since,),
    )
    return [
        ("perfect", f"{r['steamid']}:{r['appid']}", embeds.perfect_game(r)) for r in rows
    ]


def _new_games(con: sqlite3.Connection) -> list[tuple[str, str, dict]]:
    """Neu gekaufte Multiplayer-Titel, die mindestens einer aus der Runde schon hat."""
    since = int(time.time()) - NEW_GAME_HOURS * 3600
    names = {p["steamid"]: p["name"] for p in stats._players(con)}
    rows = db.rows(
        con,
        """SELECT o.steamid, o.appid, o.first_seen,
                  COALESCE(p.nick, p.personaname, o.steamid) AS player,
                  g.name, g.icon, g.header_image, g.price_cents,
                  (SELECT COUNT(*) FROM ownership x WHERE x.appid = o.appid) AS owners,
                  (SELECT group_concat(x.steamid) FROM ownership x WHERE x.appid = o.appid)
                      AS owner_ids
             FROM ownership o
             JOIN players p ON p.steamid = o.steamid
             JOIN games g ON g.appid = o.appid
            WHERE o.first_seen >= ? AND g.is_multiplayer = 1 AND g.name IS NOT NULL
            ORDER BY o.first_seen ASC
            LIMIT 20""",
        (since,),
    )
    out = []
    for r in rows:
        if r["owners"] < 2:
            continue  # Einzelkauf ohne Bezug zur Runde - kein Thema fuer den Channel
        owned_by = set((r.pop("owner_ids") or "").split(","))
        r["missing_names"] = [n for sid, n in names.items() if sid not in owned_by]
        r["player_count"] = len(names)
        out.append(("newgame", f"{r['steamid']}:{r['appid']}", embeds.new_game(r)))
    return out


def _weekly(con: sqlite3.Connection) -> list[tuple[str, str, dict]]:
    now = datetime.now()
    if now.weekday() != settings.notify_weekly_day or now.hour < settings.notify_weekly_hour:
        return []
    year, week, _ = now.isocalendar()
    data = stats.week_summary(con)
    if not data["minutes"] and not data["new_games"] and not data["achievements"]:
        return []  # tote Woche - dann lieber gar nichts posten
    return [("weekly", f"{year}-W{week:02d}", embeds.weekly(data))]


def pending(con: sqlite3.Connection) -> list[tuple[str, str, dict]]:
    """Alle noch nicht gemeldeten Ereignisse, in sinnvoller Reihenfolge."""
    events = _new_games(con) + _rare(con) + _perfect(con) + _weekly(con)
    return [e for e in events if not _seen(con, e[0], e[1])]


# ---------------------------------------------------------------------- versand


async def _post(client: httpx.AsyncClient, batch: list[dict]) -> bool:
    payload = {"username": "Steam Group Hub", "embeds": batch}
    for attempt in range(3):
        try:
            res = await client.post(settings.discord_webhook_url, json=payload)
        except httpx.HTTPError as exc:
            log.warning("Webhook nicht erreichbar: %s", exc)
            return False
        if res.status_code == 429:
            wait = float((res.json() or {}).get("retry_after", 2))
            log.info("Discord bremst uns aus, %.1fs warten", wait)
            await asyncio.sleep(min(wait, 30) + 0.5)
            continue
        if res.is_success:
            return True
        log.warning("Webhook antwortete %s: %s", res.status_code, res.text[:200])
        return False
    return False


async def send(items: list[tuple[str, str, dict]]) -> int:
    """Ereignisse posten und erst nach erfolgreichem Versand als erledigt merken."""
    sent = 0
    async with httpx.AsyncClient(timeout=20.0) as client:
        for i in range(0, len(items), MAX_EMBEDS_PER_MESSAGE):
            batch = items[i : i + MAX_EMBEDS_PER_MESSAGE]
            if not await _post(client, [e for _, _, e in batch]):
                break
            with db.session() as con:
                for kind, key, _ in batch:
                    _mark(con, kind, key)
            sent += len(batch)
            await asyncio.sleep(1.0)
    return sent


async def after_collect() -> int:
    """Haengt am Ende jedes Sammellaufs. Gibt zurueck, wie viele Meldungen rausgingen."""
    if not settings.discord_webhook_url:
        return 0

    with db.session() as con:
        first = _first_activation(con)
        items = pending(con)
        if first:
            # Bestand stumm uebernehmen, damit der Channel nicht geflutet wird.
            for kind, key, _ in items:
                _mark(con, kind, key)
            items = []

    if first:
        await send([("hello", "1", embeds.hello())])
        log.info("Discord aktiviert - Ausgangslage uebernommen")
        return 1

    if not items:
        return 0
    if len(items) > MAX_PER_RUN:
        log.info("%d Meldungen offen, sende %d - Rest folgt", len(items), MAX_PER_RUN)
        items = items[:MAX_PER_RUN]
    n = await send(items)
    log.info("%d Discord-Meldungen gesendet", n)
    return n
