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

CREATE INDEX IF NOT EXISTS idx_pg_player  ON player_game(player_id);
CREATE INDEX IF NOT EXISTS idx_pg_season  ON player_game(season);
CREATE INDEX IF NOT EXISTS idx_pg_date    ON player_game(game_date);
CREATE INDEX IF NOT EXISTS idx_tg_team    ON team_game(team_id);
CREATE INDEX IF NOT EXISTS idx_tg_season  ON team_game(season);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season);
CREATE INDEX IF NOT EXISTS idx_games_date   ON games(game_date);
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


def loaded_seasons(conn: sqlite3.Connection) -> set[str]:
    """Seasons that already have at least one game row."""
    return {r[0] for r in conn.execute("SELECT DISTINCT season FROM games")}
