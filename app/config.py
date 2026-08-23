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
