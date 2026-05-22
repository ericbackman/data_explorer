"""
Build Playoff Comebacks SQLite Database
========================================
Reads the playoff max-deficit CSV and creates a well-indexed SQLite
database optimized for playoff comeback analysis queries.

Extends the regular season schema with playoff_round and series_id
columns, plus playoff-specific views (round splits, Finals comebacks,
series comeback leaders).

Usage:
    python build_playoff_comebacks_db.py                # build from CSV
    python build_playoff_comebacks_db.py --verify       # build + verify
"""

import sqlite3
import argparse
import pathlib
import pandas as pd

DB_PATH = pathlib.Path("nba_playoff_comebacks.db")
CSV_PATH = pathlib.Path("playoff_max_deficit_situations.csv")


def create_schema(conn: sqlite3.Connection):
    """Create tables, indexes, and views."""
    cur = conn.cursor()

    cur.executescript("""
    -- ── Core tables ─────────────────────────────────────────────────────

    CREATE TABLE IF NOT EXISTS games (
        game_id         TEXT PRIMARY KEY,
        date            TEXT NOT NULL,
        season          TEXT NOT NULL,
        playoff_round   TEXT NOT NULL,
        series_id       TEXT NOT NULL,
        home_team       TEXT NOT NULL,
        away_team       TEXT NOT NULL,
        home_final      INTEGER NOT NULL,
        away_final      INTEGER NOT NULL,
        lead_changes    INTEGER,
        times_tied      INTEGER
    );

    CREATE TABLE IF NOT EXISTS team_game_deficits (
        game_id             TEXT NOT NULL,
        team                TEXT NOT NULL,
        team_id             INTEGER,
        opponent            TEXT NOT NULL,
        location            TEXT NOT NULL CHECK (location IN ('home', 'away')),
        season              TEXT NOT NULL,
        playoff_round       TEXT NOT NULL,
        series_id           TEXT NOT NULL,
        date                TEXT NOT NULL,
        max_deficit         INTEGER NOT NULL,
        own_biggest_lead    INTEGER NOT NULL,
        won                 INTEGER NOT NULL,     -- 0 or 1
        came_back           INTEGER NOT NULL,     -- 0 or 1
        final_margin        INTEGER NOT NULL,
        biggest_run         INTEGER,
        bench_pts           INTEGER,
        PRIMARY KEY (game_id, team),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    );

    -- ── Indexes ─────────────────────────────────────────────────────────

    CREATE INDEX IF NOT EXISTS idx_tgd_team_deficit
        ON team_game_deficits(team, max_deficit);

    CREATE INDEX IF NOT EXISTS idx_tgd_season
        ON team_game_deficits(season);

    CREATE INDEX IF NOT EXISTS idx_tgd_deficit_won
        ON team_game_deficits(max_deficit, won);

    CREATE INDEX IF NOT EXISTS idx_tgd_team_location
        ON team_game_deficits(team, location);

    CREATE INDEX IF NOT EXISTS idx_tgd_round
        ON team_game_deficits(playoff_round);

    CREATE INDEX IF NOT EXISTS idx_tgd_series
        ON team_game_deficits(series_id);

    CREATE INDEX IF NOT EXISTS idx_games_season_date
        ON games(season, date);

    CREATE INDEX IF NOT EXISTS idx_games_round
        ON games(playoff_round);

    -- ── Views ───────────────────────────────────────────────────────────

    -- League-wide comeback rates by deficit threshold
    CREATE VIEW IF NOT EXISTS v_league_rates AS
    SELECT
        threshold,
        COUNT(*) as situations,
        SUM(won) as comebacks,
        ROUND(CAST(SUM(won) AS REAL) / COUNT(*) * 100, 1) as comeback_pct,
        ROUND(1.0 / (CAST(SUM(won) AS REAL) / COUNT(*)), 1) as breakeven_odds
    FROM team_game_deficits,
         (SELECT 10 as threshold UNION SELECT 12 UNION SELECT 15
          UNION SELECT 18 UNION SELECT 20 UNION SELECT 25) thresholds
    WHERE max_deficit >= threshold
    GROUP BY threshold
    ORDER BY threshold;

    -- Comeback rates by playoff round (15+ deficit)
    CREATE VIEW IF NOT EXISTS v_round_rates AS
    SELECT
        playoff_round,
        COUNT(*) as total_games,
        SUM(CASE WHEN max_deficit >= 15 THEN 1 ELSE 0 END) as down_15_plus,
        SUM(CASE WHEN max_deficit >= 15 AND won = 1 THEN 1 ELSE 0 END) as comebacks_15,
        ROUND(CAST(SUM(CASE WHEN max_deficit >= 15 AND won = 1 THEN 1 ELSE 0 END) AS REAL)
              / NULLIF(SUM(CASE WHEN max_deficit >= 15 THEN 1 ELSE 0 END), 0) * 100, 1)
              as comeback_pct_15,
        SUM(CASE WHEN max_deficit >= 20 THEN 1 ELSE 0 END) as down_20_plus,
        SUM(CASE WHEN max_deficit >= 20 AND won = 1 THEN 1 ELSE 0 END) as comebacks_20
    FROM team_game_deficits
    GROUP BY playoff_round
    ORDER BY CASE playoff_round
        WHEN 'First Round' THEN 1
        WHEN 'Conference Semis' THEN 2
        WHEN 'Conference Finals' THEN 3
        WHEN 'Finals' THEN 4
        ELSE 5 END;

    -- Team comeback rates at 15+ threshold
    CREATE VIEW IF NOT EXISTS v_comeback_rates_15 AS
    SELECT
        team,
        COUNT(*) as times_down,
        SUM(won) as comebacks,
        ROUND(CAST(SUM(won) AS REAL) / COUNT(*) * 100, 1) as comeback_pct,
        ROUND(AVG(max_deficit), 1) as avg_deficit,
        ROUND(AVG(final_margin), 1) as avg_final_margin,
        SUM(CASE WHEN location = 'home' THEN 1 ELSE 0 END) as home_games
    FROM team_game_deficits
    WHERE max_deficit >= 15
    GROUP BY team
    HAVING COUNT(*) >= 3
    ORDER BY comeback_pct DESC;

    -- Comeback rates by team + season
    CREATE VIEW IF NOT EXISTS v_comeback_by_season AS
    SELECT
        team,
        season,
        COUNT(*) as times_down,
        SUM(won) as comebacks,
        ROUND(CAST(SUM(won) AS REAL) / COUNT(*) * 100, 1) as comeback_pct
    FROM team_game_deficits
    WHERE max_deficit >= 15
    GROUP BY team, season
    ORDER BY team, season;

    -- Every big comeback (20+ max deficit, won)
    CREATE VIEW IF NOT EXISTS v_big_comebacks AS
    SELECT
        d.date,
        d.team,
        d.max_deficit,
        d.opponent,
        d.location,
        d.season,
        d.playoff_round,
        d.final_margin,
        g.home_final,
        g.away_final,
        g.lead_changes
    FROM team_game_deficits d
    JOIN games g ON d.game_id = g.game_id
    WHERE d.max_deficit >= 20 AND d.won = 1
    ORDER BY d.max_deficit DESC, d.date;

    -- Finals-only comebacks (10+ deficit)
    CREATE VIEW IF NOT EXISTS v_finals_comebacks AS
    SELECT
        d.date,
        d.team,
        d.max_deficit,
        d.opponent,
        d.season,
        d.final_margin,
        g.home_final,
        g.away_final
    FROM team_game_deficits d
    JOIN games g ON d.game_id = g.game_id
    WHERE d.playoff_round = 'Finals' AND d.max_deficit >= 10 AND d.won = 1
    ORDER BY d.max_deficit DESC;

    -- Home vs away comeback splits
    CREATE VIEW IF NOT EXISTS v_home_away_splits AS
    SELECT
        team,
        location,
        COUNT(*) as times_down,
        SUM(won) as comebacks,
        ROUND(CAST(SUM(won) AS REAL) / COUNT(*) * 100, 1) as comeback_pct
    FROM team_game_deficits
    WHERE max_deficit >= 15
    GROUP BY team, location
    HAVING COUNT(*) >= 2
    ORDER BY team, location;

    -- Era analysis: decade-level comeback trends
    CREATE VIEW IF NOT EXISTS v_era_trends AS
    SELECT
        CASE
            WHEN CAST(SUBSTR(season, 1, 4) AS INTEGER) < 2000 THEN '1996-2000'
            WHEN CAST(SUBSTR(season, 1, 4) AS INTEGER) < 2005 THEN '2000-2005'
            WHEN CAST(SUBSTR(season, 1, 4) AS INTEGER) < 2010 THEN '2005-2010'
            WHEN CAST(SUBSTR(season, 1, 4) AS INTEGER) < 2015 THEN '2010-2015'
            WHEN CAST(SUBSTR(season, 1, 4) AS INTEGER) < 2020 THEN '2015-2020'
            ELSE '2020-2026'
        END as era,
        COUNT(*) as situations_15plus,
        SUM(won) as comebacks,
        ROUND(CAST(SUM(won) AS REAL) / COUNT(*) * 100, 1) as comeback_pct
    FROM team_game_deficits
    WHERE max_deficit >= 15
    GROUP BY era
    ORDER BY era;

    -- Series comeback leaders: teams that faced multiple big deficits in one series
    CREATE VIEW IF NOT EXISTS v_series_comeback_leaders AS
    SELECT
        team,
        series_id,
        playoff_round,
        season,
        opponent,
        COUNT(*) as games_down_15,
        SUM(won) as comebacks,
        MAX(max_deficit) as biggest_deficit_faced,
        MAX(CASE WHEN won = 1 THEN max_deficit ELSE 0 END) as biggest_comeback
    FROM team_game_deficits
    WHERE max_deficit >= 15
    GROUP BY team, series_id
    HAVING COUNT(*) >= 2
    ORDER BY comebacks DESC, biggest_comeback DESC;
    """)

    conn.commit()


