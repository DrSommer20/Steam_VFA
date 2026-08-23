"""FastAPI-App: liefert die JSON-API und das statische Frontend aus.

Start lokal:   python -m app.main
Start prod:    uvicorn app.main:app --host 127.0.0.1 --port 8077
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import collect, db, stats
from .config import settings

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(
    title="Steam Group Hub",
    version="1.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

_collect_lock = asyncio.Lock()


def get_db():
    con = db.connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


Con = Annotated[sqlite3.Connection, Depends(get_db)]


# ------------------------------------------------------------------------ api


@app.get("/api/health")
def health(con: Con):
    run = db.one(con, "SELECT * FROM collect_runs ORDER BY id DESC LIMIT 1")
    return {"ok": True, "now": int(time.time()), "last_run": run}


@app.get("/api/overview")
def api_overview(con: Con):
    return stats.overview(con)


@app.get("/api/players")
def api_players(con: Con):
    return stats.players_detail(con)


@app.get("/api/library")
def api_library(
    con: Con,
    min_owners: int = 1,
    multiplayer_only: bool = False,
    unplayed_only: bool = False,
    search: str = "",
    sort: str = "owners",
    limit: int = Query(300, le=2000),
):
    return stats.library(con, min_owners, multiplayer_only, unplayed_only, search, sort, limit)


@app.get("/api/matrix")
def api_matrix(con: Con):
    return stats.matrix(con)


@app.get("/api/activity")
def api_activity(con: Con, days: int = Query(14, ge=1, le=365), limit: int = Query(60, le=500)):
    return stats.activity(con, days, limit)


@app.get("/api/timeline")
def api_timeline(con: Con, days: int = Query(30, ge=7, le=365)):
    return stats.timeline(con, days)


@app.get("/api/heatmap")
def api_heatmap(con: Con):
    return stats.hours_heatmap(con)


@app.get("/api/achievements/rare")
def api_rare(con: Con, max_pct: float = 10.0, limit: int = Query(40, le=200)):
    return stats.rare_achievements(con, max_pct, limit)


@app.get("/api/achievements/recent")
def api_recent_ach(con: Con, limit: int = Query(40, le=200)):
    return stats.recent_achievements(con, limit)


@app.get("/api/achievements/completion")
def api_completion(con: Con, limit: int = Query(30, le=200)):
    return stats.completion(con, limit)


@app.get("/api/leaderboards")
def api_leaderboards(con: Con):
    return stats.leaderboards(con)


@app.get("/api/awards")
def api_awards(con: Con):
    return stats.awards(con)


@app.get("/api/recommendations")
def api_recommendations(con: Con, limit: int = Query(15, le=100)):
    return stats.recommendations(con, limit)


@app.get("/api/discover")
def api_discover(con: Con, limit: int = Query(20, le=100)):
    return stats.discover(con, limit)


@app.get("/api/game/{appid}")
def api_game(appid: int, con: Con):
    g = stats.game_detail(con, appid)
    if not g:
        raise HTTPException(404, "Spiel nicht in der Datenbank")
    return g


@app.get("/api/votes")
def api_votes(con: Con):
    return stats.votes(con)


@app.post("/api/votes")
def api_vote(con: Con, payload: dict = Body(...)):
    try:
        steamid = str(payload["steamid"])
        appid = int(payload["appid"])
        value = int(payload["value"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "steamid, appid und value erforderlich")
    if not db.one(con, "SELECT 1 FROM players WHERE steamid=?", (steamid,)):
        raise HTTPException(400, "unbekannter Spieler")
    stats.cast_vote(con, steamid, appid, value)
    con.commit()
    return stats.votes(con)


@app.post("/api/collect")
async def api_collect(token: str = Query("")):
    """Sammellauf manuell anstossen (nur wenn ADMIN_TOKEN gesetzt ist)."""
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(403, "ADMIN_TOKEN fehlt oder falsch")
    if _collect_lock.locked():
        return JSONResponse({"status": "laeuft bereits"}, status_code=409)
    async with _collect_lock:
        return await collect.run()


# ------------------------------------------------------------------- frontend

if settings.frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(settings.frontend_dir / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
