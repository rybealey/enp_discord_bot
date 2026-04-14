__version__ = "2.5.2"

import logging
import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_ROLES = [r.strip() for r in os.getenv("ALLOWED_ROLES", "Admin").split(",")]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
_livefeed_ch = os.getenv("LIVEFEED_CHANNEL_ID")
LIVEFEED_CHANNEL_ID = int(_livefeed_ch) if _livefeed_ch else None
_shifts_ch = os.getenv("SHIFTS_CHANNEL_ID", _livefeed_ch or "")
SHIFTS_CHANNEL_ID = int(_shifts_ch) if _shifts_ch else None
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
