"""SQLite schema + idempotent loaders for the OSRS clan database.

A snapshot is one point-in-time Hiscores reading per player; gains are computed
later (parse.diff_snapshots) as the diff between two snapshots. Snapshots are an
append-only time series, so (rsn, captured_at) is UNIQUE and re-running a capture
at the same instant is a no-op rather than a duplicate.
"""

from __future__ import annotations

import logging
import sqlite3

from osrs import parse

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
    rsn          TEXT PRIMARY KEY,   -- canonical (lower-cased) lookup key
    display_name TEXT,               -- spelling as the user typed it
    added_at     TEXT,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    rsn           TEXT NOT NULL,
    captured_at   TEXT NOT NULL,     -- UTC ISO-8601, stamped once per capture run
    overall_xp    INTEGER,
    overall_level INTEGER,           -- total level (sum of skill levels)
    overall_rank  INTEGER,
    UNIQUE(rsn, captured_at)
);

CREATE TABLE IF NOT EXISTS skill_xp (
    snapshot_id INTEGER NOT NULL,
    skill       TEXT NOT NULL,
    rank        INTEGER,
    level       INTEGER,
    xp          INTEGER,
    PRIMARY KEY (snapshot_id, skill)
);

CREATE INDEX IF NOT EXISTS idx_snap_rsn  ON snapshots(rsn);
CREATE INDEX IF NOT EXISTS idx_snap_time ON snapshots(captured_at);
"""


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def add_player(conn: sqlite3.Connection, display_name: str,
               added_at: str, note: str | None = None) -> bool:
    """Track a new player. Returns True if added, False if already tracked."""
    rsn = parse.canonical_rsn(display_name)
    cur = conn.execute(
        "INSERT OR IGNORE INTO players (rsn, display_name, added_at, note) "
        "VALUES (?, ?, ?, ?)",
        (rsn, display_name.strip(), added_at, note),
    )
    return cur.rowcount > 0


def tracked_players(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(canonical_rsn, display_name) for every tracked player, by display name."""
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT rsn, display_name FROM players ORDER BY display_name COLLATE NOCASE"
        )
    ]


def insert_snapshot(conn: sqlite3.Connection, rsn: str,
                    captured_at: str, skills: list[dict]) -> int:
    """Persist one capture; return its snapshot_id (existing id if a no-op).

    INSERT OR IGNORE on the (rsn, captured_at) unique key makes a same-instant
    re-run idempotent; skill rows use INSERT OR REPLACE so a corrected re-read
    overwrites cleanly rather than erroring on the primary key.
    """
    ov = next((s for s in skills if s["skill"] == "Overall"), None)
    conn.execute(
        "INSERT OR IGNORE INTO snapshots "
        "(rsn, captured_at, overall_xp, overall_level, overall_rank) "
        "VALUES (?, ?, ?, ?, ?)",
        (rsn, captured_at,
         ov["xp"] if ov else None,
         ov["level"] if ov else None,
         ov["rank"] if ov else None),
    )
    snapshot_id = conn.execute(
        "SELECT snapshot_id FROM snapshots WHERE rsn = ? AND captured_at = ?",
        (rsn, captured_at),
    ).fetchone()[0]
    conn.executemany(
        "INSERT OR REPLACE INTO skill_xp (snapshot_id, skill, rank, level, xp) "
        "VALUES (?, ?, ?, ?, ?)",
        [(snapshot_id, s["skill"], s["rank"], s["level"], s["xp"]) for s in skills],
    )
    return snapshot_id
