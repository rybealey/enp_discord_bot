import discord
from datetime import datetime, timezone

from discord.ext import commands, tasks

from config import __version__, POLL_INTERVAL, LIVEFEED_CHANNEL_ID, logger
from helpers import ACTION_ICONS, ACTION_COLORS, format_event_line
from database import insert_events_batch
from api_poller import fetch_livefeed


class LivefeedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.poll_livefeed_task.start()

    async def cog_unload(self):
        self.poll_livefeed_task.cancel()

    @tasks.loop(seconds=POLL_INTERVAL)
    async def poll_livefeed_task(self):
        """Fetch the livefeed and store new police events in the database."""
        if not LIVEFEED_CHANNEL_ID:
            return

        events = await fetch_livefeed(self.bot.http_session)
        if events:
            new_events = insert_events_batch(events)
            if new_events:
                logger.info("Stored %d new police events", len(new_events))
                channel = self.bot.get_channel(LIVEFEED_CHANNEL_ID)
                if not channel:
                    logger.warning("Livefeed channel %d not found — are the ID and bot permissions correct?", LIVEFEED_CHANNEL_ID)
                    return
                for event in new_events:
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

    @poll_livefeed_task.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(LivefeedCog(bot))
