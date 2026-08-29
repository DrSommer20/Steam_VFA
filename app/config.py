"""Zentrale Konfiguration - alles kommt aus .env bzw. hat sinnvolle Defaults."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("STEAM_API_KEY", "")
    db_path: Path = ROOT / os.getenv("DB_PATH", "data/steamhub.db")
    players_file: Path = ROOT / os.getenv("PLAYERS_FILE", "data/players.json")
    store_lang: str = os.getenv("STORE_LANG", "german")
    store_cc: str = os.getenv("STORE_CC", "DE")
    ach_top_games: int = _int("ACH_TOP_GAMES", 40)
    ach_refresh_hours: int = _int("ACH_REFRESH_HOURS", 168)
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _int("PORT", 8077)
    frontend_dir: Path = ROOT / "frontend"
    seed_file: Path = ROOT / "data" / "coop_seed.json"

    # --- Discord: Webhook-Meldungen aus dem Sammellauf (leer = aus) ---
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    notify_rare_pct: float = _float("NOTIFY_RARE_PCT", 5.0)
    notify_weekly_day: int = _int("NOTIFY_WEEKLY_DAY", 6)      # 0=Mo ... 6=So
    notify_weekly_hour: int = _int("NOTIFY_WEEKLY_HOUR", 18)
    notify_dormant_days: int = _int("NOTIFY_DORMANT_DAYS", 90)

    # --- Discord-Bot (eigener Container, leer = aus) ---
    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    discord_guild_id: str = os.getenv("DISCORD_GUILD_ID", "")
    discord_channel_id: str = os.getenv("DISCORD_CHANNEL_ID", "")
    hub_url: str = os.getenv("HUB_URL", "http://127.0.0.1:8077")
    public_url: str = os.getenv("PUBLIC_URL", "")
    voice_min_players: int = _int("VOICE_MIN_PLAYERS", 2)
    voice_cooldown_min: int = _int("VOICE_COOLDOWN_MIN", 180)


settings = Settings()


def load_players() -> list[dict]:
    """Spielerliste aus data/players.json: [{"steamid": "...", "nick": "..."}]"""
    if not settings.players_file.exists():
        return []
    with settings.players_file.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_players(players: list[dict]) -> None:
    settings.players_file.parent.mkdir(parents=True, exist_ok=True)
    with settings.players_file.open("w", encoding="utf-8") as fh:
        json.dump(players, fh, indent=2, ensure_ascii=False)
