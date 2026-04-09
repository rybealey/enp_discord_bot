__version__ = "2.3.3"

import io
import os
import re
import logging
from collections import OrderedDict
from datetime import datetime, time, timezone

import aiohttp
import discord
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from database import (
    init_db,
    insert_events_batch,
    insert_shift_snapshot,
    get_shift_snapshot,
    get_available_snapshot_dates,
    get_recent_events,
    get_events_by_officer,
    get_events_by_perpetrator,
    get_events_by_action,
    get_weekly_arrest_leaderboard,
    get_weekly_action_by_officer,
    get_event_count,
    update_shift_cache_and_log,
    reset_shift_cache,
    get_weekly_shifts_by_timezone,
    get_weekly_shift_sum,
    get_total_shift_sum,
    get_meta,
    set_meta,
)
from api_poller import fetch_livefeed

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_ROLES = [r.strip() for r in os.getenv("ALLOWED_ROLES", "Admin").split(",")]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
_livefeed_ch = os.getenv("LIVEFEED_CHANNEL_ID")
LIVEFEED_CHANNEL_ID = int(_livefeed_ch) if _livefeed_ch else None
CORP_API_URL = "https://api.anubisrp.com/v2.5/corp/id/1"
WEEKLY_SHIFT_REQ = 40

# Base rank ordering from highest to lowest (used by /shifts)
RANK_ORDER = ["Colonel", "Captain", "Lieutenant", "Sergeant", "Corporal", "Private"]

RANK_EMOJIS = {
    "Colonel": "\u2B50",       # ⭐
    "Captain": "\U0001f396",   # 🎖
    "Lieutenant": "\U0001f6e1",# 🛡
    "Sergeant": "\u2694\ufe0f",# ⚔️
    "Corporal": "\U0001f6e1",  # 🛡
    "Private": "\U0001f46e",   # 👮
}

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
    if not LIVEFEED_CHANNEL_ID:
        return

    events = await fetch_livefeed(bot.http_session)
    if events:
        new_events = insert_events_batch(events)
        if new_events:
            logger.info("Stored %d new police events", len(new_events))
            channel = bot.get_channel(LIVEFEED_CHANNEL_ID)
            if not channel:
                logger.warning("Livefeed channel %d not found — are the ID and bot permissions correct?", LIVEFEED_CHANNEL_ID)
                return
            for event in new_events:
                try:
                    embed = discord.Embed(
                        title=f"{ACTION_ICONS.get(event['action'], '\U0001f46e')} {event['action'].title()}",
                        description=format_event_line(event),
                        color=ACTION_COLORS.get(event["action"], discord.Color.blurple()),
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text=f"ENP Bot v{__version__}")
                    await channel.send(embed=embed)
                except Exception:
                    logger.exception("Failed to send livefeed embed for event %s", event["id"])


@poll_livefeed.before_loop
async def before_poll():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Weekly shift snapshot task — runs every Sunday at 23:55 UTC
# ---------------------------------------------------------------------------
@tasks.loop(time=[time(hour=23, minute=55, tzinfo=timezone.utc),
                   time(hour=0, minute=5, tzinfo=timezone.utc)])
async def weekly_shift_snapshot():
    now = datetime.now(timezone.utc)
    # Run at 23:55 on Sunday or 00:05 on Monday
    if now.weekday() == 6 and now.hour == 23:
        pass  # Sunday 23:55
    elif now.weekday() == 0 and now.hour == 0:
        pass  # Monday 00:05
    else:
        return

    headers = {"User-Agent": "ENPBot/1.0"}
    try:
        async with bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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

        # Auto-post the weekly shifts graph to the livefeed channel
        if LIVEFEED_CHANNEL_ID:
            shift_data = get_weekly_shifts_by_timezone(limit=15)
            if shift_data:
                channel = bot.get_channel(LIVEFEED_CHANNEL_ID)
                if channel:
                    try:
                        buf = _render_shifts_graph(shift_data)
                        file = discord.File(buf, filename="graph.png")
                        embed = discord.Embed(
                            title="\U0001f4ca Weekly Shifts Summary",
                            color=discord.Color.blurple(),
                            timestamp=datetime.now(timezone.utc),
                        )
                        embed.set_image(url="attachment://graph.png")
                        embed.set_footer(text=f"ENP Bot v{__version__}")
                        await channel.send(embed=embed, file=file)
                        logger.info("Shift snapshot: posted weekly shifts graph to livefeed")
                    except Exception:
                        logger.exception("Shift snapshot: failed to post shifts graph")
                else:
                    logger.warning("Shift snapshot: livefeed channel %d not found", LIVEFEED_CHANNEL_ID)
    else:
        logger.warning("Shift snapshot: no members found in API response")


