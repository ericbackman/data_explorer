"""SQLite schema and idempotent loaders for the soccer database.

We store *raw facts* (matches, lineups, on-pitch events) and derive analysis
(standings, results, scorer tables, xG aggregates) at query time -- the same
discipline as pga/db.py. That keeps the door open to redefining things later
(e.g. how a knockout decided on penalties counts) without re-scraping a byte.

The schema is deliberately **competition-agnostic**. A World Cup, the Euros, the
Champions League, and the Premier League are all just rows in `competitions`
with different `kind`s; matches hang off a (competition, season) pair. Adding a
new competition is a new league-code, never a new table.

All loads use INSERT OR REPLACE keyed on natural primary keys, so re-running the
backfill over a partially-populated DB is safe and converges to the same state
(a live match goes from partial to Full Time and the row is simply replaced).

Tier 2 (StatsBomb event-level: every pass/shot with xG) will add a small set of
`sb_*` tables later; it joins onto these matches via (competition, season) and
is intentionally NOT part of this Tier-1 broad schema.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
-- A competition: a tournament (World Cup, Euro, Champions League) or a league
-- (Premier League...). `kind` drives query logic (a league has matchdays and a
-- table; a cup has rounds and a bracket). `slug` is the ESPN league code.
CREATE TABLE IF NOT EXISTS competitions (
    competition_id  INTEGER PRIMARY KEY,   -- our own stable id (hash of slug)
    slug            TEXT NOT NULL UNIQUE,  -- 'fifa.world', 'uefa.euro', 'eng.1'
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,         -- 'international_cup' | 'club_cup' | 'league'
    confederation   TEXT                   -- 'FIFA' | 'UEFA' | domestic country code
);

-- One edition/season of a competition: World Cup 2022, Premier League 2023/24.
CREATE TABLE IF NOT EXISTS seasons (
    season_id       INTEGER PRIMARY KEY,   -- competition_id * 10000 + year
    competition_id  INTEGER NOT NULL,
    year            INTEGER NOT NULL,      -- 2022, or the *start* year for leagues
    name            TEXT,                  -- '2022' / '2023-24'
    host            TEXT,                  -- host nation(s) for a tournament
    start_date      TEXT,
    end_date        TEXT,
    UNIQUE (competition_id, year)
);

CREATE TABLE IF NOT EXISTS teams (
    team_id         INTEGER PRIMARY KEY,   -- ESPN team id
    name            TEXT,
    abbreviation    TEXT,
    country         TEXT                   -- for clubs; equals name for national teams
);

CREATE TABLE IF NOT EXISTS players (
    player_id       INTEGER PRIMARY KEY,   -- ESPN athlete id
    name            TEXT,
    position        TEXT                   -- last seen position (dimension, may drift)
);

-- The spine. One row per match. Penalty-shootout columns are NULL unless the tie
-- went to penalties; halftime score is carried when ESPN provides it.
CREATE TABLE IF NOT EXISTS matches (
    match_id        INTEGER PRIMARY KEY,   -- ESPN event id
    competition_id  INTEGER NOT NULL,
    season_id       INTEGER NOT NULL,
    date            TEXT,                  -- ISO date (UTC) of kickoff
    round           TEXT,                  -- 'Group A' / 'Round of 16' / 'Final' / matchday
    venue           TEXT,
    city            TEXT,
    country         TEXT,
    neutral         INTEGER,               -- 1 if a neutral venue (all WC group games)
    status          TEXT,                  -- 'Full Time' / 'Postponed' / ...
    home_team_id    INTEGER,
    away_team_id    INTEGER,
    home_score      INTEGER,               -- goals in regulation+ET (excludes shootout)
    away_score      INTEGER,
    home_ht         INTEGER,               -- halftime goals (NULL if unknown)
    away_ht         INTEGER,
    home_pens       INTEGER,               -- shootout goals (NULL if no shootout)
    away_pens       INTEGER,
    attendance      INTEGER,
    outcome         TEXT                   -- derived: 'H' | 'A' | 'D' (see parse.match_outcome)
);

-- Who was on the pitch. starter=0 means a substitute (whether or not they came
-- on). One row per (match, player).
CREATE TABLE IF NOT EXISTS lineups (
    match_id        INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    player_id       INTEGER NOT NULL,
    starter         INTEGER,               -- 1 starting XI, 0 bench
    position        TEXT,
    jersey          INTEGER,
    PRIMARY KEY (match_id, player_id)
);

-- On-pitch events: goals, own goals, penalties, cards, substitutions. `minute`
-- is the match minute; `minute_extra` is stoppage time (the +X in 90+3). The
-- normalized `type` is what queries group on; `detail` keeps ESPN's raw text.
CREATE TABLE IF NOT EXISTS match_events (
    match_id        INTEGER NOT NULL,
    seq             INTEGER NOT NULL,      -- order within the match (0-based)
    minute          INTEGER,
    minute_extra    INTEGER,
    type            TEXT,                  -- 'Goal' | 'Own Goal' | 'Penalty' | 'Yellow Card' | 'Red Card' | 'Substitution'
    team_id         INTEGER,
    player_id       INTEGER,               -- scorer / carded player / player coming ON
    assist_player_id INTEGER,              -- assister, or player going OFF for a sub
    detail          TEXT,                  -- ESPN's raw event text (audit trail)
    PRIMARY KEY (match_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_matches_comp     ON matches(competition_id);
CREATE INDEX IF NOT EXISTS idx_matches_season   ON matches(season_id);
CREATE INDEX IF NOT EXISTS idx_matches_date     ON matches(date);
CREATE INDEX IF NOT EXISTS idx_matches_home     ON matches(home_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_away     ON matches(away_team_id);
CREATE INDEX IF NOT EXISTS idx_lineups_player   ON lineups(player_id);
CREATE INDEX IF NOT EXISTS idx_lineups_match    ON lineups(match_id);
CREATE INDEX IF NOT EXISTS idx_events_match     ON match_events(match_id);
CREATE INDEX IF NOT EXISTS idx_events_player    ON match_events(player_id);
CREATE INDEX IF NOT EXISTS idx_events_type      ON match_events(type);
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


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict], *,
            on_conflict: str = "REPLACE") -> int:
    """INSERT OR <on_conflict> a batch of dict rows. Columns come from the first
    row, so every row in a batch must share the same keys (the parser guarantees
    it). on_conflict='IGNORE' is used for dimension rows we don't want a cheap
    tier to clobber (e.g. a player's position set by the lineup tier).
    """
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT OR {on_conflict} INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
    return len(rows)


def load_competition(conn: sqlite3.Connection, competition: dict, season: dict) -> None:
    """Upsert the competition + season dimension rows (cheap, idempotent)."""
    _insert(conn, "competitions", [competition])
    _insert(conn, "seasons", [season])
    conn.commit()


def load_matches(conn: sqlite3.Connection, teams: list[dict], matches: list[dict]) -> int:
    """Upsert the teams referenced by a batch of matches, then the matches."""
    # de-dup teams by id within the batch
    seen: dict[int, dict] = {t["team_id"]: t for t in teams}
    _insert(conn, "teams", list(seen.values()))
    n = _insert(conn, "matches", matches)
    conn.commit()
    return n


def load_match_detail(conn: sqlite3.Connection, players: list[dict],
                      lineups: list[dict], events: list[dict]) -> None:
    """Upsert player dimension rows, lineups, and events.

    Players use INSERT OR IGNORE: the event tier only knows (id, name), so it
    must not overwrite a richer row the lineup tier may have written (which adds
    `position`). Lineups and events are REPLACE — they're the source of truth for
    their own keys and re-running must converge.
    """
    seen: dict[int, dict] = {p["player_id"]: p for p in players}
    _insert(conn, "players", list(seen.values()), on_conflict="IGNORE")
    _insert(conn, "lineups", lineups)
    _insert(conn, "match_events", events)
    conn.commit()


def loaded_match_ids(conn: sqlite3.Connection, season_id: int) -> set[int]:
    """Match ids already present for a season (used to skip finished editions)."""
    return {r[0] for r in conn.execute(
        "SELECT match_id FROM matches WHERE season_id = ?", (season_id,))}


def matches_missing_detail(conn: sqlite3.Connection, season_id: int) -> list[int]:
    """Match ids in a season that have no lineup rows yet (need a summary pull)."""
    return [r[0] for r in conn.execute(
        """SELECT m.match_id FROM matches m
           WHERE m.season_id = ?
             AND NOT EXISTS (SELECT 1 FROM lineups l WHERE l.match_id = m.match_id)
           ORDER BY m.date""", (season_id,))]


def summary(conn: sqlite3.Connection) -> dict:
    q = conn.execute
    return {
        "competitions": q("SELECT COUNT(*) FROM competitions").fetchone()[0],
        "seasons": q("SELECT COUNT(*) FROM seasons").fetchone()[0],
        "matches": q("SELECT COUNT(*) FROM matches").fetchone()[0],
        "teams": q("SELECT COUNT(*) FROM teams").fetchone()[0],
        "lineups": q("SELECT COUNT(*) FROM lineups").fetchone()[0],
        "events": q("SELECT COUNT(*) FROM match_events").fetchone()[0],
    }
