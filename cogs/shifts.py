import aiohttp
import discord
from collections import OrderedDict
from datetime import datetime, time, timezone

from discord import app_commands
from discord.ext import commands, tasks

from config import (
    __version__, CORP_API_URL, SHIFTS_CHANNEL_ID, LIVEFEED_CHANNEL_ID,
    RANK_ORDER, RANK_EMOJIS, WEEKLY_SHIFT_REQ, logger,
)
from helpers import strip_rank_tier
from database import (
    insert_shift_snapshot,
    get_shift_snapshot,
    get_available_snapshot_dates,
    get_weekly_arrest_leaderboard,
    get_weekly_shift_sum,
    get_total_shift_sum,
    update_shift_cache_and_log,
    sync_corp_roster,
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
        # self.tz_end_reminder_task.start()  # temporarily disabled

    async def cog_unload(self):
        self.poll_shifts_task.cancel()
        self.weekly_shift_snapshot_task.cancel()
        self.tz_end_reminder_task.cancel()

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

            # Mirror the corp API roster into corp_roster. This is a state
            # cache only — hire/fire/quit/sent-home events are detected from
            # the livefeed in cogs.livefeed, not from this diff.
            sync_corp_roster(members)

    @poll_shifts_task.before_loop
    async def before_poll_shifts(self):
        await self.bot.wait_until_ready()

    # Trigger times are pinned to fixed UTC (≙ GMT). Role timezones are fixed
    # GMT year-round — no DST adjustment anywhere.
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

        if not members:
            logger.warning("Shift snapshot: no members found in API response")
            return

        count = insert_shift_snapshot(members, week_ending)
        logger.info("Shift snapshot: logged %d members for week ending %s", count, week_ending)

        if not SHIFTS_CHANNEL_ID:
            return
        channel = self.bot.get_channel(SHIFTS_CHANNEL_ID)
        if not channel:
            logger.warning("Shift snapshot: shifts channel %d not found", SHIFTS_CHANNEL_ID)
            return

        # Post the shift overview embed (same output as /shifts)
        try:
            parsed = datetime.strptime(week_ending, "%Y-%m-%d")
            label = "Week Starting" if parsed.weekday() == 0 else "Week Ending"
            overview_members = [
                {
                    "username": m["username"],
                    "weekly_shifts": m["weekly_shifts"],
                    "total_shifts": m["total_shifts"],
                    "base_rank": m["rank"],
                }
                for m in members
            ]
            overview_embed = self._build_shifts_overview_embed(
                overview_members, title_suffix=f" \u2014 {label} {week_ending}"
            )
            await channel.send(embed=overview_embed)
            logger.info("Shift snapshot: posted weekly shifts overview")
        except Exception:
            logger.exception("Shift snapshot: failed to post shifts overview")

    @weekly_shift_snapshot_task.before_loop
    async def before_shift_snapshot(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=[
        time(hour=7,  minute=50, tzinfo=timezone.utc),   # NA ends 08:00 UTC
        time(hour=15, minute=50, tzinfo=timezone.utc),   # OC ends 16:00 UTC
        time(hour=23, minute=50, tzinfo=timezone.utc),   # EU ends 00:00 UTC
    ])
    async def tz_end_reminder_task(self):
        tz_by_hour = {7: "NA", 15: "OC", 23: "EU"}
        tz_name = tz_by_hour.get(datetime.now(timezone.utc).hour)
        if tz_name is None:
            return

        if not LIVEFEED_CHANNEL_ID:
            return
        channel = self.bot.get_channel(LIVEFEED_CHANNEL_ID)
        if channel is None:
            logger.warning("TZ reminder: livefeed channel %s not found", LIVEFEED_CHANNEL_ID)
            return

        role = discord.utils.get(channel.guild.roles, name=tz_name)
        mention = role.mention if role else f"@{tz_name}"

        try:
            await channel.send(
                f"{mention} \u2014 the **{tz_name}** timezone ends in 10 minutes. "
                f"Please reload the client to ensure your completed shifts are "
                f"logged in the correct timezone.",
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            logger.info("TZ reminder: posted 10-minute warning for %s", tz_name)
        except Exception:
            logger.exception("TZ reminder: failed to post warning for %s", tz_name)

    @tz_end_reminder_task.before_loop
    async def before_tz_end_reminder(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_shifts_overview_embed(self, members: list[dict], title_suffix: str = "") -> discord.Embed:
        rank_priority = {r: i for i, r in enumerate(RANK_ORDER)}
        members.sort(key=lambda m: (rank_priority.get(m["base_rank"], 999), -m["weekly_shifts"]))

        grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
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
        return embed

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @app_commands.command(name="leaderboard", description="All current ENP officers ranked by weekly arrests")
    async def cmd_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Pull the full ENP roster from the corp API so non-arresting cops still appear
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

        sorted_officers = sorted(arrest_counts.items(), key=lambda x: (-x[1], x[0]))

        if not sorted_officers:
            await interaction.followup.send("No officers found.", ephemeral=True)
            return

        lines = []
        for rank, (officer, arrests) in enumerate(sorted_officers, start=1):
            medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}.get(rank, f"`{rank}.`")
            lines.append(f"{medal} **{officer}** — {arrests} arrest{'s' if arrests != 1 else ''}")

        # Discord embed descriptions cap at 4096 chars; chunk into fields if needed
        description = "\n".join(lines)
        embed = discord.Embed(
            title="\U0001f3c6 Weekly Arrest Leaderboard",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        if len(description) <= 4096:
            embed.description = description
        else:
            # Split into ~1000-char fields to stay under embed field limits
            chunk: list[str] = []
            chunk_len = 0
            field_idx = 1
            for line in lines:
                if chunk_len + len(line) + 1 > 1000:
                    embed.add_field(name=f"\u200b" if field_idx > 1 else f"{len(sorted_officers)} officers", value="\n".join(chunk), inline=False)
                    chunk = []
                    chunk_len = 0
                    field_idx += 1
                chunk.append(line)
                chunk_len += len(line) + 1
            if chunk:
                embed.add_field(name=f"\u200b" if field_idx > 1 else f"{len(sorted_officers)} officers", value="\n".join(chunk), inline=False)
        embed.set_footer(text=f"ENP Bot v{__version__}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="shifts", description="Show weekly and total shifts for all members")
    @app_commands.describe(date="Pull from stored logs (YYYY-MM-DD). Leave blank for live data.")
    async def cmd_shifts(self, interaction: discord.Interaction, date: str | None = None):
        await interaction.response.defer()

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
            parsed_date = datetime.strptime(date, "%Y-%m-%d")
            label = "Week Starting" if parsed_date.weekday() == 0 else "Week Ending"
            title_suffix = f" \u2014 {label} {date}"
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

        embed = self._build_shifts_overview_embed(members, title_suffix)
        await interaction.followup.send(embed=embed)

    @cmd_shifts.autocomplete("date")
    async def shifts_date_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        dates = get_available_snapshot_dates()
        choices: list[app_commands.Choice[str]] = []
        for d in dates:
            if current.lower() not in d:
                continue
            try:
                label = "Week starting" if datetime.strptime(d, "%Y-%m-%d").weekday() == 0 else "Week ending"
            except ValueError:
                label = "Week ending"
            choices.append(app_commands.Choice(name=f"{label} {d}", value=d))
            if len(choices) >= 25:
                break
        return choices

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
