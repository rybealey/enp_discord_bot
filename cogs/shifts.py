import aiohttp
import discord
from collections import OrderedDict
from datetime import datetime, time, timezone

from discord import app_commands
from discord.ext import commands, tasks

from config import (
    __version__, CORP_API_URL, SHIFTS_CHANNEL_ID,
    RANK_ORDER, RANK_EMOJIS, WEEKLY_SHIFT_REQ, logger,
)
from helpers import strip_rank_tier, render_shifts_graph
from database import (
    insert_shift_snapshot,
    get_shift_snapshot,
    get_available_snapshot_dates,
    get_weekly_arrest_leaderboard,
    get_weekly_shift_sum,
    get_total_shift_sum,
    get_weekly_shifts_by_timezone,
    update_shift_cache_and_log,
    reset_shift_cache,
    get_meta,
    set_meta,
)


class ShiftsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.poll_shifts_task.start()
        self.weekly_shift_snapshot_task.start()

    async def cog_unload(self):
        self.poll_shifts_task.cancel()
        self.weekly_shift_snapshot_task.cancel()

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def poll_shifts_task(self):
        """Fetch shift data from the API and log new individual shifts."""
        now = datetime.now(timezone.utc)
        last_reset = get_meta("shift_cache_reset_week")
        iso_week = now.strftime("%G-W%V")
        if last_reset != iso_week:
            reset_shift_cache()
            set_meta("shift_cache_reset_week", iso_week)
            logger.info("Shift cache reset for new week %s", iso_week)

        headers = {"User-Agent": "ENPBot/1.0"}
        try:
            async with self.bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning("Shift poll: API returned status %d", resp.status)
                    return
                data = await resp.json()
        except Exception:
            logger.exception("Shift poll: failed to fetch corp data")
            return

        members = []
        for rank in data.get("ranks", []):
            role_name = rank["role_name"]
            base_rank = strip_rank_tier(role_name)
            for m in rank.get("members", []):
                members.append({
                    "username": m["username"],
                    "rank": base_rank,
                    "weekly_shifts": m["weekly_shifts"],
                    "total_shifts": m["total_shifts"],
                })

        if members:
            new_count = update_shift_cache_and_log(members)
            if new_count > 0:
                logger.info("Shift poll: logged %d new shift(s)", new_count)

    @poll_shifts_task.before_loop
    async def before_poll_shifts(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[time(hour=23, minute=55, tzinfo=timezone.utc),
                       time(hour=0, minute=5, tzinfo=timezone.utc)])
    async def weekly_shift_snapshot_task(self):
        now = datetime.now(timezone.utc)
        if now.weekday() == 6 and now.hour == 23:
            pass  # Sunday 23:55
        elif now.weekday() == 0 and now.hour == 0:
            pass  # Monday 00:05
        else:
            return

        headers = {"User-Agent": "ENPBot/1.0"}
        try:
            async with self.bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.error("Shift snapshot: API returned status %d", resp.status)
                    return
                data = await resp.json()
        except Exception:
            logger.exception("Shift snapshot: failed to fetch corp data")
            return

        week_ending = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        members = []
        for rank in data.get("ranks", []):
            role_name = rank["role_name"]
            base_rank = strip_rank_tier(role_name)
            for m in rank.get("members", []):
                members.append({
                    "username": m["username"],
                    "rank": base_rank,
                    "weekly_shifts": m["weekly_shifts"],
                    "total_shifts": m["total_shifts"],
                })

        if members:
            count = insert_shift_snapshot(members, week_ending)
            logger.info("Shift snapshot: logged %d members for week ending %s", count, week_ending)

            if SHIFTS_CHANNEL_ID:
                shift_data = get_weekly_shifts_by_timezone(limit=15)
                if shift_data:
                    channel = self.bot.get_channel(SHIFTS_CHANNEL_ID)
                    if channel:
                        try:
                            buf = render_shifts_graph(shift_data)
                            file = discord.File(buf, filename="graph.png")
                            embed = discord.Embed(
                                title="\U0001f4ca Weekly Shifts Summary",
                                color=discord.Color.blurple(),
                                timestamp=datetime.now(timezone.utc),
                            )
                            embed.set_image(url="attachment://graph.png")
                            embed.set_footer(text=f"ENP Bot v{__version__}")
                            await channel.send(embed=embed, file=file)
                            logger.info("Shift snapshot: posted weekly shifts graph")
                        except Exception:
                            logger.exception("Shift snapshot: failed to post shifts graph")
                    else:
                        logger.warning("Shift snapshot: shifts channel %d not found", SHIFTS_CHANNEL_ID)
        else:
            logger.warning("Shift snapshot: no members found in API response")

    @weekly_shift_snapshot_task.before_loop
    async def before_shift_snapshot(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @app_commands.command(name="leaderboard", description="Top officers by arrest count for the current week")
    @app_commands.describe(count="Number of officers to show (default: 10, max: 25)")
    async def cmd_leaderboard(self, interaction: discord.Interaction, count: int = 10):
        count = min(count, 25)
        await interaction.response.defer()

        all_members: set[str] = set()
        headers = {"User-Agent": "ENPBot/1.0"}
        try:
            async with self.bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for rank in data.get("ranks", []):
                        for m in rank.get("members", []):
                            all_members.add(m["username"])
        except Exception:
            logger.warning("Leaderboard: failed to fetch corp members, showing DB-only results")

        rows = get_weekly_arrest_leaderboard(limit=0)
        arrest_counts = {row["officer"]: row["arrest_count"] for row in rows}

        for member in all_members:
            if member not in arrest_counts:
                arrest_counts[member] = 0

        sorted_officers = sorted(arrest_counts.items(), key=lambda x: (-x[1], x[0]))[:count]

        if not sorted_officers:
            await interaction.followup.send("No officers found.", ephemeral=True)
            return

        lines = []
        for rank, (officer, arrests) in enumerate(sorted_officers, start=1):
            medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}.get(rank, f"`{rank}.`")
            lines.append(f"{medal} **{officer}** — {arrests} arrest{'s' if arrests != 1 else ''}")

        embed = discord.Embed(
            title="\U0001f3c6 Weekly Arrest Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="shifts", description="Show weekly and total shifts for all members")
    @app_commands.describe(date="Pull from stored logs (YYYY-MM-DD). Leave blank for live data.")
    async def cmd_shifts(self, interaction: discord.Interaction, date: str | None = None):
        await interaction.response.defer(ephemeral=True)

        if date is not None:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                await interaction.followup.send(
                    "Invalid date format. Use **YYYY-MM-DD** (e.g. `2026-03-29`).", ephemeral=True
                )
                return

            rows = get_shift_snapshot(date)
            if not rows:
                available = get_available_snapshot_dates()
                if available:
                    date_list = ", ".join(f"`{d}`" for d in available[:10])
                    await interaction.followup.send(
                        f"No shift data found for `{date}`.\n\nAvailable weeks: {date_list}",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        f"No shift data found for `{date}`. No snapshots have been recorded yet.",
                        ephemeral=True,
                    )
                return

            members = [
                {
                    "username": r["username"],
                    "weekly_shifts": r["weekly_shifts"],
                    "total_shifts": r["total_shifts"],
                    "base_rank": r["rank"],
                }
                for r in rows
            ]
            title_suffix = f" \u2014 Week Ending {date}"
        else:
            headers = {"User-Agent": "ENPBot/1.0"}
            try:
                async with self.bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Failed to fetch corp data from the API.", ephemeral=True)
                        return
                    data = await resp.json()
            except Exception:
                await interaction.followup.send("Failed to fetch corp data from the API.", ephemeral=True)
                return

            members = []
            for rank in data.get("ranks", []):
                role_name = rank["role_name"]
                base_rank = strip_rank_tier(role_name)
                for m in rank.get("members", []):
                    members.append({
                        "username": m["username"],
                        "weekly_shifts": m["weekly_shifts"],
                        "total_shifts": m["total_shifts"],
                        "base_rank": base_rank,
                    })
            title_suffix = ""

        if not members:
            await interaction.followup.send("No members found.", ephemeral=True)
            return

        rank_priority = {r: i for i, r in enumerate(RANK_ORDER)}
        members.sort(key=lambda m: (rank_priority.get(m["base_rank"], 999), -m["weekly_shifts"]))

        grouped = OrderedDict()
        for m in members:
            grouped.setdefault(m["base_rank"], []).append(m)

        below_req = sum(1 for m in members if m["weekly_shifts"] < WEEKLY_SHIFT_REQ)

        embed = discord.Embed(
            title=f"\U0001f4cb Shift Overview{title_suffix}",
            description=(
                f"**{len(members)}** members across **{len(grouped)}** ranks\n"
                f"\u26a0\ufe0f **{below_req}** below weekly requirement ({WEEKLY_SHIFT_REQ} shifts)"
                if below_req else
                f"**{len(members)}** members across **{len(grouped)}** ranks\n"
                f"\u2705 All members meeting weekly requirement ({WEEKLY_SHIFT_REQ} shifts)"
            ),
            color=discord.Color.orange() if below_req else discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )

        for rank_name, rank_members in grouped.items():
            emoji = RANK_EMOJIS.get(rank_name, "\U0001f46e")

            lines = []
            for m in rank_members:
                weekly = m["weekly_shifts"]
                total = m["total_shifts"]
                status = "\u2705" if weekly >= WEEKLY_SHIFT_REQ else "\U0001f534"
                lines.append(f"{status} **{m['username']}**\n\u2003\u2003`Weekly` {weekly}\u2003\u2003`Total` {total}")

            embed.add_field(
                name=f"{emoji} {rank_name}",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.followup.send(embed=embed)

    @cmd_shifts.autocomplete("date")
    async def shifts_date_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        dates = get_available_snapshot_dates()
        return [
            app_commands.Choice(name=f"Week ending {d}", value=d)
            for d in dates
            if current.lower() in d
        ][:25]

    @app_commands.command(name="sum", description="Total sum of logged shift activity")
    @app_commands.describe(scope="Count weekly shifts or all-time total shifts")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Weekly", value="weekly"),
        app_commands.Choice(name="Total", value="total"),
    ])
    async def cmd_sum(self, interaction: discord.Interaction, scope: app_commands.Choice[str]):
        if scope.value == "weekly":
            count = get_weekly_shift_sum()
            await interaction.response.send_message(
                f"\U0001f4cb **Weekly Shift Total:** {count} shift{'s' if count != 1 else ''} logged this week.",
                ephemeral=True,
            )
        else:
            count = get_total_shift_sum()
            await interaction.response.send_message(
                f"\U0001f4cb **All-Time Shift Total:** {count} shift{'s' if count != 1 else ''} logged.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(ShiftsCog(bot))
