import re
import logging
import aiohttp

logger = logging.getLogger("enp_bot.poller")

API_URL = "https://api.anubisrp.com/v2.5/livefeed"
HEADERS = {"User-Agent": "ENPBot/1.0"}

# Police event indicator
POLICE_EMOJI = "\U0001f46e"  # 👮

# Managerial event indicator (used by hire/send-home/fire)
MANAGERIAL_EMOJI = "\U0001f3db\ufe0f"  # 🏛️

# Quit event indicator (worker emoji, fired by the member, not a manager)
QUIT_EMOJI = "\U0001f477"  # 👷

# ---------------------------------------------------------------------------
# Police action patterns
#   "👮 OfficerName arrested PlayerName for 18 minutes"
#   "👮 OfficerName charged PlayerName for '911Abuse'"
#   "👮 OfficerName pardoned PlayerName of all crimes"
#   "👮 OfficerName released PlayerName from prison"
# ---------------------------------------------------------------------------
ARREST_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+arrested\s+(.+?)\s+for\s+(.+)$"
)
CHARGE_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+charged\s+(.+?)(?:\s+(?:with|for)\s+(.+))?$"
)
PARDON_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+pardoned\s+(.+?)(?:\s+(?:of|for)\s+(.+))?$"
)
RELEASE_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+(?:force\s+)?released\s+(.+?)\s+from\s+prison$"
)

# ---------------------------------------------------------------------------
# Managerial / employment patterns
#   "🏛️ Y hired muba at 'Oasis Hospital'"
#   "🏛️ Beelzebub sent holy home for '69' minutes"
#   "🏛️ twist fired Westt_14 from 'Egyptian National Police'"
#   "👷 babie quit their job at 'Azural Armoury'"
# ---------------------------------------------------------------------------
HIRE_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+hired\s+(.+?)\s+at\s+'(.+)'$"
)
SEND_HOME_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+sent\s+(.+?)\s+home\s+for\s+'(.+?)'\s+minutes?$"
)
FIRED_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+fired\s+(.+?)\s+from\s+'(.+)'$"
)
QUIT_PATTERN = re.compile(
    r"^.+?\s+(.+?)\s+quit\s+their\s+job\s+at\s+'(.+)'$"
)


def parse_police_event(raw: dict) -> dict | None:
    """Parse a police event. Returns a dict if matched, else None.

    Returned dict keys: id, raw_text, timestamp, officer, perpetrator, action, details.
    """
    text = raw.get("message_text", "")

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
        event["details"] = match.group(3).strip()
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

    match = RELEASE_PATTERN.match(text)
    if match:
        event["officer"] = match.group(1).strip()
        event["action"] = "released"
        event["perpetrator"] = match.group(2).strip()
        event["details"] = "from prison"
        return event

    logger.warning("Unrecognized police event format: %s", text)
    return None


def parse_managerial_event(raw: dict) -> dict | None:
    """Parse an employment/managerial event. Returns a dict if matched, else None.

    Returned dict keys:
        id, raw_text, timestamp, event_type, member, actor, corp, details

    event_type is one of: "hired", "sent_home", "fired", "quit".

    For "sent_home", `corp` is None — the livefeed message does not include
    the corp name. The caller must filter such events by checking whether
    `actor` is currently in the ENP roster.
    """
    text = raw.get("message_text", "")

    # Hire / send_home / fired all use 🏛️
    # Quit uses 👷
    has_managerial = MANAGERIAL_EMOJI in text
    has_quit = QUIT_EMOJI in text
    if not (has_managerial or has_quit):
        return None

    base = {
        "id": raw["id"],
        "raw_text": text,
        "timestamp": raw["timestamp"],
        "event_type": None,
        "member": None,
        "actor": None,
        "corp": None,
        "details": None,
    }

    if has_managerial:
        m = HIRE_PATTERN.match(text)
        if m:
            return {**base, "event_type": "hired", "actor": m.group(1).strip(),
                    "member": m.group(2).strip(), "corp": m.group(3).strip()}

        m = SEND_HOME_PATTERN.match(text)
        if m:
            return {**base, "event_type": "sent_home", "actor": m.group(1).strip(),
                    "member": m.group(2).strip(), "details": m.group(3).strip()}

        m = FIRED_PATTERN.match(text)
        if m:
            return {**base, "event_type": "fired", "actor": m.group(1).strip(),
                    "member": m.group(2).strip(), "corp": m.group(3).strip()}

    if has_quit:
        m = QUIT_PATTERN.match(text)
        if m:
            return {**base, "event_type": "quit",
                    "member": m.group(1).strip(), "corp": m.group(2).strip()}

    return None


async def fetch_livefeed(session: aiohttp.ClientSession) -> dict:
    """Fetch the livefeed and return parsed events grouped by category.

    Returns: {"police": [...], "managerial": [...]}.
    """
    try:
        async with session.get(API_URL, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                logger.warning("API returned status %d", resp.status)
                return {"police": [], "managerial": []}
            data = await resp.json()
            raw_events = data.get("livefeed", [])
            police: list[dict] = []
            managerial: list[dict] = []
            for raw in raw_events:
                pe = parse_police_event(raw)
                if pe:
                    police.append(pe)
                    continue
                me = parse_managerial_event(raw)
                if me:
                    managerial.append(me)
            return {"police": police, "managerial": managerial}
    except Exception as e:
        logger.error("Failed to fetch livefeed: %s", e)
        return {"police": [], "managerial": []}
