import discord
from discord import app_commands
from discord.ext import commands

from helpers import build_event_embed
from database import (
    get_recent_events,
    get_events_by_officer,
    get_events_by_perpetrator,
    get_events_by_action,
)


class ActivityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="recent", description="Show the most recent police events")
    @app_commands.describe(count="Number of events to show (default: 10, max: 25)")
    async def cmd_recent(self, interaction: discord.Interaction, count: int = 10):
        count = min(count, 25)
        events = get_recent_events(count)
        if not events:
            await interaction.response.send_message("No police events recorded yet.", ephemeral=True)
            return
        embed = build_event_embed("Recent Police Activity", events)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="officer", description="Look up recent actions by a specific officer")
    @app_commands.describe(name="Officer name to look up")
    async def cmd_officer(self, interaction: discord.Interaction, name: str):
        events = get_events_by_officer(name, limit=15)
        if not events:
            await interaction.response.send_message(f"No events found for officer **{name}**.", ephemeral=True)
            return
        embed = build_event_embed(f"Officer Report: {name}", events)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="suspect", description="Look up recent police actions against a player")
    @app_commands.describe(name="Player name to look up")
    async def cmd_suspect(self, interaction: discord.Interaction, name: str):
        events = get_events_by_perpetrator(name, limit=15)
        if not events:
            await interaction.response.send_message(f"No events found for **{name}**.", ephemeral=True)
            return
        embed = build_event_embed(f"Suspect Report: {name}", events)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="arrests", description="Show recent arrests")
    @app_commands.describe(count="Number of arrests to show (default: 10, max: 25)")
    async def cmd_arrests(self, interaction: discord.Interaction, count: int = 10):
        count = min(count, 25)
        events = get_events_by_action("arrested", limit=count)
        if not events:
            await interaction.response.send_message("No arrests recorded yet.", ephemeral=True)
            return
        embed = build_event_embed("Recent Arrests", events, color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="charges", description="Show recent charges")
    @app_commands.describe(count="Number of charges to show (default: 10, max: 25)")
    async def cmd_charges(self, interaction: discord.Interaction, count: int = 10):
        count = min(count, 25)
        events = get_events_by_action("charged", limit=count)
        if not events:
            await interaction.response.send_message("No charges recorded yet.", ephemeral=True)
            return
        embed = build_event_embed("Recent Charges", events, color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pardons", description="Show recent pardons")
    @app_commands.describe(count="Number of pardons to show (default: 10, max: 25)")
    async def cmd_pardons(self, interaction: discord.Interaction, count: int = 10):
        count = min(count, 25)
        events = get_events_by_action("pardoned", limit=count)
        if not events:
            await interaction.response.send_message("No pardons recorded yet.", ephemeral=True)
            return
        embed = build_event_embed("Recent Pardons", events, color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="releases", description="Show recent prison releases")
    @app_commands.describe(count="Number of releases to show (default: 10, max: 25)")
    async def cmd_releases(self, interaction: discord.Interaction, count: int = 10):
        count = min(count, 25)
        events = get_events_by_action("released", limit=count)
        if not events:
            await interaction.response.send_message("No releases recorded yet.", ephemeral=True)
            return
        embed = build_event_embed("Recent Releases", events, color=discord.Color.teal())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityCog(bot))
