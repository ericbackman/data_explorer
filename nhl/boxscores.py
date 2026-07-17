"""
NHL Boxscore Backfill
=====================
Fills skater_boxscores / goalie_boxscores / team_game for every game in
nhl.db flagged boxscore_loaded = 0, then flips the flag. Safe to interrupt
and re-run: it only fetches games it hasn't already stored.

Run build_nhl_db.py first to create the schema + games index.

Usage:
    python fetch_nhl_boxscores.py                 # backfill everything outstanding
    python fetch_nhl_boxscores.py --limit 25      # smoke-test on 25 games
    python fetch_nhl_boxscores.py --season 20232024
    python fetch_nhl_boxscores.py --dry-run
"""

import time
import logging
import sqlite3
import argparse
import pathlib

from . import api as nhl_api

log = logging.getLogger("fetch_nhl_boxscores")

DB_PATH = pathlib.Path(__file__).parent / "data" / "nhl.db"
DEFAULT_SLEEP = 0.4  # api-web.nhle.com is lenient; stay polite. Retry covers 429.

PLAYER_UPSERT = """
INSERT INTO players (player_id, name, last_position)
VALUES (:player_id, :name, :last_position)
ON CONFLICT(player_id) DO UPDATE SET
    name = excluded.name, last_position = excluded.last_position
"""

TEAM_UPSERT = """
INSERT INTO teams (team_id, abbrev) VALUES (?, ?)
ON CONFLICT(team_id) DO UPDATE SET abbrev = excluded.abbrev
"""

TEAM_GAME_INSERT = """
INSERT OR IGNORE INTO team_game (game_id, team_id, is_home, score, sog)
VALUES (:game_id, :team_id, :is_home, :score, :sog)
"""

SKATER_INSERT = """
INSERT OR IGNORE INTO skater_boxscores
 (game_id, player_id, team_id, position, sweater, goals, assists, points,
  plus_minus, pim, sog, hits, blocked_shots, takeaways, giveaways,
  power_play_goals, faceoff_pct, toi_seconds, shifts)
VALUES
 (:game_id, :player_id, :team_id, :position, :sweater, :goals, :assists, :points,
  :plus_minus, :pim, :sog, :hits, :blocked_shots, :takeaways, :giveaways,
  :power_play_goals, :faceoff_pct, :toi_seconds, :shifts)
"""

GOALIE_INSERT = """
INSERT OR IGNORE INTO goalie_boxscores
 (game_id, player_id, team_id, sweater, starter, decision, saves, shots_against,
  goals_against, save_pct, pim, toi_seconds, es_shots_against, es_goals_against,
  pp_shots_against, pp_goals_against, sh_shots_against, sh_goals_against)
VALUES
 (:game_id, :player_id, :team_id, :sweater, :starter, :decision, :saves, :shots_against,
  :goals_against, :save_pct, :pim, :toi_seconds, :es_shots_against, :es_goals_against,
  :pp_shots_against, :pp_goals_against, :sh_shots_against, :sh_goals_against)
"""


def insert_boxscore(conn: sqlite3.Connection, parsed: dict) -> None:
    """Write one parsed boxscore's teams/skaters/goalies into the DB."""
    for t in parsed["teams"]:
        if t["team_id"] is not None:
            conn.execute(TEAM_UPSERT, (t["team_id"], t["abbrev"]))
            conn.execute(TEAM_GAME_INSERT, t)
    for s in parsed["skaters"]:
        conn.execute(PLAYER_UPSERT, {"player_id": s["player_id"],
                                     "name": s["name"], "last_position": s["position"]})
        conn.execute(SKATER_INSERT, s)
    for g in parsed["goalies"]:
        conn.execute(PLAYER_UPSERT, {"player_id": g["player_id"],
                                     "name": g["name"], "last_position": "G"})
        conn.execute(GOALIE_INSERT, g)


def outstanding_games(conn: sqlite3.Connection, season: int | None,
                      min_season: int | None, team_id: int | None,
                      limit: int) -> list[str]:
    sql = "SELECT game_id FROM games WHERE boxscore_loaded = 0"
    params: list = []
    if season:
        sql += " AND season = ?"
        params.append(str(season))
    if min_season:
        sql += " AND CAST(season AS INTEGER) >= ?"
        params.append(min_season)
    if team_id:
        sql += " AND (home_team_id = ? OR away_team_id = ?)"
        params.extend([team_id, team_id])
    sql += " ORDER BY date"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill NHL boxscores into nhl.db")
    parser.add_argument("--season", type=int, default=None, help="Only this season (e.g. 20232024)")
    parser.add_argument("--min-season", type=int, default=None,
                        help="Only seasons >= this 8-digit int (e.g. 20122013)")
    parser.add_argument("--team-id", type=int, default=None,
                        help="Only games involving this team id (e.g. 10 = Toronto Maple Leafs)")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N games (0 = all)")
    parser.add_argument("--batch-size", type=int, default=100, help="Commit every N games")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="Seconds between requests")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fetched, then exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH.name} not found. Run build_nhl_db.py first.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    try:
        todo = outstanding_games(conn, args.season, args.min_season, args.team_id, args.limit)
        eta_min = len(todo) * args.sleep / 60
        log.info("Outstanding games: %d  (ETA ~%.0f min at %.2fs/req)",
                 len(todo), eta_min, args.sleep)
        if args.dry_run or not todo:
            return

        session = nhl_api.make_session()
        fetched = failed = 0
        for i, game_id in enumerate(todo, 1):
            try:
                raw = nhl_api.fetch_boxscore(session, game_id)
                parsed = nhl_api.parse_boxscore(raw)
                insert_boxscore(conn, parsed)
                conn.execute("UPDATE games SET boxscore_loaded = 1 WHERE game_id = ?", (game_id,))
                fetched += 1
            except Exception:  # noqa: BLE001 -- log, leave flag=0 so it retries
                log.exception("  failed: %s", game_id)
                failed += 1

            if fetched and fetched % args.batch_size == 0:
                conn.commit()
                log.info("  [%d/%d] committed %d games (%d failed)",
                         i, len(todo), fetched, failed)
            time.sleep(args.sleep)

        conn.commit()
        log.info("Done. Fetched %d, failed %d.", fetched, failed)
    finally:
        conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    log.info("nhl.db is now %.1f MB", size_mb)


if __name__ == "__main__":
    main()