@weekly_shift_snapshot.before_loop
async def before_shift_snapshot():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Shift tracking task — polls every 1 minute, logs individual shifts
# ---------------------------------------------------------------------------
@tasks.loop(minutes=1)
async def poll_shifts():
    """Fetch shift data from the API and log new individual shifts."""
    # Reset cache at the start of each week (Monday 00:00 UTC)
    now = datetime.now(timezone.utc)
    last_reset = get_meta("shift_cache_reset_week")
    iso_week = now.strftime("%G-W%V")
    if last_reset != iso_week:
        reset_shift_cache()
        set_meta("shift_cache_reset_week", iso_week)
        logger.info("Shift cache reset for new week %s", iso_week)

    headers = {"User-Agent": "ENPBot/1.0"}
    try:
        async with bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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


@poll_shifts.before_loop
async def before_poll_shifts():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# DST auto-detection task — runs daily at 03:00 UTC
# ---------------------------------------------------------------------------
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


@tasks.loop(time=time(hour=3, minute=0, tzinfo=timezone.utc))
async def dst_check():
    """Automatically enable/disable DST based on UK BST rules."""
    now = datetime.now(timezone.utc)
    should_be = "1" if _is_uk_dst(now) else "0"
    current = get_meta("dst_enabled") or "0"
    if should_be != current:
        set_meta("dst_enabled", should_be)
        state = "enabled" if should_be == "1" else "disabled"
        logger.info("DST auto-check: %s (was %s)", state, "enabled" if current == "1" else "disabled")


@dst_check.before_loop
async def before_dst_check():
    await bot.wait_until_ready()


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

    bot.http_session = aiohttp.ClientSession()
    init_db()

    if not poll_livefeed.is_running():
        poll_livefeed.start()
    if not weekly_shift_snapshot.is_running():
        weekly_shift_snapshot.start()
    if not poll_shifts.is_running():
        poll_shifts.start()
    if not dst_check.is_running():
        dst_check.start()

    await tree.sync()
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
# Helpers
# ---------------------------------------------------------------------------
def strip_rank_tier(role_name: str) -> str:
    """Strip tier suffixes (I, II, III, etc.) and whitespace from a rank name."""
    return re.sub(r"\s+[IVX]+$", "", role_name.strip())


ACTION_COLORS = {
    "arrested": discord.Color.red(),
    "charged": discord.Color.orange(),
    "pardoned": discord.Color.green(),
    "released": discord.Color.teal(),
}

ACTION_ICONS = {
    "arrested": "\U0001f6a8",   # 🚨
    "charged": "\U0001f4cb",    # 📋
    "pardoned": "\u2705",       # ✅
    "released": "\U0001f513",   # 🔓
}


def format_event_line(row) -> str:
    """Format a single event as a compact line for embed descriptions."""
    icon = ACTION_ICONS.get(row["action"], "\U0001f46e")
    ts = f"<t:{row['timestamp']}:f>"
    if row["action"] == "pardoned":
        return f"{icon} **{row['officer']}** pardoned **{row['perpetrator']}** of all crimes {ts}"
    if row["action"] == "released":
        return f"{icon} **{row['officer']}** released **{row['perpetrator']}** from prison {ts}"
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

    lines = [format_event_line(e) for e in reversed(events)]
    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"ENP Bot v{__version__}")
    return embed


GRAPH_COLORS = {
    "arrested": "#e74c3c",
    "charged": "#e67e22",
    "pardoned": "#2ecc71",
    "released": "#1abc9c",
}

GRAPH_ACTION_CHOICES = [
    app_commands.Choice(name="Arrests", value="arrested"),
    app_commands.Choice(name="Charges", value="charged"),
    app_commands.Choice(name="Pardons", value="pardoned"),
    app_commands.Choice(name="Releases", value="released"),
    app_commands.Choice(name="Shifts", value="shifts"),
]

