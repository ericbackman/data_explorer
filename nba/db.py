"""SQLite schema + idempotent loaders for the NBA database.

Raw facts only. Re-running the scraper must be safe and must *update* changing
rows (a live game goes partial -> final), so fact tables use INSERT OR REPLACE
keyed on the natural primary key, NOT INSERT OR IGNORE.
"""

from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY,
    abbreviation TEXT,
    name TEXT
);

CREATE TABLE IF NOT EXISTS players (
    player_id INTEGER PRIMARY KEY,
    player_name TEXT
);

CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    season TEXT,
    season_type TEXT,
    game_date TEXT,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_pts INTEGER,
    away_pts INTEGER
);

CREATE TABLE IF NOT EXISTS team_game (
    game_id TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    season TEXT, season_type TEXT, game_date TEXT, matchup TEXT, wl TEXT,
    min REAL, fgm INTEGER, fga INTEGER, fg_pct REAL,
    fg3m INTEGER, fg3a INTEGER, fg3_pct REAL,
    ftm INTEGER, fta INTEGER, ft_pct REAL,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER,
    blk INTEGER, tov INTEGER, pf INTEGER, pts INTEGER, plus_minus REAL,
    PRIMARY KEY (game_id, team_id)
);

CREATE TABLE IF NOT EXISTS player_game (
    game_id TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    team_id INTEGER,
    season TEXT, season_type TEXT, game_date TEXT, matchup TEXT, wl TEXT,
    min REAL, fgm INTEGER, fga INTEGER, fg_pct REAL,
    fg3m INTEGER, fg3a INTEGER, fg3_pct REAL,
    ftm INTEGER, fta INTEGER, ft_pct REAL,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER,
    blk INTEGER, tov INTEGER, pf INTEGER, pts INTEGER, plus_minus REAL,
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS drafts (
    season INTEGER NOT NULL,
    overall_pick INTEGER NOT NULL,
    round_number INTEGER,
    round_pick INTEGER,
    person_id INTEGER,
    player_name TEXT,
    team_id INTEGER,
    team_city TEXT,
    team_name TEXT,
    team_abbreviation TEXT,
    organization TEXT,
    organization_type TEXT,
    draft_type TEXT,
    PRIMARY KEY (season, overall_pick)
);

CREATE INDEX IF NOT EXISTS idx_pg_player  ON player_game(player_id);
CREATE INDEX IF NOT EXISTS idx_pg_season  ON player_game(season);
CREATE INDEX IF NOT EXISTS idx_pg_date    ON player_game(game_date);
CREATE INDEX IF NOT EXISTS idx_tg_team    ON team_game(team_id);
CREATE INDEX IF NOT EXISTS idx_tg_season  ON team_game(season);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season);
CREATE INDEX IF NOT EXISTS idx_games_date   ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_drafts_season ON drafts(season);

CREATE TABLE IF NOT EXISTS player_awards (
    person_id INTEGER NOT NULL,
    season TEXT,                 -- '1999-00'; NULL for career/one-off honors
    description TEXT NOT NULL,    -- 'NBA All-Star', 'All-NBA', 'NBA Champion', ...
    team_number INTEGER          -- All-NBA / All-Defensive team (1/2/3), else NULL
);
CREATE INDEX IF NOT EXISTS idx_awards_person ON player_awards(person_id);

-- One row per person once their awards have been fetched, so a resumable scrape
-- skips players it already checked even when they earned zero awards.
CREATE TABLE IF NOT EXISTS awards_fetched (person_id INTEGER PRIMARY KEY);

