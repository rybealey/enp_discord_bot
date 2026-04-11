import discord
from datetime import datetime, timezone

from discord import app_commands
from discord.ext import commands

from config import __version__, POLL_INTERVAL
from database import get_current_timezone, get_event_count, get_meta


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show a guide to all available bot commands")
    async def cmd_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="\U0001f4d6 ENP Bot \u2014 Command Guide",
            description="All data is scoped to the **current week** (Monday 00:00 GMT). Responses are ephemeral (only visible to you) unless noted.",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="\U0001f6a8 Police Activity",
            value=(
                "**/recent** `[count]` \u2014 Latest police events\n"
                "**/arrests** `[count]` \u2014 Recent arrests\n"
                "**/charges** `[count]` \u2014 Recent charges\n"
                "**/pardons** `[count]` \u2014 Recent pardons\n"
                "**/releases** `[count]` \u2014 Recent prison releases\n"
                "**/officer** `<name>` \u2014 Actions by a specific officer\n"
                "**/suspect** `<name>` \u2014 Actions against a specific player"
            ),
            inline=False,
        )

        embed.add_field(
            name="\U0001f4cb Shifts & Leaderboard",
            value=(
                "**/shifts** `[date]` \u2014 Weekly shift overview (live or historical)\n"
                "**/sum** `<scope>` \u2014 Total sum of logged shifts (Weekly or Total)\n"
                "**/leaderboard** \u2014 Every current ENP officer ranked by weekly arrests *(visible to all)*\n"
                "**/graph** `<action>` \u2014 Bar chart of weekly activity *(visible to all)*"
            ),
            inline=False,
        )

        embed.add_field(
            name="\u2699\ufe0f Utility",
            value=(
                "**/about** \u2014 Bot info and configuration\n"
                "**/tz** \u2014 Show the current operating timezone\n"
                "**/help** \u2014 This message"
            ),
            inline=False,
        )

        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="about", description="Show bot info and configuration")
    async def cmd_about(self, interaction: discord.Interaction):
        total = get_event_count()
        embed = discord.Embed(
            title="\U0001f46e ENP Bot",
            description="Developed and updated by Peggy.",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Total Events", value=str(total), inline=True)
        embed.add_field(name="Poll Interval", value=f"{POLL_INTERVAL}s", inline=True)
        embed.add_field(name="Tracking", value="Arrests, Charges, Pardons, Releases", inline=True)
        dst = get_meta("dst_enabled") or "0"
        embed.add_field(name="DST", value="Enabled (+1 GMT)" if dst == "1" else "Disabled (GMT)", inline=True)
        embed.add_field(name="Version", value=f"v{__version__}", inline=True)
        embed.add_field(
            name="Developer",
            value="[Message Developer](https://discord.com/users/608531997849026609)",
            inline=True,
        )
        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="tz", description="Show the bot's current operating timezone")
    async def cmd_tz(self, interaction: discord.Interaction):
        tz_row = get_current_timezone()
        dst = get_meta("dst_enabled") or "0"
        dst_value = "Enabled (+1 GMT)" if dst == "1" else "Disabled (GMT)"

        embed = discord.Embed(
            title="\U0001f553 Current Operating Timezone",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )

        if tz_row is None:
            embed.description = "No active timezone window."
        else:
            window = f"{tz_row['start_hour']:02d}:00 \u2013 {tz_row['end_hour']:02d}:00 GMT"
            embed.add_field(name="Timezone", value=tz_row["label"], inline=True)
            embed.add_field(name="GMT Window", value=window, inline=True)
            embed.add_field(name="DST", value=dst_value, inline=True)

        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCog(bot))
