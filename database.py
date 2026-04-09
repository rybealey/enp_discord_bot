import sqlite3
import os
from datetime import datetime, timezone, timedelta

DB_DIR = os.getenv("DB_PATH", os.path.dirname(__file__))
DB_PATH = os.path.join(DB_DIR, "enp_bot.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS police_events (
            id          INTEGER PRIMARY KEY,
            officer     TEXT    NOT NULL,
            perpetrator TEXT    NOT NULL,
            action      TEXT    NOT NULL,
            details     TEXT,
            raw_text    TEXT    NOT NULL,
            timestamp   INTEGER NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_police_timestamp   ON police_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_police_officer     ON police_events(officer);
        CREATE INDEX IF NOT EXISTS idx_police_perpetrator ON police_events(perpetrator);
        CREATE INDEX IF NOT EXISTS idx_police_action      ON police_events(action);

        CREATE TABLE IF NOT EXISTS shift_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL,
            rank            TEXT    NOT NULL,
            weekly_shifts   INTEGER NOT NULL,
            total_shifts    INTEGER NOT NULL,
            week_ending     TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_shift_week    ON shift_snapshots(week_ending);
        CREATE INDEX IF NOT EXISTS idx_shift_user    ON shift_snapshots(username);

        CREATE TABLE IF NOT EXISTS shift_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL,
            rank          TEXT    NOT NULL,
            weekly_shifts INTEGER NOT NULL,
            total_shifts  INTEGER NOT NULL,
            timestamp     INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_shiftlog_user ON shift_log(username);
        CREATE INDEX IF NOT EXISTS idx_shiftlog_ts   ON shift_log(timestamp);

        CREATE TABLE IF NOT EXISTS shift_cache (
            username       TEXT PRIMARY KEY,
            weekly_shifts  INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS timezones (
            label      TEXT PRIMARY KEY,
            start_hour INTEGER NOT NULL,
            end_hour   INTEGER NOT NULL
        );

        INSERT OR IGNORE INTO timezones (label, start_hour, end_hour) VALUES
            ('OC',  6, 14),
            ('EU', 14, 22),
            ('NA', 22,  6);

        CREATE TABLE IF NOT EXISTS bot_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()

    # One-time migration: clear stale shift data from pre-v2.0.0
    if not conn.execute("SELECT 1 FROM bot_meta WHERE key = 'shift_log_v2_reset'").fetchone():
        conn.execute("DELETE FROM shift_log")
        conn.execute("DELETE FROM shift_cache")
        conn.execute("INSERT INTO bot_meta (key, value) VALUES ('shift_log_v2_reset', '1')")
        conn.commit()

    conn.close()


def _monday_midnight_ts() -> int:
    """Return the Unix timestamp for Monday 00:00 UTC of the current week."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    monday_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    return int(monday_midnight.timestamp())


def insert_events_batch(events: list[dict]) -> list[dict]:
    """Insert new police events in a batch, skipping duplicates. Returns list of newly inserted events."""
    if not events:
        return []

    conn = get_connection()
    incoming_ids = [e["id"] for e in events]
    placeholders = ",".join("?" for _ in incoming_ids)
    existing = {
        row[0]
        for row in conn.execute(
            f"SELECT id FROM police_events WHERE id IN ({placeholders})",
            incoming_ids,
        ).fetchall()
    }
    new_events = [e for e in events if e["id"] not in existing]
    if new_events:
        conn.executemany(
            """INSERT OR IGNORE INTO police_events
               (id, officer, perpetrator, action, details, raw_text, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    e["id"],
                    e["officer"],
                    e["perpetrator"],
                    e["action"],
                    e.get("details"),
                    e["raw_text"],
                    e["timestamp"],
                )
                for e in new_events
            ],
        )
        conn.commit()
    conn.close()
    return new_events


def get_recent_events(limit: int = 10) -> list[sqlite3.Row]:
    monday_ts = _monday_midnight_ts()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
        (monday_ts, limit),
    ).fetchall()
    conn.close()
    return rows


def get_events_by_officer(officer: str, limit: int = 10) -> list[sqlite3.Row]:
    monday_ts = _monday_midnight_ts()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events WHERE officer LIKE ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
        (f"%{officer}%", monday_ts, limit),
    ).fetchall()
    conn.close()
    return rows


