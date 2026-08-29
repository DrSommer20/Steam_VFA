"""Discord-Bot fuer den Steam Group Hub.

Er bringt zwei Dinge in den Channel, die im Web niemand aufmacht:

  * **Abstimmen, wo die Runde sowieso ist.** `/zocken` postet Vorschlaege mit
    Daumen-Buttons; die Stimme landet in derselben Datenbank wie die aus dem
    Web (`POST /api/discord/vote`), nur eben mit Namen dran.
  * **Der Anstupser im Voice.** Sobald genug verknuepfte Leute in einem
    Sprachkanal sitzen, sucht der Bot Spiele, die *genau diese* Leute alle
    besitzen und lange nicht gestartet haben.

Start:  python -m bot.bot     (Container-Command, siehe docker-compose.yml)
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands

from app import embeds
from app.config import settings

from .api import HubAPI, HubError

log = logging.getLogger("bot")

VOTE_PREFIX = "vote:"
LABEL_PREFIX = "game:"
MAX_VOTE_ROWS = 5  # Discord erlaubt fuenf Button-Reihen pro Nachricht


# --------------------------------------------------------------------- buttons


class VoteView(discord.ui.View):
    """Pro Spiel eine Reihe: Titel, Daumen hoch, Daumen runter.

    Die Buttons haben keine eigenen Callbacks - geklickt wird zentral in
    `HubBot.on_interaction` ausgewertet. Das ueberlebt einen Neustart des Bots:
    die noetige Information (welches Spiel, welche Richtung) steckt komplett in
    der custom_id, nicht in einem Objekt im Speicher.
    """

    def __init__(self, games: list[dict]) -> None:
        super().__init__(timeout=None)
        for row, g in enumerate(games[:MAX_VOTE_ROWS]):
            appid = g["appid"]
            self.add_item(
                discord.ui.Button(
                    label=embeds.cut(g["name"], 60),
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                    row=row,
                    custom_id=f"{LABEL_PREFIX}{appid}",
                )
            )
            self.add_item(
                discord.ui.Button(
                    emoji="👍",
                    style=discord.ButtonStyle.success,
                    row=row,
                    custom_id=f"{VOTE_PREFIX}{appid}:1",
                )
            )
            self.add_item(
                discord.ui.Button(
                    emoji="👎",
                    style=discord.ButtonStyle.danger,
                    row=row,
                    custom_id=f"{VOTE_PREFIX}{appid}:-1",
                )
            )


def games_of(message: discord.Message) -> list[tuple[int, str]]:
    """Welche Spiele stehen in dieser Nachricht zur Wahl? (aus den Buttons gelesen)"""
    out = []
    for row in message.components:
        for item in getattr(row, "children", []):
            cid = getattr(item, "custom_id", "") or ""
            if cid.startswith(LABEL_PREFIX):
                out.append((int(cid[len(LABEL_PREFIX) :]), item.label or str(cid)))
    return out


def tally_field(games: list[tuple[int, str]], votes: list[dict]) -> dict:
    by_app = {v["appid"]: v for v in votes}
    lines = []
    for appid, name in games:
        v = by_app.get(appid)
        if not v:
            lines.append(f"`  0` {name}")
            continue
        who = " · ".join(
            x
            for x in (
                ("👍 " + ", ".join(n for n in (v.get("yes_names") or "").split(",") if n)),
                ("👎 " + ", ".join(n for n in (v.get("no_names") or "").split(",") if n)),
            )
            if len(x) > 2
        )
        lines.append(f"`{v['score']:+3d}` {name}" + (f" — {who}" if who else ""))
    return {"name": "Stimmen", "value": embeds.cut("\n".join(lines)), "inline": False}


def with_tally(embed: discord.Embed, games, votes) -> discord.Embed:
    data = embed.to_dict()
    data["fields"] = [f for f in data.get("fields", []) if f["name"] != "Stimmen"]
    data["fields"].append(tally_field(games, votes))
    return discord.Embed.from_dict(data)


# ------------------------------------------------------------------------- bot


class HubBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        intents.members = True  # fuer die Mitglieder eines Sprachkanals noetig
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.api = HubAPI(settings.hub_url, settings.admin_token)
        self._voice_seen: dict[int, float] = {}

    async def setup_hook(self) -> None:
        if settings.discord_guild_id:
            # Auf einen Server begrenzt sind die Befehle sofort da statt nach einer Stunde.
            guild = discord.Object(id=int(settings.discord_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def close(self) -> None:
        await self.api.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("angemeldet als %s", self.user)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="eure Steam-Bibliotheken"
            )
        )

    # ------------------------------------------------------------ vote-buttons

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if not cid.startswith(VOTE_PREFIX):
            return

        appid, _, raw = cid[len(VOTE_PREFIX) :].partition(":")
        try:
            result = await self.api.vote(interaction.user.id, int(appid), int(raw))
        except HubError as exc:
            await interaction.response.send_message(
                f"{exc}\nTipp: einmal `/verbinden` und deine Stimme zaehlt.", ephemeral=True
            )
            return

        # Nur das Embed anfassen: die Buttons bleiben, wie sie sind - sie tragen
        # ihre Bedeutung selbst und funktionieren auch nach einem Neustart weiter.
        message = interaction.message
        embed = message.embeds[0] if message.embeds else discord.Embed(title="Abstimmung")
        await interaction.response.edit_message(
            embed=with_tally(embed, games_of(message), result["votes"])
        )

    # ------------------------------------------------------------ voice-trigger

    async def on_voice_state_update(self, member, before, after) -> None:
        channel = after.channel
        if channel is None or (before.channel and before.channel.id == channel.id):
            return
        if member.bot:
            return

        last = self._voice_seen.get(channel.id, 0.0)
        if time.time() - last < settings.voice_cooldown_min * 60:
            return

        present = [m for m in channel.members if not m.bot]
        if len(present) < settings.voice_min_players:
            return

        try:
            links = await self.api.links()
            known = [(m, links[str(m.id)]) for m in present if str(m.id) in links]
            if len(known) < settings.voice_min_players:
                return
            games = await self.api.suggest([sid for _, sid in known], limit=MAX_VOTE_ROWS)
        except HubError as exc:
            log.warning("Voice-Vorschlag fehlgeschlagen: %s", exc)
            return
        if not games:
            return

        self._voice_seen[channel.id] = time.time()
        target = channel
        if settings.discord_channel_id:
            target = self.get_channel(int(settings.discord_channel_id)) or channel
        embed = embeds.suggestion(games, [m.display_name for m, _ in known])
        await target.send(embed=discord.Embed.from_dict(embed), view=VoteView(games))


client = HubBot()
tree = client.tree


# ------------------------------------------------------------------- befehle


async def _fail(interaction: discord.Interaction, exc: Exception) -> None:
    text = str(exc) if isinstance(exc, HubError) else "Da ist etwas schiefgelaufen."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


@tree.command(name="zocken", description="Spielideen für die Runde - mit Abstimmung")
@app_commands.describe(anzahl="Wie viele Vorschläge? (1-5)")
async def cmd_zocken(interaction: discord.Interaction, anzahl: int = 5):
    await interaction.response.defer()
    try:
        rec = await client.api.recommendations(limit=10)
        votes = await client.api.votes()
    except HubError as exc:
        return await _fail(interaction, exc)

    picked: list[dict] = []
    seen: set[int] = set()
    for bucket in ("ready_to_play", "backlog_gems", "trending", "almost_there"):
        for g in rec.get(bucket) or []:
            if g["appid"] in seen:
                continue
            seen.add(g["appid"])
            picked.append(g)
            if len(picked) >= max(1, min(anzahl, MAX_VOTE_ROWS)):
                break
        if len(picked) >= max(1, min(anzahl, MAX_VOTE_ROWS)):
            break

    if not picked:
        return await interaction.followup.send(
            "Noch keine Vorschläge - der Sammler war wohl noch nicht dran."
        )

    embed = discord.Embed.from_dict(embeds.suggestion(picked))
    games = [(g["appid"], embeds.cut(g["name"], 60)) for g in picked]
    await interaction.followup.send(
        embed=with_tally(embed, games, votes), view=VoteView(picked)
    )


@tree.command(name="abstimmung", description="Aktueller Stand der Abstimmung")
async def cmd_abstimmung(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        votes = await client.api.votes()
    except HubError as exc:
        return await _fail(interaction, exc)
    await interaction.followup.send(embed=discord.Embed.from_dict(embeds.vote_board(votes)))


@tree.command(name="wasgeht", description="Was können die Leute in deinem Sprachkanal zusammen spielen?")
async def cmd_wasgeht(interaction: discord.Interaction):
    voice = getattr(getattr(interaction.user, "voice", None), "channel", None)
    if voice is None:
        return await interaction.response.send_message(
            "Dafür musst du in einem Sprachkanal sitzen.", ephemeral=True
        )
    await interaction.response.defer()
    try:
        links = await client.api.links()
        known = [(m, links[str(m.id)]) for m in voice.members if not m.bot and str(m.id) in links]
        if not known:
            return await interaction.followup.send(
                "Hier ist niemand verknüpft - `/verbinden` hilft."
            )
        games = await client.api.suggest([sid for _, sid in known], limit=MAX_VOTE_ROWS)
    except HubError as exc:
        return await _fail(interaction, exc)
    if not games:
        return await interaction.followup.send(
            "Kein Multiplayer-Titel, den ihr alle habt. Das ist doch mal eine Ansage."
        )
    embed = embeds.suggestion(games, [m.display_name for m, _ in known])
    await interaction.followup.send(
        embed=discord.Embed.from_dict(embed), view=VoteView(games)
    )


@tree.command(name="spiel", description="Wer hat's, wer spielt's, wie weit sind die Achievements?")
@app_commands.describe(name="Name des Spiels")
async def cmd_spiel(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    try:
        if name.isdigit():
            detail = await client.api.game(int(name))
        else:
            hits = await client.api.library(search=name, limit=1)
            if not hits:
                return await interaction.followup.send(f"Nichts gefunden zu „{name}“.")
            detail = await client.api.game(hits[0]["appid"])
    except HubError as exc:
        return await _fail(interaction, exc)
    await interaction.followup.send(embed=discord.Embed.from_dict(embeds.game_card(detail)))


@cmd_spiel.autocomplete("name")
async def ac_spiel(interaction: discord.Interaction, current: str):
    try:
        hits = await client.api.library(search=current, limit=25, sort="owners")
    except HubError:
        return []
    return [
        app_commands.Choice(name=embeds.cut(g["name"], 90), value=str(g["appid"]))
        for g in hits[:25]
    ]


@tree.command(name="verbinden", description="Dein Discord-Konto mit deinem Steam-Spieler verknüpfen")
@app_commands.describe(spieler="Dein Name aus dem Hub")
async def cmd_verbinden(interaction: discord.Interaction, spieler: str):
    await interaction.response.defer(ephemeral=True)
    try:
        res = await client.api.link(interaction.user.id, spieler, str(interaction.user))
    except HubError as exc:
        return await _fail(interaction, exc)
    await interaction.followup.send(
        f"Verknüpft: **{res['name']}**. Deine Stimmen zählen ab sofort.", ephemeral=True
    )


@cmd_verbinden.autocomplete("spieler")
async def ac_spieler(interaction: discord.Interaction, current: str):
    try:
        players = await client.api.players()
    except HubError:
        return []
    low = current.lower()
    return [
        app_commands.Choice(name=p["name"], value=p["name"])
        for p in players
        if low in p["name"].lower()
    ][:25]


BOARDS = {
    "playtime": ("Spielzeit gesamt", embeds.hours),
    "last_14d": ("Spielzeit (14 Tage)", embeds.hours),
    "games": ("Anzahl Spiele", lambda v: f"{v} Spiele"),
    "backlog": ("Pile of Shame", lambda v: f"{v} nie gestartet"),
    "achievements": ("Errungenschaften", lambda v: f"{v}"),
    "perfect_games": ("100-%-Spiele", lambda v: f"{v}"),
    "library_value": ("Wert der Bibliothek", embeds.euro),
}


@tree.command(name="rangliste", description="Die Bestenlisten der Runde")
@app_commands.describe(kategorie="Welche Liste?")
@app_commands.choices(
    kategorie=[app_commands.Choice(name=t, value=k) for k, (t, _) in BOARDS.items()]
)
async def cmd_rangliste(interaction: discord.Interaction, kategorie: str = "playtime"):
    await interaction.response.defer()
    try:
        boards = await client.api.leaderboards()
    except HubError as exc:
        return await _fail(interaction, exc)
    title, fmt = BOARDS.get(kategorie, BOARDS["playtime"])
    rows = boards.get(kategorie) or []
    await interaction.followup.send(
        embed=discord.Embed.from_dict(embeds.leaderboard(rows, f"🏅 {title}", fmt))
    )


@tree.command(name="selten", description="Die seltensten Errungenschaften der Runde")
async def cmd_selten(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        rows = await client.api.rare(limit=5, max_pct=settings.notify_rare_pct)
    except HubError as exc:
        return await _fail(interaction, exc)
    if not rows:
        return await interaction.followup.send("Noch nichts Seltenes dabei.")
    await interaction.followup.send(
        embeds=[
            discord.Embed.from_dict(embeds.rare_achievement({**r, "ach_icon": r.get("icon")}))
            for r in rows
        ]
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if not settings.discord_token:
        raise SystemExit("DISCORD_TOKEN fehlt - siehe .env.example")
    if not settings.admin_token:
        raise SystemExit("ADMIN_TOKEN fehlt - der Bot braucht ihn zum Schreiben")
    try:
        client.run(settings.discord_token, log_handler=None)
    except KeyboardInterrupt:
        asyncio.run(client.close())


if __name__ == "__main__":
    main()
