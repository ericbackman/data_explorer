"""Seed the Neon serving tables from the local nba.db.

    . C:\\Users\\ericb\\Github\\.claude\\ops\\neon-url.ps1
    python seed.py                 # truncate + load
    python seed.py --counts-only   # what WOULD load, touching nothing

Reads nba.db read-only and aggregates 1.48M player-game rows down to ~37k
player-seasons. That reduction is the point: BigQuery keeps the raw grain for
scanning, Postgres keeps the serving grain for lookups, and Neon's 0.5 GB
free-plan ceiling (shared across all branches) only fits the latter.

Loads with COPY rather than executemany - one stream instead of 37k round trips.

Referential integrity is reconciled EXPLICITLY. `teams` has 45 modern franchises
while player_game reaches back to 1946, so some historical team_ids have no row
to point at. Those are set NULL and COUNTED, never dropped: losing a Hall of
Famer's season because his franchise folded in 1949 would be a silent data bug,
and the schema makes team_id nullable precisely to allow this.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sqlite3
import sys
from pathlib import Path

import psycopg

LOG = logging.getLogger("seed")

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "nba" / "data" / "nba.db"

TEAMS_SQL = "SELECT team_id, abbreviation, name FROM teams"
PLAYERS_SQL = "SELECT player_id, player_name FROM players"

# Totals per (player, season, season_type), plus the last team the player
# actually appeared for that season - which is the one a roster page wants,
# not MAX(team_id), which would be an arbitrary integer.
PLAYER_SEASON_SQL = """
WITH totals AS (
    SELECT player_id, season, season_type,
           COUNT(*)                    AS games,
           COALESCE(SUM(min), 0)       AS minutes,
           COALESCE(SUM(pts), 0)       AS pts,
           COALESCE(SUM(reb), 0)       AS reb,
           COALESCE(SUM(ast), 0)       AS ast
    FROM player_game
    GROUP BY player_id, season, season_type
),
last_team AS (
    SELECT player_id, season, season_type, team_id,
           ROW_NUMBER() OVER (
               PARTITION BY player_id, season, season_type
               ORDER BY game_date DESC
           ) AS rn
    FROM player_game
)
SELECT t.player_id, t.season, t.season_type, lt.team_id,
       t.games, t.minutes, t.pts, t.reb, t.ast
FROM totals AS t
JOIN last_team AS lt
  ON  lt.player_id   = t.player_id
  AND lt.season      = t.season
  AND lt.season_type = t.season_type
  AND lt.rn = 1
"""


def require_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "  local: . C:\\Users\\ericb\\Github\\.claude\\ops\\neon-url.ps1\n"
            "  CI:    supplied by the create-branch action"
        )
    return url


def copy_rows(cur: psycopg.Cursor, table: str, columns: list[str], rows: list[tuple]) -> None:
    with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(row)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--counts-only", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.db.exists():
        LOG.error("source database not found: %s", args.db)
        return 1

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        teams = con.execute(TEAMS_SQL).fetchall()
        players = con.execute(PLAYERS_SQL).fetchall()
        LOG.info("reading player_season aggregate (this scans 1.48M rows) ...")
        seasons = con.execute(PLAYER_SEASON_SQL).fetchall()
    finally:
        con.close()

    known_teams = {t[0] for t in teams}
    known_players = {p[0] for p in players}

    reconciled: list[tuple] = []
    orphan_team = 0
    orphan_player = 0
    for player_id, season, season_type, team_id, games, minutes, pts, reb, ast in seasons:
        if player_id not in known_players:
            # No players row to reference; the FK would reject it. Count and skip,
            # loudly - this should be zero and a nonzero value means nba.db has a
            # gap worth chasing, not something to paper over.
            orphan_player += 1
            continue
        if team_id is not None and team_id not in known_teams:
            team_id = None
            orphan_team += 1
        reconciled.append(
            (player_id, season, season_type, team_id, games, round(minutes or 0, 1), pts, reb, ast)
        )

    LOG.info("teams %s | players %s | player_season %s",
             f"{len(teams):,}", f"{len(players):,}", f"{len(reconciled):,}")
    if orphan_team:
        LOG.info("  %s season rows had a team_id with no teams row -> NULL (pre-modern franchises)",
                 f"{orphan_team:,}")
    if orphan_player:
        LOG.warning("  %s season rows had a player_id with no players row -> SKIPPED",
                    f"{orphan_player:,}")

    if args.counts_only:
        LOG.info("\n--counts-only: nothing written.")
        return 0

    with psycopg.connect(require_url()) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                # One transaction, so a failure leaves the previous contents
                # intact rather than an empty serving layer.
                cur.execute("TRUNCATE player_season, players, teams RESTART IDENTITY CASCADE")
                copy_rows(cur, "teams", ["team_id", "abbreviation", "name"], teams)
                copy_rows(cur, "players", ["player_id", "player_name"], players)
                copy_rows(
                    cur, "player_season",
                    ["player_id", "season", "season_type", "team_id",
                     "games", "minutes", "pts", "reb", "ast"],
                    reconciled,
                )
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM player_season")
            LOG.info("loaded. player_season now holds %s rows", f"{cur.fetchone()[0]:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
