"""SQLite schema and idempotent loaders.

We store *raw facts* (per-round strokes, final positions) and derive analysis
(36/54-hole leaders, conversion rates) at query time. That keeps the door open
to redefining "leader" later without re-scraping a single byte.

All loads use INSERT OR REPLACE keyed on natural primary keys, so re-running the
backfill over a partially-populated DB is safe and converges to the same state.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from .parse import ParsedEvent

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tournaments (
    event_id          INTEGER PRIMARY KEY,
    season            INTEGER NOT NULL,
    calendar_year     INTEGER,
    name              TEXT NOT NULL,
    short_name        TEXT,
    start_date        TEXT,
    end_date          TEXT,
    venue             TEXT,
    city              TEXT,
    state             TEXT,
    par               INTEGER,
    purse             REAL,
    playoff_type      TEXT,
    num_rounds        INTEGER,
    field_size        INTEGER,
    is_major          INTEGER NOT NULL DEFAULT 0,
    winner_player_id  INTEGER
);

CREATE TABLE IF NOT EXISTS players (
    player_id  INTEGER PRIMARY KEY,
    name       TEXT,
    country    TEXT
);

CREATE TABLE IF NOT EXISTS player_rounds (
    event_id    INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    round_num   INTEGER NOT NULL,
    strokes     INTEGER,
    to_par      INTEGER,
    out_score   INTEGER,
    in_score    INTEGER,
    is_playoff  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (event_id, player_id, round_num)
);

CREATE TABLE IF NOT EXISTS player_results (
    event_id          INTEGER NOT NULL,
    player_id         INTEGER NOT NULL,
    position          TEXT,
    position_numeric  INTEGER,
    is_tie            INTEGER,
    total_strokes     INTEGER,
    total_to_par      INTEGER,
    status            TEXT,
    made_cut          INTEGER,
    earnings          REAL,
    amateur           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (event_id, player_id)
);

-- Hole-level depth (re-parsed from the same cached ESPN scoreboards). par is the
-- consensus across the field for that hole at that event; courses are derived by
-- joining to tournaments.venue.
CREATE TABLE IF NOT EXISTS event_holes (
    event_id  INTEGER NOT NULL,
    hole_num  INTEGER NOT NULL,
    par       INTEGER,
    PRIMARY KEY (event_id, hole_num)
);

CREATE TABLE IF NOT EXISTS player_hole_scores (
    event_id   INTEGER NOT NULL,
    player_id  INTEGER NOT NULL,
    round_num  INTEGER NOT NULL,
    hole_num   INTEGER NOT NULL,
    strokes    INTEGER,
    to_par     INTEGER,
    PRIMARY KEY (event_id, player_id, round_num, hole_num)
);

-- Tier 2: deep major history (1960-2004), winner + 36/54-hole leaders only.
-- Sourced from Wikipedia, lower granularity than Tier 1 (no full field).
CREATE TABLE IF NOT EXISTS major_history (
    year             INTEGER NOT NULL,
    major            TEXT NOT NULL,   -- Masters / U.S. Open / The Open / PGA Championship
    winner           TEXT,
    winning_score    TEXT,
    leader_36        TEXT,
    leader_36_score  TEXT,
    leader_54        TEXT,
    leader_54_score  TEXT,
    playoff          INTEGER,
    leader_36_won    INTEGER,         -- derived at load time
    leader_54_won    INTEGER,         -- derived at load time
    source_url       TEXT,
    PRIMARY KEY (year, major)
);

CREATE INDEX IF NOT EXISTS idx_rounds_event   ON player_rounds(event_id);
CREATE INDEX IF NOT EXISTS idx_results_event  ON player_results(event_id);
CREATE INDEX IF NOT EXISTS idx_results_player ON player_results(player_id);
CREATE INDEX IF NOT EXISTS idx_tourn_season   ON tournaments(season);
CREATE INDEX IF NOT EXISTS idx_tourn_major    ON tournaments(is_major);
CREATE INDEX IF NOT EXISTS idx_holescores_event  ON player_hole_scores(event_id);
CREATE INDEX IF NOT EXISTS idx_holescores_player ON player_hole_scores(player_id);
CREATE INDEX IF NOT EXISTS idx_evholes_event     ON event_holes(event_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _cols(rows: list[dict]) -> tuple[list[str], str]:
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    return cols, placeholders


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols, placeholders = _cols(rows)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])


def load_event(conn: sqlite3.Connection, parsed: ParsedEvent) -> None:
    """Idempotently upsert one parsed event into all four tables."""
    _insert(conn, "tournaments", [parsed.tournament])
    # de-dup players within the event (same id can't appear twice, but be safe)
    seen: dict[int, dict] = {p["player_id"]: p for p in parsed.players}
    _insert(conn, "players", list(seen.values()))
    _insert(conn, "player_rounds", parsed.rounds)
    _insert(conn, "player_results", parsed.results)
    conn.commit()


def load_event_holes(conn: sqlite3.Connection, event_holes: list[dict],
                     hole_scores: list[dict]) -> None:
    """Idempotently upsert one event's hole-level rows."""
    _insert(conn, "event_holes", event_holes)
    _insert(conn, "player_hole_scores", hole_scores)
    conn.commit()


def event_exists(conn: sqlite3.Connection, event_id: int) -> bool:
    cur = conn.execute("SELECT 1 FROM tournaments WHERE event_id = ?", (event_id,))
    return cur.fetchone() is not None


def summary(conn: sqlite3.Connection) -> dict:
    q = conn.execute
    return {
        "tournaments": q("SELECT COUNT(*) FROM tournaments").fetchone()[0],
        "majors": q("SELECT COUNT(*) FROM tournaments WHERE is_major = 1").fetchone()[0],
        "players": q("SELECT COUNT(*) FROM players").fetchone()[0],
        "player_rounds": q("SELECT COUNT(*) FROM player_rounds").fetchone()[0],
        "player_results": q("SELECT COUNT(*) FROM player_results").fetchone()[0],
        "season_min": q("SELECT MIN(season) FROM tournaments").fetchone()[0],
        "season_max": q("SELECT MAX(season) FROM tournaments").fetchone()[0],
    }
