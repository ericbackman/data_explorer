"""
NHL Play-by-Play Backfill (Step 2)
==================================
Fills the wide `plays` table for every game in nhl.db flagged
pbp_loaded = 0, then flips the flag. Safe to interrupt and re-run.

Coordinates (x/y/zone) and situation_code only exist from 2009-10 onward;
earlier games still load their goal/penalty/shot events with those columns
NULL (see nhl_api.PBP_FIRST_COORD_SEASON).

Run build_nhl_db.py first (it creates the games index + plays schema).

Usage:
    python fetch_nhl_pbp.py                  # backfill everything outstanding
    python fetch_nhl_pbp.py --limit 25       # smoke-test on 25 games
    python fetch_nhl_pbp.py --season 20232024
    python fetch_nhl_pbp.py --coords-only    # only seasons that have coordinates
    python fetch_nhl_pbp.py --dry-run
"""

import time
import logging
import sqlite3
import argparse
import pathlib

from . import api as nhl_api
from .build import ensure_pbp_schema

log = logging.getLogger("fetch_nhl_pbp")

DB_PATH = pathlib.Path(__file__).parent / "data" / "nhl.db"
DEFAULT_SLEEP = 0.4

PLAYS_INSERT = """
INSERT OR IGNORE INTO plays
 (game_id, sort_order, event_id, period, period_type, time_in_period,
  event_type, event_team_id, x_coord, y_coord, zone_code, shot_type,
  shooter_id, goalie_id, scorer_id, assist1_id, assist2_id,
  faceoff_winner_id, faceoff_loser_id, hitter_id, hittee_id, blocker_id,
  penalty_on_id, penalty_drawn_id, penalty_type, penalty_minutes,
  player_id, situation_code)
VALUES
 (:game_id, :sort_order, :event_id, :period, :period_type, :time_in_period,
  :event_type, :event_team_id, :x_coord, :y_coord, :zone_code, :shot_type,
  :shooter_id, :goalie_id, :scorer_id, :assist1_id, :assist2_id,
  :faceoff_winner_id, :faceoff_loser_id, :hitter_id, :hittee_id, :blocker_id,
  :penalty_on_id, :penalty_drawn_id, :penalty_type, :penalty_minutes,
  :player_id, :situation_code)
"""


def outstanding_games(conn: sqlite3.Connection, season: int | None,
                      coords_only: bool, limit: int) -> list[str]:
    sql = "SELECT game_id FROM games WHERE pbp_loaded = 0"
    params: list = []
    if season:
        sql += " AND season = ?"
        params.append(str(season))
    if coords_only:
        sql += " AND CAST(season AS INTEGER) >= ?"
        params.append(nhl_api.PBP_FIRST_COORD_SEASON)
    sql += " ORDER BY date"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill NHL play-by-play into nhl.db")
    parser.add_argument("--season", type=int, default=None, help="Only this season (e.g. 20232024)")
    parser.add_argument("--coords-only", action="store_true",
                        help="Skip pre-2009-10 games (which have no coordinates)")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N games (0 = all)")
    parser.add_argument("--batch-size", type=int, default=100, help="Commit every N games")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="Seconds between requests")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fetched, then exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH.name} not found. Run build_nhl_db.py first.")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")   # wait, don't fail, if DB is busy

    try:
        ensure_pbp_schema(conn)
        todo = outstanding_games(conn, args.season, args.coords_only, args.limit)
        eta_min = len(todo) * args.sleep / 60
        log.info("Outstanding games: %d  (ETA ~%.0f min at %.2fs/req)",
                 len(todo), eta_min, args.sleep)
        if args.dry_run or not todo:
            return

        session = nhl_api.make_session()
        fetched = failed = plays_total = 0
        for i, game_id in enumerate(todo, 1):
            try:
                raw = nhl_api.fetch_pbp(session, game_id)
                rows = nhl_api.parse_pbp(raw)
                conn.executemany(PLAYS_INSERT, rows)
                conn.execute("UPDATE games SET pbp_loaded = 1 WHERE game_id = ?", (game_id,))
                fetched += 1
                plays_total += len(rows)
            except Exception:  # noqa: BLE001 -- log, leave flag=0 so it retries
                log.exception("  failed: %s", game_id)
                failed += 1

            if fetched and fetched % args.batch_size == 0:
                conn.commit()
                log.info("  [%d/%d] %d games, %d plays (%d failed)",
                         i, len(todo), fetched, plays_total, failed)
            time.sleep(args.sleep)

        conn.commit()
        log.info("Done. Fetched %d games, %d plays, %d failed.", fetched, plays_total, failed)
    finally:
        conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    log.info("nhl.db is now %.1f MB", size_mb)


if __name__ == "__main__":
    main()
