"""Duenner async-Client fuer die Steam Web API + die (inoffizielle) Store-API.

Gutmuetig gebaut: private Profile, fehlende Achievements und Rate-Limits fuehren
nicht zum Abbruch, sondern zu einem leeren Ergebnis + Log-Zeile.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from .config import settings

log = logging.getLogger("steam")

API = "https://api.steampowered.com"
STORE = "https://store.steampowered.com/api"

# Category-IDs aus der Store-API, die uns fuer "koennen wir das zusammen spielen?" interessieren
CAT_MULTIPLAYER = {1, 20, 27, 36, 38, 39, 47, 49}
CAT_COOP = {9, 38, 39, 48}
CAT_PVP = {36, 37, 47, 49}

STEAMID64_RE = re.compile(r"^7656119\d{10}$")


class SteamError(RuntimeError):
    pass


class SteamClient:
    def __init__(self, api_key: str | None = None, concurrency: int = 4):
        self.key = api_key or settings.api_key
        if not self.key:
            raise SteamError("STEAM_API_KEY fehlt - siehe .env.example")
        self._sem = asyncio.Semaphore(concurrency)
        self._store_lock = asyncio.Lock()
        self._store_last = 0.0
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": "steam-vfa-hub/1.0"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> "SteamClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------------- plumbing

    async def _get(self, url: str, params: dict, *, tries: int = 4) -> dict | None:
        delay = 2.0
        for attempt in range(tries):
            async with self._sem:
                try:
                    r = await self._client.get(url, params=params)
                except httpx.HTTPError as exc:
                    log.warning("netzwerk-fehler %s (%s)", url, exc)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    return None
            if r.status_code in (401, 403):
                # privates Profil / keine Stats fuer dieses Spiel -> kein Retry
                return None
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503):
                log.warning("status %s bei %s - warte %.0fs", r.status_code, url, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            log.warning("unerwarteter status %s bei %s", r.status_code, url)
            return None
        return None

    # ------------------------------------------------------------------ people

    async def resolve_vanity(self, vanity: str) -> str | None:
        data = await self._get(
            f"{API}/ISteamUser/ResolveVanityURL/v1/",
            {"key": self.key, "vanityurl": vanity},
        )
        res = (data or {}).get("response", {})
        return res.get("steamid") if res.get("success") == 1 else None

    async def resolve_any(self, ident: str) -> str | None:
        """Nimmt SteamID64, Profil-URL oder Vanity-Namen entgegen."""
        ident = ident.strip().rstrip("/")
        if STEAMID64_RE.match(ident):
            return ident
        m = re.search(r"steamcommunity\.com/profiles/(\d{17})", ident)
        if m:
            return m.group(1)
        m = re.search(r"steamcommunity\.com/id/([^/?#]+)", ident)
        if m:
            return await self.resolve_vanity(m.group(1))
        return await self.resolve_vanity(ident)

    async def player_summaries(self, steamids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(steamids), 100):
            chunk = steamids[i : i + 100]
            data = await self._get(
                f"{API}/ISteamUser/GetPlayerSummaries/v2/",
                {"key": self.key, "steamids": ",".join(chunk)},
            )
            out.extend((data or {}).get("response", {}).get("players", []))
        return out

    # ------------------------------------------------------------------ library

    async def owned_games(self, steamid: str) -> list[dict]:
        data = await self._get(
            f"{API}/IPlayerService/GetOwnedGames/v1/",
            {
                "key": self.key,
                "steamid": steamid,
                "include_appinfo": 1,
                "include_played_free_games": 1,
                "skip_unvetted_apps": 0,
            },
        )
        return (data or {}).get("response", {}).get("games", []) or []

    async def recently_played(self, steamid: str) -> list[dict]:
        data = await self._get(
            f"{API}/IPlayerService/GetRecentlyPlayedGames/v1/",
            {"key": self.key, "steamid": steamid},
        )
        return (data or {}).get("response", {}).get("games", []) or []

    # ------------------------------------------------------------- achievements

    async def player_achievements(self, steamid: str, appid: int) -> list[dict] | None:
        """None = Spiel hat keine Achievements oder Profil/Stats sind privat."""
        data = await self._get(
            f"{API}/ISteamUserStats/GetPlayerAchievements/v1/",
            {"key": self.key, "steamid": steamid, "appid": appid, "l": "german"},
        )
        stats = (data or {}).get("playerstats", {})
        if not stats.get("success"):
            return None
        return stats.get("achievements", []) or []

    async def game_schema(self, appid: int) -> list[dict]:
        data = await self._get(
            f"{API}/ISteamUserStats/GetSchemaForGame/v2/",
            {"key": self.key, "appid": appid, "l": "german"},
        )
        stats = (data or {}).get("game", {}).get("availableGameStats", {})
        return stats.get("achievements", []) or []

    async def global_achievement_pct(self, appid: int) -> dict[str, float]:
        data = await self._get(
            f"{API}/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/",
            {"gameid": appid},
        )
        items = (data or {}).get("achievementpercentages", {}).get("achievements", []) or []
        return {i["name"]: float(i["percent"]) for i in items if "name" in i}

    # -------------------------------------------------------------- store meta

    async def app_details(self, appid: int) -> dict | None:
        """Inoffizielle Store-API - hart gedrosselt (ca. 200 Requests / 5 Min)."""
        async with self._store_lock:
            wait = 1.6 - (time.monotonic() - self._store_last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._store_last = time.monotonic()
        data = await self._get(
            f"{STORE}/appdetails",
            {
                "appids": appid,
                "l": settings.store_lang,
                "cc": settings.store_cc,
            },
            tries=3,
        )
        entry = (data or {}).get(str(appid))
        if not entry or not entry.get("success"):
            return None
        return entry.get("data")


def classify_categories(cats: list[dict]) -> tuple[list[int], bool, bool, bool]:
    ids = [c["id"] for c in cats if isinstance(c, dict) and "id" in c]
    s = set(ids)
    return (
        ids,
        bool(s & CAT_MULTIPLAYER),
        bool(s & CAT_COOP),
        bool(s & CAT_PVP),
    )
