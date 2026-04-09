import io
import re
from datetime import datetime, timezone

import discord
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from discord import app_commands

from config import __version__, ALLOWED_ROLES


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
# Rank helpers
# ---------------------------------------------------------------------------
def strip_rank_tier(role_name: str) -> str:
    """Strip tier suffixes (I, II, III, etc.) and whitespace from a rank name."""
    return re.sub(r"\s+[IVX]+$", "", role_name.strip())


# ---------------------------------------------------------------------------
# Event formatting
# ---------------------------------------------------------------------------
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


_DEFAULT_ICON = "\U0001f46e"


def format_event_line(row, include_icon: bool = True) -> str:
    """Format a single event as a compact line for embed descriptions."""
    icon = f"{ACTION_ICONS.get(row['action'], _DEFAULT_ICON)} " if include_icon else ""
    ts = f"<t:{row['timestamp']}:f>"
    if row["action"] == "pardoned":
        return f"{icon}**{row['officer']}** pardoned **{row['perpetrator']}** of all crimes {ts}"
    if row["action"] == "released":
        return f"{icon}**{row['officer']}** released **{row['perpetrator']}** from prison {ts}"
    details = f" — {row['details']}" if row["details"] else ""
    return f"{icon}**{row['officer']}** {row['action']} **{row['perpetrator']}**{details} {ts}"


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


# ---------------------------------------------------------------------------
# Graph constants
# ---------------------------------------------------------------------------
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
# Shared graph renderer
# ---------------------------------------------------------------------------
def render_shifts_graph(data: dict[str, dict[str, int]]) -> io.BytesIO:
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
