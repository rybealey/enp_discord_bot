from datetime import datetime, time, timezone

from discord.ext import commands, tasks

from config import logger
from database import get_meta, set_meta


def _is_uk_dst(dt: datetime) -> bool:
    """Return True if the given UTC datetime falls within UK BST (last Sunday
    of March 01:00 UTC to last Sunday of October 01:00 UTC)."""
    year = dt.year

    # Last Sunday of March
    mar_last = 31
    while datetime(year, 3, mar_last).weekday() != 6:
        mar_last -= 1
    dst_start = datetime(year, 3, mar_last, 1, tzinfo=timezone.utc)

    # Last Sunday of October
    oct_last = 31
    while datetime(year, 10, oct_last).weekday() != 6:
        oct_last -= 1
    dst_end = datetime(year, 10, oct_last, 1, tzinfo=timezone.utc)

    return dst_start <= dt < dst_end


class DSTCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.dst_check_task.start()

    async def cog_unload(self):
        self.dst_check_task.cancel()

    @tasks.loop(time=time(hour=3, minute=0, tzinfo=timezone.utc))
    async def dst_check_task(self):
        """Automatically enable/disable DST based on UK BST rules."""
        now = datetime.now(timezone.utc)
        should_be = "1" if _is_uk_dst(now) else "0"
        current = get_meta("dst_enabled") or "0"
        if should_be != current:
            set_meta("dst_enabled", should_be)
            state = "enabled" if should_be == "1" else "disabled"
            logger.info("DST auto-check: %s (was %s)", state, "enabled" if current == "1" else "disabled")

    @dst_check_task.before_loop
    async def before_dst_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(DSTCog(bot))
