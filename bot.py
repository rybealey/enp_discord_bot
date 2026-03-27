__version__ = "1.0.0"

import os
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from database import (
    init_db,
    insert_events_batch,
    get_recent_events,
    get_events_by_officer,
    get_events_by_perpetrator,
    get_events_by_action,
    get_weekly_arrest_leaderboard,
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

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# ---------------------------------------------------------------------------
# Role check
# ---------------------------------------------------------------------------
def has_allowed_role(interaction: discord.Interaction) -> bool:
    """Check that the user has at least one of the allowed roles."""
    if not interaction.guild:
        return False
    user_roles = [role.name for role in interaction.user.roles]
    return any(role in user_roles for role in ALLOWED_ROLES)


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

    await tree.sync()
    logger.info("Slash commands synced")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ACTION_COLORS = {
    "arrested": discord.Color.red(),
    "charged": discord.Color.orange(),
    "pardoned": discord.Color.green(),
}

ACTION_ICONS = {
    "arrested": "\U0001f6a8",   # 🚨
    "charged": "\U0001f4cb",    # 📋
    "pardoned": "\u2705",       # ✅
}


def format_event_line(row) -> str:
    """Format a single event as a compact line for embed descriptions."""
    icon = ACTION_ICONS.get(row["action"], "\U0001f46e")
    ts = f"<t:{row['timestamp']}:R>"
    if row["action"] == "pardoned":
        return f"{icon} **{row['officer']}** pardoned **{row['perpetrator']}** of all crimes {ts}"
    details = f" — {row['details']}" if row["details"] else ""
    return f"{icon} **{row['officer']}** {row['action']} **{row['perpetrator']}**{details} {ts}"


def build_event_embed(title: str, events: list, color: discord.Color = None) -> discord.Embed:
    """Build a Discord embed from a list of event rows."""
    if not color:
        actions = set(e["action"] for e in events)
        if len(actions) == 1:
            color = ACTION_COLORS.get(actions.pop(), discord.Color.blurple())
        else:
            color = discord.Color.blurple()

    lines = [format_event_line(e) for e in events]
    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"ENP Bot v{__version__}")
    return embed


# ---------------------------------------------------------------------------
# Slash Commands
# ---------------------------------------------------------------------------
@tree.command(name="recent", description="Show the most recent police events")
@app_commands.describe(count="Number of events to show (default: 10, max: 25)")
async def cmd_recent(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_recent_events(count)
    if not events:
        await interaction.response.send_message("No police events recorded yet.", ephemeral=True)
        return

    embed = build_event_embed(f"Recent Police Activity", events)
    await interaction.response.send_message(embed=embed)


@tree.command(name="officer", description="Look up recent actions by a specific officer")
@app_commands.describe(name="Officer name to look up")
async def cmd_officer(interaction: discord.Interaction, name: str):
    events = get_events_by_officer(name, limit=15)
    if not events:
        await interaction.response.send_message(f"No events found for officer **{name}**.", ephemeral=True)
        return

    embed = build_event_embed(f"Officer Report: {name}", events)
    await interaction.response.send_message(embed=embed)


@tree.command(name="suspect", description="Look up recent police actions against a player")
@app_commands.describe(name="Player name to look up")
async def cmd_suspect(interaction: discord.Interaction, name: str):
    events = get_events_by_perpetrator(name, limit=15)
    if not events:
        await interaction.response.send_message(f"No events found for **{name}**.", ephemeral=True)
        return

    embed = build_event_embed(f"Suspect Report: {name}", events)
    await interaction.response.send_message(embed=embed)


@tree.command(name="arrests", description="Show recent arrests")
@app_commands.describe(count="Number of arrests to show (default: 10, max: 25)")
async def cmd_arrests(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_events_by_action("arrested", limit=count)
    if not events:
        await interaction.response.send_message("No arrests recorded yet.", ephemeral=True)
        return

    embed = build_event_embed("Recent Arrests", events, color=discord.Color.red())
    await interaction.response.send_message(embed=embed)


@tree.command(name="charges", description="Show recent charges")
@app_commands.describe(count="Number of charges to show (default: 10, max: 25)")
async def cmd_charges(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_events_by_action("charged", limit=count)
    if not events:
        await interaction.response.send_message("No charges recorded yet.", ephemeral=True)
        return

    embed = build_event_embed("Recent Charges", events, color=discord.Color.orange())
    await interaction.response.send_message(embed=embed)


@tree.command(name="pardons", description="Show recent pardons")
@app_commands.describe(count="Number of pardons to show (default: 10, max: 25)")
async def cmd_pardons(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_events_by_action("pardoned", limit=count)
    if not events:
        await interaction.response.send_message("No pardons recorded yet.", ephemeral=True)
        return

    embed = build_event_embed("Recent Pardons", events, color=discord.Color.green())
    await interaction.response.send_message(embed=embed)


@tree.command(name="leaderboard", description="Top officers by arrest count for the current week")
@app_commands.describe(count="Number of officers to show (default: 10, max: 25)")
async def cmd_leaderboard(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    rows = get_weekly_arrest_leaderboard(limit=count)
    if not rows:
        await interaction.response.send_message("No arrests recorded this week.", ephemeral=True)
        return

    lines = []
    for rank, row in enumerate(rows, start=1):
        medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}.get(rank, f"`{rank}.`")
        lines.append(f"{medal} **{row['officer']}** — {row['arrest_count']} arrest{'s' if row['arrest_count'] != 1 else ''}")

    embed = discord.Embed(
        title="\U0001f3c6 Weekly Arrest Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"ENP Bot v{__version__}")
    await interaction.response.send_message(embed=embed)


@tree.command(name="stats", description="Show bot stats and configuration")
async def cmd_stats(interaction: discord.Interaction):
    total = get_event_count()
    embed = discord.Embed(
        title="\U0001f46e ENP Bot Stats",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Total Events", value=str(total), inline=True)
    embed.add_field(name="Poll Interval", value=f"{POLL_INTERVAL}s", inline=True)
    embed.add_field(name="Tracking", value="Arrests, Charges, Pardons", inline=True)
    embed.add_field(name="Version", value=f"v{__version__}", inline=True)
    embed.set_footer(text=f"ENP Bot v{__version__}")
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Global error handler for slash commands
# ---------------------------------------------------------------------------
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    else:
        logger.error("Command error: %s", error)


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