def get_events_by_perpetrator(name: str, limit: int = 10) -> list[sqlite3.Row]:
    monday_ts = _monday_midnight_ts()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events WHERE perpetrator LIKE ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
        (f"%{name}%", monday_ts, limit),
    ).fetchall()
    conn.close()
    return rows


def get_events_by_action(action: str, limit: int = 10) -> list[sqlite3.Row]:
    monday_ts = _monday_midnight_ts()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events WHERE action LIKE ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
        (f"%{action}%", monday_ts, limit),
    ).fetchall()
    conn.close()
    return rows


def get_weekly_arrest_leaderboard(limit: int = 10) -> list[sqlite3.Row]:
    """Top officers by arrest count for the current week (Mon 00:00 UTC). Pass limit=0 for all."""
    monday_ts = _monday_midnight_ts()
    conn = get_connection()
    query = """SELECT officer, COUNT(*) as arrest_count
               FROM police_events
               WHERE action = 'arrested'
                 AND timestamp >= ?
               GROUP BY officer
               ORDER BY arrest_count DESC"""
    if limit > 0:
        query += " LIMIT ?"
        rows = conn.execute(query, (monday_ts, limit)).fetchall()
    else:
        rows = conn.execute(query, (monday_ts,)).fetchall()
    conn.close()
    return rows


def get_weekly_action_by_officer(action: str, limit: int = 15) -> list[sqlite3.Row]:
    """Officers ranked by count of a specific action for the current week (Mon 00:00 UTC)."""
    monday_ts = _monday_midnight_ts()
    conn = get_connection()
    rows = conn.execute(
        """SELECT officer, COUNT(*) as action_count
           FROM police_events
           WHERE action = ?
             AND timestamp >= ?
           GROUP BY officer
           ORDER BY action_count DESC
           LIMIT ?""",
        (action, monday_ts, limit),
    ).fetchall()
    conn.close()
    return rows


def get_event_count() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM police_events").fetchone()[0]
    conn.close()
    return count


def insert_shift_snapshot(members: list[dict], week_ending: str) -> int:
    """Insert a weekly shift snapshot for all members. Returns rows inserted."""
    if not members:
        return 0
    conn = get_connection()
    conn.executemany(
        """INSERT INTO shift_snapshots (username, rank, weekly_shifts, total_shifts, week_ending)
           VALUES (?, ?, ?, ?, ?)""",
        [(m["username"], m["rank"], m["weekly_shifts"], m["total_shifts"], week_ending) for m in members],
    )
    conn.commit()
    count = len(members)
    conn.close()
    return count


def get_shift_snapshot(week_ending: str) -> list[sqlite3.Row]:
    """Return all shift snapshot rows for a given week_ending date."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM shift_snapshots WHERE week_ending = ? ORDER BY rank, username",
        (week_ending,),
    ).fetchall()
    conn.close()
    return rows


def get_available_snapshot_dates() -> list[str]:
    """Return all distinct week_ending dates with stored snapshots, most recent first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT week_ending FROM shift_snapshots ORDER BY week_ending DESC"
    ).fetchall()
    conn.close()
    return [r["week_ending"] for r in rows]


def get_timezones() -> list[sqlite3.Row]:
    """Return all timezone definitions."""
    conn = get_connection()
    rows = conn.execute("SELECT label, start_hour, end_hour FROM timezones ORDER BY start_hour").fetchall()
    conn.close()
    return rows


def get_current_timezone() -> sqlite3.Row | None:
    """Return the timezone whose window contains the current GMT hour."""
    now_hour = datetime.now(timezone.utc).hour
    conn = get_connection()
    row = conn.execute(
        """SELECT label, start_hour, end_hour FROM timezones
           WHERE (start_hour < end_hour AND ? >= start_hour AND ? < end_hour)
              OR (start_hour > end_hour AND (? >= start_hour OR ? < end_hour))""",
        (now_hour, now_hour, now_hour, now_hour),
    ).fetchone()
    conn.close()
    return row


