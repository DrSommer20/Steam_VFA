"""Duenner Client fuer die Hub-API.

Der Bot hat bewusst keinen eigenen Datenbankzugriff: alles laeuft ueber HTTP
gegen den steamhub-Container. So gibt es genau eine Stelle, die Regeln kennt,
und Web-Oberflaeche und Discord zeigen immer denselben Stand.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("bot.api")


class HubError(RuntimeError):
    """Fehler, dessen Text man dem Nutzer im Channel zeigen kann."""


class HubAPI:
    def __init__(self, base_url: str, token: str = "") -> None:
        self._token = token
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=20.0)

    async def close(self) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------------- plumbing

    async def _request(self, method: str, path: str, **kw) -> Any:
        try:
            res = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise HubError(f"Der Hub antwortet nicht ({exc.__class__.__name__}).") from exc
        if res.status_code >= 400:
            detail = ""
            try:
                detail = (res.json() or {}).get("detail", "")
            except ValueError:
                pass
            raise HubError(detail or f"Hub antwortete mit {res.status_code}.")
        return res.json()

    async def get(self, path: str, **params) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, payload: dict) -> Any:
        return await self._request("POST", path, params={"token": self._token}, json=payload)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path, params={"token": self._token})

    # ------------------------------------------------------------ auswertungen

    async def recommendations(self, limit: int = 10) -> dict:
        return await self.get("/api/recommendations", limit=limit)

    async def suggest(self, steamids: list[str], limit: int = 5) -> list[dict]:
        return await self.get("/api/suggest", steamids=",".join(steamids), limit=limit)

    async def dormant(self, min_days: int = 90, limit: int = 5) -> list[dict]:
        return await self.get("/api/dormant", min_days=min_days, limit=limit)

    async def votes(self) -> list[dict]:
        return await self.get("/api/votes")

    async def players(self) -> list[dict]:
        return await self.get("/api/players")

    async def library(self, search: str = "", limit: int = 25, **kw) -> list[dict]:
        return await self.get("/api/library", search=search, limit=limit, **kw)

    async def game(self, appid: int) -> dict:
        return await self.get(f"/api/game/{appid}")

    async def leaderboards(self) -> dict:
        return await self.get("/api/leaderboards")

    async def rare(self, limit: int = 5, max_pct: float = 5.0) -> list[dict]:
        return await self.get("/api/achievements/rare", limit=limit, max_pct=max_pct)

    async def activity(self, days: int = 7, limit: int = 10) -> list[dict]:
        return await self.get("/api/activity", days=days, limit=limit)

    # ----------------------------------------------------------------- discord

    async def links(self) -> dict[str, str]:
        """Discord-ID -> SteamID."""
        return {r["discord_id"]: r["steamid"] for r in await self.get("/api/discord/links")}

    async def link(self, discord_id: int | str, player: str, username: str = "") -> dict:
        return await self.post(
            "/api/discord/link",
            {"discord_id": str(discord_id), "player": player, "username": username},
        )

    async def unlink(self, discord_id: int | str) -> Any:
        return await self.delete(f"/api/discord/link/{discord_id}")

    async def vote(self, discord_id: int | str, appid: int, value: int) -> dict:
        return await self.post(
            "/api/discord/vote",
            {"discord_id": str(discord_id), "appid": appid, "value": value},
        )