def load_data(conn: sqlite3.Connection):
    """Load CSV into the database tables."""
    df = pd.read_csv(CSV_PATH)
    print(f"  Loaded {len(df)} rows from {CSV_PATH}")

    # ── Games table (deduplicate: one row per game) ──────────────────────
    games = (
        df.groupby("game_id")
        .first()
        .reset_index()[["game_id", "date", "season", "playoff_round", "series_id",
                         "home_team", "away_team", "home_final", "away_final",
                         "lead_changes", "times_tied"]]
    )
    games["game_id"] = games["game_id"].astype(str).str.zfill(10)
    games.to_sql("games", conn, if_exists="replace", index=False)
    print(f"  Inserted {len(games)} games")

    # ── Team game deficits table ─────────────────────────────────────────
    tgd = df[["game_id", "team", "team_id", "opponent", "location", "season",
              "playoff_round", "series_id", "date", "max_deficit", "own_biggest_lead",
              "won", "came_back", "final_margin", "biggest_run", "bench_pts"]].copy()
    tgd["game_id"] = tgd["game_id"].astype(str).str.zfill(10)
    tgd["won"] = tgd["won"].astype(int)
    tgd["came_back"] = tgd["came_back"].astype(int)
    tgd.to_sql("team_game_deficits", conn, if_exists="replace", index=False)
    print(f"  Inserted {len(tgd)} team-game deficit rows")


