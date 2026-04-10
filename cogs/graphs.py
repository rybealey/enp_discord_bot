import io

import discord
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timezone

from discord import app_commands
from discord.ext import commands

from config import __version__
from helpers import GRAPH_COLORS, GRAPH_ACTION_CHOICES, render_shifts_graph
from database import get_weekly_action_by_officer, get_weekly_shifts_by_timezone


class GraphsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="graph", description="Bar graph of officers by action type for the current week")
    @app_commands.describe(action="Type of police action to graph")
    @app_commands.choices(action=GRAPH_ACTION_CHOICES)
    async def cmd_graph(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if action.value == "shifts":
            await self._graph_shifts(interaction)
            return

        rows = get_weekly_action_by_officer(action.value, limit=15)
        if not rows:
            await interaction.response.send_message(
                f"No {action.name.lower()} recorded this week.", ephemeral=True
            )
            return

        await interaction.response.defer()

        officers = [row["officer"] for row in reversed(rows)]
        counts = [row["action_count"] for row in reversed(rows)]
        bar_color = GRAPH_COLORS.get(action.value, "#7289da")

        fig, ax = plt.subplots(figsize=(10, max(3, len(officers) * 0.5)))
        bars = ax.barh(officers, counts, color=bar_color, edgecolor="white", linewidth=0.5)
        ax.bar_label(bars, padding=4, fontsize=11, fontweight="bold", color="white")

        ax.set_xlabel("Count", fontsize=12, color="white")
        ax.set_title(f"Weekly {action.name} by Officer", fontsize=14, fontweight="bold", color="white", pad=12)

        ax.set_facecolor("#2b2d31")
        fig.set_facecolor("#2b2d31")
        ax.tick_params(colors="white", labelsize=11)
        ax.xaxis.label.set_color("white")
        for spine in ax.spines.values():
            spine.set_color("#40444b")
        ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)

        file = discord.File(buf, filename="graph.png")
        embed = discord.Embed(
            title=f"\U0001f4ca Weekly {action.name} by Officer",
            color=discord.Color.from_str(bar_color),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_image(url="attachment://graph.png")
        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.followup.send(embed=embed, file=file)

    async def _graph_shifts(self, interaction: discord.Interaction):
        """Render a stacked horizontal bar graph of shifts broken down by timezone."""
        data = get_weekly_shifts_by_timezone(limit=15)
        if not data:
            await interaction.response.send_message("No shift data recorded this week.", ephemeral=True)
            return

        await interaction.response.defer()

        buf = render_shifts_graph(data)
        file = discord.File(buf, filename="graph.png")
        embed = discord.Embed(
            title="\U0001f4ca Weekly Shifts by Timezone",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_image(url="attachment://graph.png")
        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(GraphsCog(bot))
