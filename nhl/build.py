"""
Build NHL SQLite Database (schema + game index)
================================================
Creates nhl.db with the boxscore schema and loads the *games* dimension
from the NHL master game index (one API call lists every game ever played).

This is the fast first step. The slow per-game boxscore backfill lives in
fetch_nhl_boxscores.py, which fills skater_boxscores / goalie_boxscores for
each game flagged here as not-yet-loaded.

Usage:
    python build_nhl_db.py                       # RTSS era (1997-98 -> now)
    python build_nhl_db.py --min-season 19171918 # all of NHL history
    python build_nhl_db.py --verify              # build + per-season counts
"""

import logging
import sqlite3
import argparse
import pathlib

from . import api as nhl_api

log = logging.getLogger("build_nhl_db")

DB_PATH = pathlib.Path(__file__).parent / "data" / "nhl.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS games (
    game_id         TEXT PRIMARY KEY,
    season          TEXT NOT NULL,        -- '19971998'
    game_type       INTEGER NOT NULL,     -- 2 regular, 3 playoff
    date            TEXT NOT NULL,        -- '1997-10-01'
    home_team_id    INTEGER NOT NULL,
    away_team_id    INTEGER NOT NULL,
    home_score      INTEGER,
    away_score      INTEGER,
    boxscore_loaded INTEGER NOT NULL DEFAULT 0,  -- Step 1 resumability flag
    pbp_loaded      INTEGER NOT NULL DEFAULT 0   -- Step 2 resumability flag
);

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY,
    abbrev  TEXT                          -- filled in during boxscore fetch
);

CREATE TABLE IF NOT EXISTS players (
    player_id     INTEGER PRIMARY KEY,
    name          TEXT,                   -- abbreviated 'L. Glendening'
    last_position TEXT
);