TZ_COLORS = {
    "OC": "#3498db",   # blue
    "EU": "#e67e22",   # orange
    "NA": "#2ecc71",   # green
}
TZ_ORDER = ["OC", "EU", "NA"]


# ---------------------------------------------------------------------------
# Slash Commands — Police Activity
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
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="officer", description="Look up recent actions by a specific officer")
@app_commands.describe(name="Officer name to look up")
async def cmd_officer(interaction: discord.Interaction, name: str):
    events = get_events_by_officer(name, limit=15)
    if not events:
        await interaction.response.send_message(f"No events found for officer **{name}**.", ephemeral=True)
        return

    embed = build_event_embed(f"Officer Report: {name}", events)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="suspect", description="Look up recent police actions against a player")
@app_commands.describe(name="Player name to look up")
async def cmd_suspect(interaction: discord.Interaction, name: str):
    events = get_events_by_perpetrator(name, limit=15)
    if not events:
        await interaction.response.send_message(f"No events found for **{name}**.", ephemeral=True)
        return

    embed = build_event_embed(f"Suspect Report: {name}", events)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="arrests", description="Show recent arrests")
@app_commands.describe(count="Number of arrests to show (default: 10, max: 25)")
async def cmd_arrests(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_events_by_action("arrested", limit=count)
    if not events:
        await interaction.response.send_message("No arrests recorded yet.", ephemeral=True)
        return

    embed = build_event_embed("Recent Arrests", events, color=discord.Color.red())
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="charges", description="Show recent charges")
@app_commands.describe(count="Number of charges to show (default: 10, max: 25)")
async def cmd_charges(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_events_by_action("charged", limit=count)
    if not events:
        await interaction.response.send_message("No charges recorded yet.", ephemeral=True)
        return

    embed = build_event_embed("Recent Charges", events, color=discord.Color.orange())
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="pardons", description="Show recent pardons")
@app_commands.describe(count="Number of pardons to show (default: 10, max: 25)")
async def cmd_pardons(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_events_by_action("pardoned", limit=count)
    if not events:
        await interaction.response.send_message("No pardons recorded yet.", ephemeral=True)
        return

    embed = build_event_embed("Recent Pardons", events, color=discord.Color.green())
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="releases", description="Show recent prison releases")
@app_commands.describe(count="Number of releases to show (default: 10, max: 25)")
async def cmd_releases(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    events = get_events_by_action("released", limit=count)
    if not events:
        await interaction.response.send_message("No releases recorded yet.", ephemeral=True)
        return

    embed = build_event_embed("Recent Releases", events, color=discord.Color.teal())
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Slash Commands — Shifts & Leaderboard
# ---------------------------------------------------------------------------
@tree.command(name="leaderboard", description="Top officers by arrest count for the current week")
@app_commands.describe(count="Number of officers to show (default: 10, max: 25)")
async def cmd_leaderboard(interaction: discord.Interaction, count: int = 10):
    count = min(count, 25)
    await interaction.response.defer()

    # Fetch all current corp members from the API
    all_members: set[str] = set()
    headers = {"User-Agent": "ENPBot/1.0"}
    try:
        async with bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                for rank in data.get("ranks", []):
                    for m in rank.get("members", []):
                        all_members.add(m["username"])
    except Exception:
        logger.warning("Leaderboard: failed to fetch corp members, showing DB-only results")

    # Get arrest counts from the database
    rows = get_weekly_arrest_leaderboard(limit=0)
    arrest_counts = {row["officer"]: row["arrest_count"] for row in rows}

    # Merge: add any corp members not already in the arrest data
    for member in all_members:
        if member not in arrest_counts:
            arrest_counts[member] = 0

    # Sort by arrest count descending, then alphabetically
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


@tree.command(name="shifts", description="Show weekly and total shifts for all members")
@app_commands.describe(date="Pull from stored logs (YYYY-MM-DD). Leave blank for live data.")
async def cmd_shifts(interaction: discord.Interaction, date: str | None = None):
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
            async with bot.http_session.get(CORP_API_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    dates = get_available_snapshot_dates()
    return [
        app_commands.Choice(name=f"Week ending {d}", value=d)
        for d in dates
        if current.lower() in d
    ][:25]


@tree.command(name="sum", description="Total sum of logged shift activity")
@app_commands.describe(scope="Count weekly shifts or all-time total shifts")
@app_commands.choices(scope=[
    app_commands.Choice(name="Weekly", value="weekly"),
    app_commands.Choice(name="Total", value="total"),
])
async def cmd_sum(interaction: discord.Interaction, scope: app_commands.Choice[str]):
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


# ---------------------------------------------------------------------------
# Slash Commands — Graphs
# ---------------------------------------------------------------------------
@tree.command(name="graph", description="Bar graph of officers by action type for the current week")
@app_commands.describe(action="Type of police action to graph")
@app_commands.choices(action=GRAPH_ACTION_CHOICES)
async def cmd_graph(interaction: discord.Interaction, action: app_commands.Choice[str]):
    if action.value == "shifts":
        await _graph_shifts(interaction)
        return

    rows = get_weekly_action_by_officer(action.value, limit=15)
    if not rows:
        await interaction.response.send_message(
            f"No {action.name.lower()} recorded this week.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

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


def _render_shifts_graph(data: dict[str, dict[str, int]]) -> io.BytesIO:
    """Render a shifts-by-timezone bar chart and return the PNG as a BytesIO buffer."""
    users = sorted(data.keys(), key=lambda u: sum(data[u].values()))

    fig, ax = plt.subplots(figsize=(10, max(3, len(users) * 0.5)))
    y_pos = np.arange(len(users))
    left = np.zeros(len(users))

    for tz in TZ_ORDER:
        counts = [data[u].get(tz, 0) for u in users]
        bars = ax.barh(y_pos, counts, left=left, color=TZ_COLORS.get(tz, "#7289da"),
                       edgecolor="white", linewidth=0.5, label=tz)
        for bar, count in zip(bars, counts):
            if count > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height() / 2,
                        str(count), ha="center", va="center", fontsize=9, fontweight="bold", color="white")
        left += counts

    totals = [sum(data[u].values()) for u in users]
    for i, total in enumerate(totals):
        ax.text(total + 0.3, i, str(total), va="center", fontsize=11, fontweight="bold", color="white")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(users)
    ax.set_xlabel("Shifts", fontsize=12, color="white")
    ax.set_title("Weekly Shifts by Timezone", fontsize=14, fontweight="bold", color="white", pad=12)

    ax.set_facecolor("#2b2d31")
    fig.set_facecolor("#2b2d31")
    ax.tick_params(colors="white", labelsize=11)
    ax.xaxis.label.set_color("white")
    for spine in ax.spines.values():
        spine.set_color("#40444b")
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))

    legend = ax.legend(loc="lower right", fontsize=10, facecolor="#2b2d31", edgecolor="#40444b")
    for text in legend.get_texts():
        text.set_color("white")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


