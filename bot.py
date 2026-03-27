__version__ = "0.1.0"

import os
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from database import (
    init_db,
    insert_events_batch,
    get_recent_events,
    get_events_by_officer,
    get_events_by_perpetrator,
    get_events_by_action,
    get_event_count,
)
from api_poller import fetch_livefeed

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_ROLES = [r.strip() for r in os.getenv("ALLOWED_ROLES", "Admin").split(",")]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("enp_bot")

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------------------------------------------------------------------
# Role check
# ---------------------------------------------------------------------------
def has_allowed_role():
    """Command check: user must have at least one of the allowed roles."""
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        user_roles = [role.name for role in ctx.author.roles]
        return any(role in user_roles for role in ALLOWED_ROLES)
    return commands.check(predicate)


# ---------------------------------------------------------------------------
# Background polling task
# ---------------------------------------------------------------------------
@tasks.loop(seconds=POLL_INTERVAL)
async def poll_livefeed():
    """Fetch the livefeed and store new police events in the database."""
    events = await fetch_livefeed(bot.http_session)
    if events:
        new_count = insert_events_batch(events)
        if new_count > 0:
            logger.info("Stored %d new police events", new_count)


@poll_livefeed.before_loop
async def before_poll():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    logger.info("Logged in as %s (ID: %s)", bot.user.name, bot.user.id)
    logger.info("Allowed roles: %s", ", ".join(ALLOWED_ROLES))
    logger.info("Poll interval: %ds", POLL_INTERVAL)

    bot.http_session = aiohttp.ClientSession()
    init_db()

    if not poll_livefeed.is_running():
        poll_livefeed.start()


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to use this command.")
    else:
        logger.error("Command error: %s", error)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def format_event(row) -> str:
    """Format a database row into a readable Discord message line."""
    ts = datetime.fromtimestamp(row["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    details = f" ({row['details']})" if row["details"] else ""
    return f"`{ts}` | **{row['officer']}** {row['action']} **{row['perpetrator']}**{details}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@bot.command(name="recent")
@has_allowed_role()
async def cmd_recent(ctx: commands.Context, count: int = 10):
    """Show the most recent police events.

    Usage: !recent [count]
    """
    count = min(count, 25)
    events = get_recent_events(count)
    if not events:
        await ctx.send("No police events recorded yet.")
        return

    lines = [format_event(e) for e in events]
    header = f"**Last {len(events)} Police Events**\n"
    await ctx.send(header + "\n".join(lines))


@bot.command(name="officer")
@has_allowed_role()
async def cmd_officer(ctx: commands.Context, *, name: str):
    """Look up recent actions by a specific officer.

    Usage: !officer <officer_name>
    """
    events = get_events_by_officer(name, limit=15)
    if not events:
        await ctx.send(f"No events found for officer **{name}**.")
        return

    lines = [format_event(e) for e in events]
    header = f"**Actions by officer: {name}**\n"
    await ctx.send(header + "\n".join(lines))


@bot.command(name="suspect")
@has_allowed_role()
async def cmd_suspect(ctx: commands.Context, *, name: str):
    """Look up recent police actions against a specific player.

    Usage: !suspect <player_name>
    """
    events = get_events_by_perpetrator(name, limit=15)
    if not events:
        await ctx.send(f"No events found for **{name}**.")
        return

    lines = [format_event(e) for e in events]
    header = f"**Police actions against: {name}**\n"
    await ctx.send(header + "\n".join(lines))


@bot.command(name="arrests")
@has_allowed_role()
async def cmd_arrests(ctx: commands.Context, count: int = 10):
    """Show recent arrests.

    Usage: !arrests [count]
    """
    count = min(count, 25)
    events = get_events_by_action("arrested", limit=count)
    if not events:
        await ctx.send("No arrests recorded yet.")
        return

    lines = [format_event(e) for e in events]
    header = f"**Recent Arrests**\n"
    await ctx.send(header + "\n".join(lines))


@bot.command(name="charges")
@has_allowed_role()
async def cmd_charges(ctx: commands.Context, count: int = 10):
    """Show recent charges.

    Usage: !charges [count]
    """
    count = min(count, 25)
    events = get_events_by_action("charged", limit=count)
    if not events:
        await ctx.send("No charges recorded yet.")
        return

    lines = [format_event(e) for e in events]
    header = f"**Recent Charges**\n"
    await ctx.send(header + "\n".join(lines))



@bot.command(name="pardons")
@has_allowed_role()
async def cmd_pardons(ctx: commands.Context, count: int = 10):
    """Show recent pardons.

    Usage: !pardons [count]
    """
    count = min(count, 25)
    events = get_events_by_action("pardoned", limit=count)
    if not events:
        await ctx.send("No pardons recorded yet.")
        return

    lines = [format_event(e) for e in events]
    header = f"**Recent Pardons**\n"
    await ctx.send(header + "\n".join(lines))


@bot.command(name="stats")
@has_allowed_role()
async def cmd_stats(ctx: commands.Context):
    """Show basic stats about recorded police activity.

    Usage: !stats
    """
    total = get_event_count()
    await ctx.send(
        f"**ENP Bot Stats**\n"
        f"Total police events recorded: **{total}**\n"
        f"Polling every **{POLL_INTERVAL}s**\n"
        f"Tracking: arrests, charges, pardons"
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
async def cleanup():
    if hasattr(bot, "http_session") and bot.http_session:
        await bot.http_session.close()


def main():
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not set. Copy .env.example to .env and add your token.")
        return

    try:
        bot.run(DISCORD_TOKEN)
    finally:
        import asyncio
        asyncio.get_event_loop().run_until_complete(cleanup())


if __name__ == "__main__":
    main()