def verify(conn: sqlite3.Connection):
    """Run sample queries to validate the database."""
    cur = conn.cursor()

    print("\n-- League-wide playoff comeback rates --")
    for row in cur.execute("SELECT * FROM v_league_rates"):
        print(f"  {row[0]}+ pts: {row[1]} situations, {row[2]} comebacks, "
              f"{row[3]}%, breakeven {row[4]}:1")

    print("\n-- Comeback rates by playoff round (15+) --")
    for row in cur.execute("SELECT * FROM v_round_rates"):
        print(f"  {row[0]}: {row[2]} down 15+, {row[3]} comebacks ({row[4]}%)")

    print("\n-- Top 10 playoff comeback teams (15+) --")
    for row in cur.execute("SELECT * FROM v_comeback_rates_15 LIMIT 10"):
        print(f"  {row[0]}: {row[2]}/{row[1]} ({row[3]}%)")

    print("\n-- Top 5 biggest playoff comebacks --")
    for row in cur.execute("SELECT * FROM v_big_comebacks LIMIT 5"):
        print(f"  {row[0]} {row[1]} came back from {row[2]} vs {row[3]} ({row[6]})")

    print("\n-- Finals comebacks (10+) --")
    for row in cur.execute("SELECT * FROM v_finals_comebacks LIMIT 10"):
        print(f"  {row[0]} {row[1]} came back from {row[2]} vs {row[3]}")

    print("\n-- Era trends --")
    for row in cur.execute("SELECT * FROM v_era_trends"):
        print(f"  {row[0]}: {row[2]}/{row[1]} ({row[3]}%)")

    print("\n-- Series comeback leaders --")
    for row in cur.execute("SELECT * FROM v_series_comeback_leaders LIMIT 10"):
        print(f"  {row[0]} vs {row[4]} ({row[3]} {row[2]}): "
              f"{row[6]} comebacks from 15+, biggest deficit {row[7]}")

    db_size = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\n-- Database size: {db_size:.2f} MB --")


def main():
    parser = argparse.ArgumentParser(description="Build NBA Playoff Comebacks SQLite DB")
    parser.add_argument("--verify", action="store_true",
                        help="Run verification queries after building")
    args = parser.parse_args()

    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found. Run fetch_playoff_data.py first.")
        return

    print(f"Building database: {DB_PATH}")

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    print("\n[1/3] Creating schema...")
    create_schema(conn)

    print("\n[2/3] Loading data...")
    load_data(conn)

    print("\n[3/3] Rebuilding indexes...")
    create_schema(conn)  # re-run to ensure indexes on fresh data
    conn.execute("ANALYZE")  # update query planner statistics
    conn.commit()

    if args.verify:
        verify(conn)

    conn.close()
    db_size = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nDone! {DB_PATH} ({db_size:.2f} MB)")


if __name__ == "__main__":
    main()