async def _graph_shifts(interaction: discord.Interaction):
    """Render a stacked horizontal bar graph of shifts broken down by timezone."""
    data = get_weekly_shifts_by_timezone(limit=15)
    if not data:
        await interaction.response.send_message("No shift data recorded this week.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    buf = _render_shifts_graph(data)
    file = discord.File(buf, filename="graph.png")
    embed = discord.Embed(
        title="\U0001f4ca Weekly Shifts by Timezone",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_image(url="attachment://graph.png")
    embed.set_footer(text=f"ENP Bot v{__version__}")
    await interaction.followup.send(embed=embed, file=file)


# ---------------------------------------------------------------------------
# Slash Commands — Utility
# ---------------------------------------------------------------------------
@tree.command(name="help", description="Show a guide to all available bot commands")
async def cmd_help(interaction: discord.Interaction):
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
            "**/leaderboard** `[count]` \u2014 Top officers by arrests *(visible to all)*\n"
            "**/graph** `<action>` \u2014 Bar chart of weekly activity (Arrests, Charges, Pardons, Releases, Shifts)"
        ),
        inline=False,
    )

    embed.add_field(
        name="\u2699\ufe0f Utility",
        value=(
            "**/about** \u2014 Bot info and configuration\n"
            "**/help** \u2014 This message"
        ),
        inline=False,
    )

    embed.set_footer(text=f"ENP Bot v{__version__}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="about", description="Show bot info and configuration")
async def cmd_about(interaction: discord.Interaction):
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
    embed.set_footer(text=f"ENP Bot v{__version__}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


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
