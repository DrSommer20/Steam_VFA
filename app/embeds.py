"""Discord-Embeds bauen - reine Formatierung, kein DB-Zugriff.

Bewusst als nackte Dicts statt discord.py-Objekte: der Webhook aus dem
Sammellauf (app/notify.py) kommt ohne die Bibliothek aus, der Bot (bot/)
reicht dieselben Dicts an discord.Embed.from_dict weiter.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import settings

COLOR_RARE = 0x8B5CF6
COLOR_PERFECT = 0xF59E0B
COLOR_NEW = 0x22C55E
COLOR_WEEKLY = 0x3B82F6
COLOR_SUGGEST = 0x06B6D4
COLOR_VOTE = 0xF97316
COLOR_INFO = 0x64748B

STORE = "https://store.steampowered.com/app/{}"
ICON = "https://media.steampowered.com/steamcommunity/public/images/apps/{}/{}.jpg"


def store_url(appid: int) -> str:
    return STORE.format(appid)


def icon_url(appid: int, icon: str | None) -> str | None:
    return ICON.format(appid, icon) if icon else None


def hours(minutes: int | None) -> str:
    m = int(minutes or 0)
    if m < 60:
        return f"{m} min"
    return f"{m / 60:.1f} h".replace(".", ",")


def euro(cents: int | None) -> str:
    return f"{(cents or 0) / 100:.2f} EUR".replace(".", ",") if cents else "-"


def cut(text: str | None, n: int = 1024) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _ts(unix: int) -> str:
    return datetime.fromtimestamp(int(unix), tz=timezone.utc).isoformat()


def _base(title: str, color: int, **extra) -> dict:
    """Grundgeruest inkl. Fusszeile - die zeigt den Hub nur, wenn PUBLIC_URL gesetzt ist."""
    e = {"title": cut(title, 256), "color": color, **extra}
    if settings.public_url:
        e["footer"] = {"text": settings.public_url}
    return e


# ------------------------------------------------------------------- meldungen


def rare_achievement(r: dict) -> dict:
    pct = f"{r.get('global_pct') or 0:.1f}".replace(".", ",")
    e = _base(
        "💎 " + (r.get("display") or r.get("apiname") or "Errungenschaft"),
        COLOR_RARE,
        url=store_url(r["appid"]),
        description=(
            f"**{r['player']}** hat das in *{r['game']}* geschafft - "
            f"weltweit haben es nur **{pct} %**."
        ),
    )
    if r.get("description"):
        e["fields"] = [{"name": "Wofür", "value": cut(r["description"]), "inline": False}]
    if r.get("ach_icon"):
        e["thumbnail"] = {"url": r["ach_icon"]}
    if r.get("unlocktime"):
        e["timestamp"] = _ts(r["unlocktime"])
    return e


def perfect_game(r: dict) -> dict:
    e = _base(
        f"🏆 {r['game']} zu 100 %",
        COLOR_PERFECT,
        url=store_url(r["appid"]),
        description=(
            f"**{r['player']}** hat alle **{r['total']}** Errungenschaften eingesammelt"
            + (f" - {hours(r.get('minutes'))} hat es gedauert." if r.get("minutes") else ".")
        ),
    )
    img = r.get("header_image") or icon_url(r["appid"], r.get("icon"))
    if img:
        e["thumbnail"] = {"url": img}
    if r.get("last_unlock"):
        e["timestamp"] = _ts(r["last_unlock"])
    return e


def new_game(r: dict) -> dict:
    """Neuzugang im Regal - interessant vor allem, wenn er die Runde komplettiert."""
    owners, total = r["owners"], r.get("player_count") or r["owners"]
    missing = r.get("missing_names") or []
    if owners >= total:
        note = "🎉 **Damit haben es alle** - ab sofort sofort spielbereit."
    elif len(missing) == 1:
        note = f"Nur **{missing[0]}** fehlt noch ({euro(r.get('price_cents'))})."
    else:
        note = f"{owners} von {total} besitzen es jetzt."
    e = _base(
        f"🆕 {r['name']}",
        COLOR_NEW,
        url=store_url(r["appid"]),
        description=f"**{r['player']}** hat es neu im Regal.\n{note}",
    )
    if r.get("header_image"):
        e["image"] = {"url": r["header_image"]}
    elif r.get("icon"):
        e["thumbnail"] = {"url": icon_url(r["appid"], r["icon"])}
    return e


def weekly(data: dict) -> dict:
    medals = ["🥇", "🥈", "🥉"]
    fields = []

    board = [p for p in data["players"] if p["minutes"] > 0]
    if board:
        fields.append(
            {
                "name": "Spielzeit der Woche",
                "value": cut(
                    "\n".join(
                        f"{medals[i] if i < 3 else '▪️'} **{p['player']}** - {hours(p['minutes'])}"
                        for i, p in enumerate(board[:8])
                    )
                ),
                "inline": False,
            }
        )
    if data.get("games"):
        fields.append(
            {
                "name": "Meistgespielt",
                "value": cut(
                    "\n".join(
                        f"[{g['name']}]({store_url(g['appid'])}) - {hours(g['minutes'])}"
                        f" ({g['players']} Leute)"
                        for g in data["games"]
                    )
                ),
                "inline": False,
            }
        )
    if data.get("dormant"):
        d = data["dormant"][0]
        fields.append(
            {
                "name": "🕸️ Staubfänger der Woche",
                "value": cut(
                    f"[{d['name']}]({store_url(d['appid'])}) - alle besitzen es, "
                    f"seit **{d['days_since']} Tagen** hat es keiner mehr gestartet."
                ),
                "inline": False,
            }
        )

    summary = (
        f"**{hours(data['minutes'])}** zusammen gespielt · "
        f"**{data['achievements']}** Errungenschaften · "
        f"**{data['new_games']}** Neuzugänge"
    )
    return _base("📊 Die Woche der Runde", COLOR_WEEKLY, description=summary, fields=fields)


# ----------------------------------------------------------------- vorschlaege


def suggestion(games: list[dict], names: list[str] | None = None) -> dict:
    who = ""
    if names:
        who = ", ".join(names[:-1]) + " und " + names[-1] if len(names) > 1 else names[0]
    lines = [
        f"**[{g['name']}]({store_url(g['appid'])})**\n{g.get('reason') or ''}".rstrip()
        for g in games
    ]
    return _base(
        "🎮 Ihr seid im Voice - wie wär's damit?" if names else "🎮 Spielideen",
        COLOR_SUGGEST,
        description=cut(
            (f"{who} könnt das hier alle zusammen spielen:\n\n" if who else "")
            + "\n\n".join(lines),
            4000,
        ),
    )


def vote_board(rows: list[dict], title: str = "🗳️ Was zocken wir?") -> dict:
    if not rows:
        return _base(
            title,
            COLOR_VOTE,
            description="Noch keine Stimmen. Mit `/zocken` gibt es Vorschläge zum Abstimmen.",
        )
    lines = []
    for r in rows[:15]:
        yes = [n for n in (r.get("yes_names") or "").split(",") if n]
        no = [n for n in (r.get("no_names") or "").split(",") if n]
        detail = " · ".join(
            x
            for x in (
                ("👍 " + ", ".join(yes)) if yes else "",
                ("👎 " + ", ".join(no)) if no else "",
            )
            if x
        )
        lines.append(
            f"`{r['score']:+d}` **[{r['name']}]({store_url(r['appid'])})**"
            + (f"\n　　{detail}" if detail else "")
        )
    return _base(title, COLOR_VOTE, description=cut("\n".join(lines), 4000))


def game_card(g: dict) -> dict:
    owners = g.get("owners") or []
    fields = [
        {
            "name": f"Besitzer ({len(owners)})",
            "value": cut(
                "\n".join(f"**{o['player']}** - {hours(o['minutes'])}" for o in owners[:12]) or "-"
            ),
            "inline": True,
        }
    ]
    if g.get("achievements"):
        fields.append(
            {
                "name": "Errungenschaften",
                "value": cut(
                    "\n".join(
                        f"**{a['player']}** {a['unlocked']}/{a['total']}"
                        for a in g["achievements"][:12]
                    )
                ),
                "inline": True,
            }
        )
    meta = " · ".join(
        x
        for x in (
            ", ".join(g.get("genres") or [])[:80],
            f"Metacritic {g['metacritic']}" if g.get("metacritic") else "",
            euro(g.get("price_cents")) if g.get("price_cents") else "",
            g.get("release_date") or "",
        )
        if x
    )
    e = _base(
        g.get("name") or str(g["appid"]),
        COLOR_INFO,
        url=store_url(g["appid"]),
        description=cut((g.get("short_desc") or "") + (f"\n\n*{meta}*" if meta else ""), 2000),
        fields=fields,
    )
    if g.get("header_image"):
        e["image"] = {"url": g["header_image"]}
    return e


def leaderboard(rows: list[dict], title: str, fmt=str) -> dict:
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i] if i < 3 else '▪️'} **{r['player']}** - {fmt(r['value'])}"
        for i, r in enumerate(rows[:10])
    ]
    return _base(title, COLOR_WEEKLY, description=cut("\n".join(lines) or "-", 4000))


def hello() -> dict:
    return _base(
        "👋 Der Steam Hub hängt jetzt am Discord",
        COLOR_INFO,
        description=(
            "Ab sofort melde ich hier seltene Errungenschaften, 100-%-Spiele und "
            "Neuzugänge, die die Runde komplettieren - dazu sonntags einen Rückblick.\n\n"
            "Der Bestand von heute ist die Ausgangslage, den poste ich nicht nach."
        ),
    )