CREATE TABLE IF NOT EXISTS skater_boxscores (
    game_id          TEXT NOT NULL,
    player_id        INTEGER NOT NULL,
    team_id          INTEGER NOT NULL,
    position         TEXT,                -- C / L / R / D
    sweater          INTEGER,
    goals            INTEGER,
    assists          INTEGER,
    points           INTEGER,
    plus_minus       INTEGER,
    pim              INTEGER,
    sog              INTEGER,
    hits             INTEGER,
    blocked_shots    INTEGER,
    takeaways        INTEGER,
    giveaways        INTEGER,
    power_play_goals INTEGER,
    faceoff_pct      REAL,
    toi_seconds      INTEGER,
    shifts           INTEGER,
    PRIMARY KEY (game_id, player_id),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE TABLE IF NOT EXISTS goalie_boxscores (
    game_id          TEXT NOT NULL,
    player_id        INTEGER NOT NULL,
    team_id          INTEGER NOT NULL,
    sweater          INTEGER,
    starter          INTEGER,             -- 0 / 1
    decision         TEXT,                -- W / L / T / O / NULL
    saves            INTEGER,
    shots_against    INTEGER,
    goals_against    INTEGER,
    save_pct         REAL,
    pim              INTEGER,
    toi_seconds      INTEGER,
    es_shots_against INTEGER,
    es_goals_against INTEGER,
    pp_shots_against INTEGER,
    pp_goals_against INTEGER,
    sh_shots_against INTEGER,
    sh_goals_against INTEGER,
    PRIMARY KEY (game_id, player_id),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

-- Per-team, per-game line (score + shots) straight from the boxscore.
CREATE TABLE IF NOT EXISTS team_game (
    game_id TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    is_home INTEGER NOT NULL,
    score   INTEGER,
    sog     INTEGER,
    PRIMARY KEY (game_id, team_id),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

-- ── Indexes ──────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_games_season      ON games(season);
CREATE INDEX IF NOT EXISTS idx_games_loaded      ON games(boxscore_loaded);
CREATE INDEX IF NOT EXISTS idx_sb_player         ON skater_boxscores(player_id);
CREATE INDEX IF NOT EXISTS idx_sb_game           ON skater_boxscores(game_id);
CREATE INDEX IF NOT EXISTS idx_sb_team           ON skater_boxscores(team_id);
CREATE INDEX IF NOT EXISTS idx_gb_player         ON goalie_boxscores(player_id);
CREATE INDEX IF NOT EXISTS idx_gb_game           ON goalie_boxscores(game_id);
CREATE INDEX IF NOT EXISTS idx_tg_game           ON team_game(game_id);
"""

# Step 2 schema, kept separate so fetch_nhl_pbp.py can apply it standalone.
# Wide plays table: every event is one row, role columns nullable per type.
# Coordinates + situation_code are NULL for pre-2009-10 games (no API data).
PBP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plays (
    game_id           TEXT NOT NULL,
    sort_order        INTEGER NOT NULL,    -- chronological index within game
    event_id          INTEGER,
    period            INTEGER,
    period_type       TEXT,                -- REG / OT / SO
    time_in_period    TEXT,                -- 'MM:SS'
    event_type        TEXT,                -- faceoff, shot-on-goal, hit, goal...
    event_team_id     INTEGER,
    x_coord           INTEGER,             -- NULL before 2009-10
    y_coord           INTEGER,             -- NULL before 2009-10
    zone_code         TEXT,                -- O / N / D
    shot_type         TEXT,
    shooter_id        INTEGER,             -- shot-on-goal / missed / blocked
    goalie_id         INTEGER,
    scorer_id         INTEGER,             -- goal
    assist1_id        INTEGER,
    assist2_id        INTEGER,
    faceoff_winner_id INTEGER,             -- faceoff
    faceoff_loser_id  INTEGER,
    hitter_id         INTEGER,             -- hit
    hittee_id         INTEGER,
    blocker_id        INTEGER,             -- blocked-shot
    penalty_on_id     INTEGER,             -- penalty
    penalty_drawn_id  INTEGER,
    penalty_type      TEXT,
    penalty_minutes   INTEGER,
    player_id         INTEGER,             -- giveaway / takeaway actor
    situation_code    TEXT,                -- strength state, NULL before 2009-10
    PRIMARY KEY (game_id, sort_order),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE INDEX IF NOT EXISTS idx_plays_game    ON plays(game_id);
CREATE INDEX IF NOT EXISTS idx_plays_type    ON plays(event_type);
CREATE INDEX IF NOT EXISTS idx_plays_shooter ON plays(shooter_id);
CREATE INDEX IF NOT EXISTS idx_plays_scorer  ON plays(scorer_id);
CREATE INDEX IF NOT EXISTS idx_games_pbp     ON games(pbp_loaded);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    ensure_pbp_schema(conn)
    conn.commit()


def ensure_pbp_schema(conn: sqlite3.Connection) -> None:
    """Create the plays table and add games.pbp_loaded if an older DB lacks it.
    Safe to call repeatedly; used by both this script and fetch_nhl_pbp.py.

    The column is added BEFORE running PBP_SCHEMA_SQL, because that script
    creates an index on games(pbp_loaded) which would fail on an older DB."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
    if "pbp_loaded" not in cols:
        conn.execute("ALTER TABLE games ADD COLUMN pbp_loaded INTEGER NOT NULL DEFAULT 0")
    conn.executescript(PBP_SCHEMA_SQL)
    conn.commit()


def load_games(conn: sqlite3.Connection, games: list[dict]) -> int:
    """Upsert the games dimension. Existing rows keep their boxscore_loaded
    flag (so re-running build never forces a re-fetch); new rows default to 0."""
    rows = [
        (
            str(g["id"]),
            str(g["season"]),
            g["gameType"],
            g["gameDate"],
            g["homeTeamId"],
            g["visitingTeamId"],
            g.get("homeScore"),
            g.get("visitingScore"),
        )
        for g in games
    ]
    conn.executemany(
        """INSERT INTO games
           (game_id, season, game_type, date,
            home_team_id, away_team_id, home_score, away_score)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(game_id) DO UPDATE SET
             home_score = excluded.home_score,
             away_score = excluded.away_score""",
        rows,
    )
    # Make sure every referenced team id exists (abbrev filled at fetch time).
    team_ids = {g["homeTeamId"] for g in games} | {g["visitingTeamId"] for g in games}
    conn.executemany(
        "INSERT OR IGNORE INTO teams (team_id) VALUES (?)",
        [(t,) for t in team_ids],
    )
    conn.commit()
    return len(rows)


def verify(conn: sqlite3.Connection) -> None:
    log.info("Games per season (newest 10):")
    for season, gtype_2, gtype_3 in conn.execute(
        """SELECT season,
                  SUM(game_type = 2) AS regular,
                  SUM(game_type = 3) AS playoff
           FROM games GROUP BY season ORDER BY season DESC LIMIT 10"""
    ):
        log.info("  %s: %s regular, %s playoff", season, gtype_2, gtype_3)

    total, loaded = conn.execute(
        "SELECT COUNT(*), SUM(boxscore_loaded) FROM games"
    ).fetchone()
    log.info("Total games: %d  |  boxscores loaded: %d", total, loaded or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NHL SQLite DB (schema + game index)")
    parser.add_argument("--min-season", type=int, default=nhl_api.RTSS_FIRST_SEASON,
                        help="Earliest season as 8-digit int (default 19971998, the RTSS era)")
    parser.add_argument("--verify", action="store_true", help="Print per-season counts after build")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    session = nhl_api.make_session()
    log.info("Fetching master game index...")
    raw = nhl_api.fetch_game_index(session)
    games = nhl_api.select_games(raw, args.min_season)
    log.info("Selected %d final regular+playoff games since season %d",
             len(games), args.min_season)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        init_schema(conn)
        n = load_games(conn, games)
        conn.execute("ANALYZE")
        conn.commit()
        log.info("Loaded %d games into %s", n, DB_PATH.name)
        if args.verify:
            verify(conn)
    finally:
        conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    log.info("Done. %s (%.2f MB). Next: python fetch_nhl_boxscores.py", DB_PATH.name, size_mb)


if __name__ == "__main__":
    main()
