"""SQLite-Layer. Bewusst schlank: ein File, WAL-Mode, Schema per CREATE IF NOT EXISTS."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS players (
    steamid      TEXT PRIMARY KEY,
    nick         TEXT,
    personaname  TEXT,
    avatar       TEXT,
    profileurl   TEXT,
    country      TEXT,
    timecreated  INTEGER,
    lastlogoff   INTEGER,
    personastate INTEGER,
    visibility   INTEGER,
    added_at     INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS games (
    appid           INTEGER PRIMARY KEY,
    name            TEXT,
    icon            TEXT,
    -- Store-Metadaten (aus appdetails, wird nur einmal geholt und gecached)
    meta_fetched_at INTEGER,
    meta_ok         INTEGER DEFAULT 0,
    short_desc      TEXT,
    header_image    TEXT,
    release_date    TEXT,
    metacritic      INTEGER,
    price_cents     INTEGER,
    genres          TEXT,   -- JSON-Array
    categories      TEXT,   -- JSON-Array mit Category-IDs
    is_multiplayer  INTEGER DEFAULT 0,
    is_coop         INTEGER DEFAULT 0,
    is_pvp          INTEGER DEFAULT 0,
    max_players_hint TEXT
);

CREATE TABLE IF NOT EXISTS ownership (
    steamid          TEXT NOT NULL,
    appid            INTEGER NOT NULL,
    playtime_forever INTEGER DEFAULT 0,
    playtime_2weeks  INTEGER DEFAULT 0,
    last_played      INTEGER DEFAULT 0,
    first_seen       INTEGER DEFAULT (strftime('%s','now')),
    last_seen        INTEGER DEFAULT (strftime('%s','now')),
    PRIMARY KEY (steamid, appid)
);
CREATE INDEX IF NOT EXISTS idx_ownership_app ON ownership(appid);

-- Zeitreihe: nur schreiben wenn sich die Spielzeit veraendert hat.
-- Daraus bauen wir Sessions, Aktivitaets-Feed und Charts.
CREATE TABLE IF NOT EXISTS playtime_snapshots (
    steamid          TEXT NOT NULL,
    appid            INTEGER NOT NULL,
    ts               INTEGER NOT NULL,
    playtime_forever INTEGER NOT NULL,
    delta            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (steamid, appid, ts)
);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON playtime_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_snap_app ON playtime_snapshots(appid, ts);

CREATE TABLE IF NOT EXISTS ach_schema (
    appid       INTEGER NOT NULL,
    apiname     TEXT NOT NULL,
    display     TEXT,
    description TEXT,
    icon        TEXT,
    global_pct  REAL,
    PRIMARY KEY (appid, apiname)
);

CREATE TABLE IF NOT EXISTS achievements (
    steamid    TEXT NOT NULL,
    appid      INTEGER NOT NULL,
    apiname    TEXT NOT NULL,
    achieved   INTEGER DEFAULT 0,
    unlocktime INTEGER DEFAULT 0,
    PRIMARY KEY (steamid, appid, apiname)
);
CREATE INDEX IF NOT EXISTS idx_ach_unlock ON achievements(unlocktime);

-- Merkt sich, wann wir Achievements zuletzt geholt haben (spart API-Calls).
CREATE TABLE IF NOT EXISTS ach_state (
    steamid       TEXT NOT NULL,
    appid         INTEGER NOT NULL,
    last_fetch    INTEGER DEFAULT 0,
    last_playtime INTEGER DEFAULT 0,
    ok            INTEGER DEFAULT 1,
    PRIMARY KEY (steamid, appid)
);

-- "Was zocken wir Freitag?" - simples Voting, ohne Login, auf Vertrauensbasis.
CREATE TABLE IF NOT EXISTS votes (
    steamid TEXT NOT NULL,
    appid   INTEGER NOT NULL,
    value   INTEGER NOT NULL,  -- +1 / -1
    ts      INTEGER DEFAULT (strftime('%s','now')),
    PRIMARY KEY (steamid, appid)
);

-- Discord: was schon gepostet wurde. Verhindert Doppelmeldungen ueber
-- Neustarts hinweg und beim ersten Aktivieren die grosse Nachhol-Lawine.
CREATE TABLE IF NOT EXISTS discord_sent (
    kind TEXT NOT NULL,
    key  TEXT NOT NULL,
    ts   INTEGER DEFAULT (strftime('%s','now')),
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS idx_discord_sent_ts ON discord_sent(ts);

-- Discord-Konto <-> Steam-Spieler. Damit zaehlt eine Stimme aus Discord
-- genauso wie eine aus dem Web - nur eben nachvollziehbar, wer sie abgab.
CREATE TABLE IF NOT EXISTS discord_links (
    discord_id TEXT PRIMARY KEY,
    steamid    TEXT NOT NULL,
    username   TEXT,
    linked_at  INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS collect_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER,
    finished_at INTEGER,
    ok          INTEGER DEFAULT 0,
    players     INTEGER DEFAULT 0,
    games       INTEGER DEFAULT 0,
    new_games   INTEGER DEFAULT 0,
    minutes_new INTEGER DEFAULT 0,
    note        TEXT
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or settings.db_path
    p.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False, weil FastAPI eine Request-Dependency ueber mehrere
    # Threadpool-Threads reichen kann. Jede Verbindung gehoert genau einem Request.
    con = sqlite3.connect(p, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init(path: Path | None = None) -> None:
    with connect(path) as con:
        con.executescript(SCHEMA)


@contextmanager
def session(path: Path | None = None):
    con = connect(path)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def rows(con: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(con: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> dict | None:
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None
