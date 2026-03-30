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

        CREATE TABLE IF NOT EXISTS bot_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def insert_events_batch(events: list[dict]) -> int:
    """Insert new police events in a batch, skipping duplicates. Returns count of new rows."""
    if not events:
        return 0

    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) FROM police_events").fetchone()[0]
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
            for e in events
        ],
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM police_events").fetchone()[0]
    conn.close()
    return after - before


def get_recent_events(limit: int = 10) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_events_by_officer(officer: str, limit: int = 10) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events WHERE officer LIKE ? ORDER BY timestamp DESC LIMIT ?",
        (f"%{officer}%", limit),
    ).fetchall()
    conn.close()
    return rows


def get_events_by_perpetrator(name: str, limit: int = 10) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events WHERE perpetrator LIKE ? ORDER BY timestamp DESC LIMIT ?",
        (f"%{name}%", limit),
    ).fetchall()
    conn.close()
    return rows


def get_events_by_action(action: str, limit: int = 10) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM police_events WHERE action LIKE ? ORDER BY timestamp DESC LIMIT ?",
        (f"%{action}%", limit),
    ).fetchall()
    conn.close()
    return rows


def get_weekly_arrest_leaderboard(limit: int = 10) -> list[sqlite3.Row]:
    """Top officers by arrest count for the current week (Mon 00:00 UTC)."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()  # 0 = Monday
    monday_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    monday_ts = int(monday_midnight.timestamp())

    conn = get_connection()
    rows = conn.execute(
        """SELECT officer, COUNT(*) as arrest_count
           FROM police_events
           WHERE action = 'arrested'
             AND timestamp >= ?
           GROUP BY officer
           ORDER BY arrest_count DESC
           LIMIT ?""",
        (monday_ts, limit),
    ).fetchall()
    conn.close()
    return rows


def get_weekly_action_by_officer(action: str, limit: int = 15) -> list[sqlite3.Row]:
    """Officers ranked by count of a specific action for the current week (Mon 00:00 UTC)."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()  # 0 = Monday
    monday_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    monday_ts = int(monday_midnight.timestamp())

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