-- Naismith Hall of Fame inductions (see nba.hof_scrape).
--
-- WHY THIS IS NOT IN player_awards: stats.nba.com's PlayerAwards endpoint stops
-- carrying "Hall of Fame Inductee" after the 2018 class — every inductee from
-- 2019 on (Kobe, Duncan, Garnett, Dirk, Wade, Gasol, ...) is absent upstream, so
-- no amount of re-scraping awards can produce them. This table is the separate,
-- HOF-specific source; consumers UNION it into their awards view (the same shape
-- MLB uses via its own `hall_of_fame` table).
--
-- Keeping it out of player_awards is also load-safety: `load_player_awards` is
-- delete-then-insert per person, so rows injected there would be silently wiped
-- by the next `python -m nba.awards_scrape` run.
--
-- player_id is NULL for inductees with no NBA playing career (WNBA players,
-- Globetrotters, pre-NBA college stars). Those rows are still kept so the source
-- is represented faithfully and the unmatched set stays inspectable.
CREATE TABLE IF NOT EXISTS hall_of_fame (
    inductee_name TEXT NOT NULL,
    inducted_year INTEGER NOT NULL,
    player_id INTEGER,
    PRIMARY KEY (inductee_name, inducted_year)
);
CREATE INDEX IF NOT EXISTS idx_hof_player ON hall_of_fame(player_id);
"""

# Exact column order each fact table is written in (a parse row may carry extra
# keys like team_name; we project to just these before inserting).
PLAYER_GAME_COLS = [
    "game_id", "player_id", "team_id", "season", "season_type", "game_date",
    "matchup", "wl", "min", "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
    "ftm", "fta", "ft_pct", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov",
    "pf", "pts", "plus_minus",
]
TEAM_GAME_COLS = [c for c in PLAYER_GAME_COLS if c not in ("player_id",)]
GAME_COLS = [
    "game_id", "season", "season_type", "game_date",
    "home_team_id", "away_team_id", "home_pts", "away_pts",
]
DRAFT_COLS = [
    "season", "overall_pick", "round_number", "round_pick", "person_id",
    "player_name", "team_id", "team_city", "team_name", "team_abbreviation",
    "organization", "organization_type", "draft_type",
]
AWARD_COLS = ["person_id", "season", "description", "team_number"]


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _upsert(conn: sqlite3.Connection, table: str, cols: list[str], rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" * len(cols))
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)


def _load_dims(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Upsert the team (and, if present, player) dimension rows referenced."""
    teams = {r["team_id"]: (r.get("team_abbreviation"), r.get("team_name")) for r in rows}
    _upsert(conn, "teams", ["team_id", "abbreviation", "name"],
            [{"team_id": tid, "abbreviation": ab, "name": nm}
             for tid, (ab, nm) in teams.items()])
    if rows and "player_id" in rows[0]:
        players = {r["player_id"]: r.get("player_name") for r in rows}
        _upsert(conn, "players", ["player_id", "player_name"],
                [{"player_id": pid, "player_name": nm} for pid, nm in players.items()])


def load_player_game(conn: sqlite3.Connection, rows: list[dict]) -> int:
    _load_dims(conn, rows)
    return _upsert(conn, "player_game", PLAYER_GAME_COLS, rows)


def load_team_game(conn: sqlite3.Connection, rows: list[dict]) -> int:
    _load_dims(conn, rows)
    return _upsert(conn, "team_game", TEAM_GAME_COLS, rows)


def load_games(conn: sqlite3.Connection, rows: list[dict]) -> int:
    return _upsert(conn, "games", GAME_COLS, rows)


def load_drafts(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Upsert draft picks keyed on (season, overall_pick). Re-running is safe;
    a corrected name/team on a slot overwrites the old row rather than duplicating.
    """
    return _upsert(conn, "drafts", DRAFT_COLS, rows)


HOF_COLS = ["inductee_name", "inducted_year", "player_id"]


def load_hall_of_fame(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Replace the whole Hall of Fame table from one page scrape.

    Full-snapshot replace (not per-row upsert) because the source IS the whole
    list: a name corrected upstream should stop existing here rather than linger
    beside its correction. Refuses to wipe a populated table with nothing, so a
    silently-empty parse can't destroy good data.
    """
    if not rows:
        raise ValueError("refusing to replace hall_of_fame with 0 rows")
    conn.execute("DELETE FROM hall_of_fame")
    return _upsert(conn, "hall_of_fame", HOF_COLS, rows)


def load_player_awards(conn: sqlite3.Connection, person_id: int, rows: list[dict]) -> int:
    """Replace one player's award rows (delete-then-insert = idempotent per player),
    and mark him fetched so a resumable scrape skips him next time even with 0 awards."""
    conn.execute("DELETE FROM player_awards WHERE person_id = ?", (person_id,))
    n = _upsert(conn, "player_awards", AWARD_COLS, rows)
    conn.execute("INSERT OR REPLACE INTO awards_fetched (person_id) VALUES (?)", (person_id,))
    return n


def loaded_award_persons(conn: sqlite3.Connection) -> set[int]:
    """person_ids whose awards have already been fetched (earned some or none)."""
    return {r[0] for r in conn.execute("SELECT person_id FROM awards_fetched")}


def loaded_draft_seasons(conn: sqlite3.Connection) -> set[int]:
    """Draft years that already have at least one pick row."""
    return {r[0] for r in conn.execute("SELECT DISTINCT season FROM drafts")}


def loaded_seasons(conn: sqlite3.Connection) -> set[str]:
    """Seasons that already have at least one game row."""
    return {r[0] for r in conn.execute("SELECT DISTINCT season FROM games")}
