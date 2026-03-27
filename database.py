import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "enp_bot.db")


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


def get_event_count() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM police_events").fetchone()[0]
    conn.close()
    return count
