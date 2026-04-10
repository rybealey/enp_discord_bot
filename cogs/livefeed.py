import discord
from datetime import datetime, timezone

from discord.ext import commands, tasks

from config import __version__, POLL_INTERVAL, LIVEFEED_CHANNEL_ID, logger
from helpers import ACTION_ICONS, ACTION_COLORS, format_event_line
from database import insert_events_batch, insert_roster_events_batch, is_in_enp_roster
from api_poller import fetch_livefeed


ENP_CORP_NAME = "Egyptian National Police"

# (icon, title, color) for each managerial event type
MANAGERIAL_EVENT_STYLE = {
    "hired":     ("\U0001f7e2", "Hired into ENP",       discord.Color.green()),       # 🟢
    "sent_home": ("\U0001f3e0", "Sent Home",            discord.Color.orange()),       # 🏠
    "fired":     ("\U0001f6ab", "Fired from ENP",       discord.Color.red()),          # 🚫
    "quit":      ("\U0001f44b", "Quit ENP",             discord.Color.dark_grey()),    # 👋
}


def _filter_enp_managerial(event: dict) -> bool:
    """Return True if the managerial event should be tracked as an ENP event.

    - hired/fired/quit: filter by exact corp name match.
    - sent_home: livefeed message has no corp name; check whether the manager
      (actor) is currently in the ENP roster.
    """
    et = event["event_type"]
    if et in ("hired", "fired", "quit"):
        return event.get("corp") == ENP_CORP_NAME
    if et == "sent_home":
        actor = event.get("actor")
        return bool(actor) and is_in_enp_roster(actor)
    return False


def _build_managerial_embed(event: dict) -> discord.Embed:
    icon, title, color = MANAGERIAL_EVENT_STYLE.get(
        event["event_type"],
        ("\U0001f3db\ufe0f", event["event_type"].title(), discord.Color.blurple()),
    )

    et = event["event_type"]
    member = event["member"]
    actor = event.get("actor")

    if et == "hired":
        description = f"**{actor}** hired **{member}** into ENP."
    elif et == "sent_home":
        mins = event.get("details") or "?"
        description = f"**{actor}** sent **{member}** home for **{mins}** minute{'s' if mins != '1' else ''}."
    elif et == "fired":
        description = f"**{actor}** fired **{member}** from ENP."
    elif et == "quit":
        description = f"**{member}** quit ENP."
    else:
        description = event.get("raw_text", member)

    embed = discord.Embed(
        title=f"{icon} {title}",
        description=description,
        color=color,
        timestamp=datetime.fromtimestamp(event["timestamp"], tz=timezone.utc),
    )
    embed.set_footer(text=f"ENP Bot v{__version__}")
    return embed


class LivefeedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.poll_livefeed_task.start()

    async def cog_unload(self):
        self.poll_livefeed_task.cancel()

    @tasks.loop(seconds=POLL_INTERVAL)
    async def poll_livefeed_task(self):
        """Fetch the livefeed and store new police + managerial events."""
        if not LIVEFEED_CHANNEL_ID:
            return

        result = await fetch_livefeed(self.bot.http_session)
        police_events = result.get("police", [])
        managerial_events = result.get("managerial", [])

        channel = None  # lazily fetched on first send

        # ----- Police events -----
        if police_events:
            new_police = insert_events_batch(police_events)
            if new_police:
                logger.info("Stored %d new police events", len(new_police))
                channel = channel or self.bot.get_channel(LIVEFEED_CHANNEL_ID)
                if not channel:
                    logger.warning("Livefeed channel %d not found — check the ID and bot permissions", LIVEFEED_CHANNEL_ID)
                    return
                for event in new_police:
                    try:
                        default_icon = "\U0001f46e"
                        embed = discord.Embed(
                            title=f"{ACTION_ICONS.get(event['action'], default_icon)} {event['action'].title()}",
                            description=format_event_line(event, include_icon=False),
                            color=ACTION_COLORS.get(event["action"], discord.Color.blurple()),
                            timestamp=datetime.now(timezone.utc),
                        )
                        embed.set_footer(text=f"ENP Bot v{__version__}")
                        await channel.send(embed=embed)
                    except Exception:
                        logger.exception("Failed to send livefeed embed for event %s", event["id"])

        # ----- Managerial events (ENP-only) -----
        if managerial_events:
            enp_events = [e for e in managerial_events if _filter_enp_managerial(e)]
            if enp_events:
                new_managerial = insert_roster_events_batch(enp_events)
                if new_managerial:
                    logger.info("Stored %d new managerial events", len(new_managerial))
                    channel = channel or self.bot.get_channel(LIVEFEED_CHANNEL_ID)
                    if not channel:
                        logger.warning("Livefeed channel %d not found — check the ID and bot permissions", LIVEFEED_CHANNEL_ID)
                        return
                    for event in new_managerial:
                        try:
                            await channel.send(embed=_build_managerial_embed(event))
                        except Exception:
                            logger.exception("Failed to send managerial embed for event %s", event["id"])

    @poll_livefeed_task.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(LivefeedCog(bot))