def get_shift_cache() -> dict[str, int]:
    """Return {username: weekly_shifts} from the cache."""
    conn = get_connection()
    rows = conn.execute("SELECT username, weekly_shifts FROM shift_cache").fetchall()
    conn.close()
    return {r["username"]: r["weekly_shifts"] for r in rows}


def update_shift_cache_and_log(members: list[dict]) -> int:
    """Compare incoming member data against cache, log new shifts, update cache.

    Each member dict must have: username, rank, weekly_shifts.
    Returns the number of new shift entries logged.
    """
    if not members:
        return 0

    cache = get_shift_cache()
    now_ts = int(datetime.now(timezone.utc).timestamp())

    new_entries = []
    for m in members:
        username = m["username"]
        current = m["weekly_shifts"]

        if username not in cache:
            # First time seeing this user — seed cache only, don't log
            continue

        previous = cache[username]
        if current > previous:
            diff = current - previous
            for i in range(diff):
                # Each logged shift gets the cumulative count at that point
                shift_num = previous + i + 1
                new_entries.append((
                    username, m["rank"], shift_num, m["total_shifts"], now_ts
                ))

    conn = get_connection()
    if new_entries:
        conn.executemany(
            """INSERT INTO shift_log (username, rank, weekly_shifts, total_shifts, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            new_entries,
        )
    # Upsert all members into cache
    conn.executemany(
        """INSERT INTO shift_cache (username, weekly_shifts) VALUES (?, ?)
           ON CONFLICT(username) DO UPDATE SET weekly_shifts = excluded.weekly_shifts""",
        [(m["username"], m["weekly_shifts"]) for m in members],
    )
    conn.commit()
    conn.close()
    return len(new_entries)


def reset_shift_cache():
    """Clear the shift cache (call at the start of each week)."""
    conn = get_connection()
    conn.execute("DELETE FROM shift_cache")
    conn.commit()
    conn.close()


def get_shift_log(username: str | None = None, since_ts: int | None = None) -> list[sqlite3.Row]:
    """Query shift log entries, optionally filtered by username and/or timestamp."""
    conditions = []
    params = []
    if username:
        conditions.append("username LIKE ?")
        params.append(f"%{username}%")
    if since_ts is not None:
        conditions.append("timestamp >= ?")
        params.append(since_ts)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = get_connection()
    rows = conn.execute(
        f"SELECT * FROM shift_log {where} ORDER BY timestamp DESC", params
    ).fetchall()
    conn.close()
    return rows


def get_weekly_shifts_by_timezone(limit: int = 15) -> dict[str, dict[str, int]]:
    """Return {username: {tz_label: count}} for shifts logged this week.

    Each shift's timestamp hour (UTC) is matched against the timezones table
    to determine which timezone window it fell in.
    """
    monday_ts = _monday_midnight_ts()

    conn = get_connection()
    tz_rows = conn.execute("SELECT label, start_hour, end_hour FROM timezones").fetchall()
    logs = conn.execute(
        "SELECT username, timestamp FROM shift_log WHERE timestamp >= ? ORDER BY timestamp",
        (monday_ts,),
    ).fetchall()
    conn.close()

    # Apply DST offset: when enabled, shift windows back by 1 hour in UTC
    dst_offset = 1 if get_meta("dst_enabled") == "1" else 0
    tz_defs = [
        (r["label"], (r["start_hour"] - dst_offset) % 24, (r["end_hour"] - dst_offset) % 24)
        for r in tz_rows
    ]

    def classify_hour(hour: int) -> str:
        for label, start, end in tz_defs:
            if start < end and start <= hour < end:
                return label
            if start > end and (hour >= start or hour < end):
                return label
        return "Unknown"

    result: dict[str, dict[str, int]] = {}
    for row in logs:
        hour = datetime.fromtimestamp(row["timestamp"], tz=timezone.utc).hour
        tz_label = classify_hour(hour)
        user = row["username"]
        result.setdefault(user, {})
        result[user][tz_label] = result[user].get(tz_label, 0) + 1

    # Sort by total shifts descending, limit
    sorted_users = sorted(result.keys(), key=lambda u: sum(result[u].values()), reverse=True)[:limit]
    return {u: result[u] for u in sorted_users}


def get_meta(key: str) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT value FROM bot_meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_meta(key: str, value: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO bot_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    conn.commit()
    conn.close()
