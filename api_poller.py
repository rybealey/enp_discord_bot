import re
import logging
import aiohttp

logger = logging.getLogger("enp_bot.poller")

API_URL = "https://api.anubisrp.com/v2.5/livefeed"
HEADERS = {"User-Agent": "ENPBot/1.0"}

# Police event indicator
POLICE_EMOJI = "\U0001f46e"  # 👮

# Patterns for police actions:
#   "👮 OfficerName arrested PlayerName for 18 minutes"
#   "👮 OfficerName charged PlayerName for '911Abuse'"
#   "👮 OfficerName pardoned PlayerName of all crimes"
ARREST_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+arrested\s+(.+?)\s+for\s+(.+)$"
)
CHARGE_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+charged\s+(.+?)(?:\s+(?:with|for)\s+(.+))?$"
)
PARDON_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+pardoned\s+(.+?)(?:\s+(?:of|for)\s+(.+))?$"
)


def parse_police_event(raw: dict) -> dict | None:
    """Parse a raw API event. Returns a dict if it's a police event, else None."""
    text = raw.get("message_text", "")

    # Only process events with the police emoji
    if POLICE_EMOJI not in text:
        return None

    event = {
        "id": raw["id"],
        "raw_text": text,
        "timestamp": raw["timestamp"],
        "officer": None,
        "perpetrator": None,
        "action": None,
        "details": None,
    }

    match = ARREST_PATTERN.match(text)
    if match:
        event["officer"] = match.group(1).strip()
        event["action"] = "arrested"
        event["perpetrator"] = match.group(2).strip()
        event["details"] = match.group(3).strip()  # e.g. "18 minutes"
        return event

    match = CHARGE_PATTERN.match(text)
    if match:
        event["officer"] = match.group(1).strip()
        event["action"] = "charged"
        event["perpetrator"] = match.group(2).strip()
        event["details"] = match.group(3).strip() if match.group(3) else None
        return event

    match = PARDON_PATTERN.match(text)
    if match:
        event["officer"] = match.group(1).strip()
        event["action"] = "pardoned"
        event["perpetrator"] = match.group(2).strip()
        event["details"] = match.group(3).strip() if match.group(3) else None
        return event

    # Unknown police event — log it so we can add a pattern later
    logger.warning("Unrecognized police event format: %s", text)
    return None


async def fetch_livefeed(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch the livefeed and return only parsed police events."""
    try:
        async with session.get(API_URL, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                logger.warning("API returned status %d", resp.status)
                return []
            data = await resp.json()
            raw_events = data.get("livefeed", [])
            parsed = []
            for raw in raw_events:
                event = parse_police_event(raw)
                if event:
                    parsed.append(event)
            return parsed
    except Exception as e:
        logger.error("Failed to fetch livefeed: %s", e)
        return []
