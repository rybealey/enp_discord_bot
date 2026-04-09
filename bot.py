import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from config import (
    __version__, DISCORD_TOKEN, LIVEFEED_CHANNEL_ID, ALLOWED_ROLES,
    POLL_INTERVAL, logger,
)
from database import init_db, get_meta, set_meta

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

EXTENSIONS = [
    "cogs.activity",
    "cogs.shifts",
    "cogs.graphs",
    "cogs.utility",
    "cogs.livefeed",
    "cogs.dst",
]


async def setup_hook():
    bot.http_session = aiohttp.ClientSession()
    init_db()
    for ext in EXTENSIONS:
        await bot.load_extension(ext)

bot.setup_hook = setup_hook


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    logger.info("Logged in as %s (ID: %s)", bot.user.name, bot.user.id)
    logger.info("Allowed roles: %s", ", ".join(ALLOWED_ROLES))
    logger.info("Poll interval: %ds", POLL_INTERVAL)
    if LIVEFEED_CHANNEL_ID:
        logger.info("Livefeed channel: %d", LIVEFEED_CHANNEL_ID)
    else:
        logger.warning("LIVEFEED_CHANNEL_ID not set — livefeed posting is disabled")

    await bot.tree.sync()
    logger.info("Slash commands synced")

    # Announce new deployment if commit SHA changed
    commit_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA")
    commit_msg = os.getenv("RAILWAY_GIT_COMMIT_MESSAGE", "No commit message provided.")
    if commit_sha and LIVEFEED_CHANNEL_ID:
        last_sha = get_meta("last_announced_commit")
        if commit_sha != last_sha:
            channel = bot.get_channel(LIVEFEED_CHANNEL_ID)
            if channel:
                short_sha = commit_sha[:7]
                embed = discord.Embed(
                    title=f"\U0001f680 Software Update \u2013 v{__version__}",
                    description=(
                        f"A new update has been deployed.\n\n"
                        f"**Commit:** `{short_sha}`\n"
                        f"**Message:** {commit_msg}"
                    ),
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text=f"ENP Bot v{__version__}")
                await channel.send(embed=embed)
                logger.info("Announced deployment %s to update channel", short_sha)
            else:
                logger.warning("Update channel %d not found", LIVEFEED_CHANNEL_ID)
            set_meta("last_announced_commit", commit_sha)


# ---------------------------------------------------------------------------
# Global error handler for slash commands
# ---------------------------------------------------------------------------
@bot.tree.error
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
