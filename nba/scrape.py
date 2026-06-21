"""Backfill / update the local NBA database, purely from nba_api.

The efficient backbone
----------------------
LeagueGameLog returns *every* player-game (or team-game) row for an entire
season in ONE request. So a full historical pull of traditional box scores is
~4 requests per season (player/team x regular/playoffs), not one-per-game:
~80 seasons => ~320 requests => minutes, not hours.

Per-game detail (advanced box scores, play-by-play, starters/bench) is a
separate, expensive tier you add later — it joins onto the games this builds.

Usage
-----
  python -m nba.scrape --seasons 1996-2026          # modern era
  python -m nba.scrape --seasons 1946-2026          # all of NBA history
  python -m nba.scrape --seasons 2025-2026 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sqlite3

from nba import db, parse
from nba.client import NBAClient

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent  # data_explorer/nba/
DATA_DIR = PKG_DIR / "data"                         # gitignored: db + cache live here
DB_PATH = DATA_DIR / "nba.db"
CACHE_DIR = DATA_DIR / "cache"
SEASON_TYPES = ["Regular Season", "Playoffs"]


# ─────────────────────────────────────────────────────────────────────────────
# Refetch policy: which requested seasons do we actually re-hit the network for?
# ─────────────────────────────────────────────────────────────────────────────
# Always re-pull the most recent N seasons (the live one + recent history), and
# otherwise skip any season already loaded. The safety net exists because two
# things change after a season first lands: (1) the live season gains a game
# every night, and (2) the NBA issues box-score stat corrections for days after
# a game. So "loaded once" is NOT "correct forever" for recent seasons, though it
# is a safe assumption for seasons that are years old.
REFETCH_RECENT_SEASONS = 2  # current season + this many prior, always re-pulled


def _recent_seasons(current_season: str, n: int) -> set[str]:
    """The current season and the (n-1) seasons before it, as season strings."""
    start = int(current_season[:4])
    return {parse.season_str(y) for y in range(start - n + 1, start + 1)}


def seasons_to_refetch(
    conn: sqlite3.Connection,
    requested: list[str],
    current_season: str,
    force: bool,
) -> list[str]:
    """Return the subset of `requested` to actually fetch, in order.

    Policy: --force re-pulls everything; otherwise we re-pull the most recent
    REFETCH_RECENT_SEASONS seasons unconditionally (to catch live games + late
    stat corrections) and skip any older season already present in the DB.
    """
    if force:
        return list(requested)
    loaded = db.loaded_seasons(conn)
    recent = _recent_seasons(current_season, REFETCH_RECENT_SEASONS)
    return [s for s in requested if s in recent or s not in loaded]


# ─────────────────────────────────────────────────────────────────────────────


def ingest_season(client: NBAClient, conn: sqlite3.Connection,
                  season: str, current_season: str) -> dict:
    """Fetch + load one season (both season types). Returns a small stat summary."""
    # The live season's cached JSON goes stale intra-day, so force a network read.
    use_cache = season != current_season
    counts = {"player_rows": 0, "team_rows": 0, "games": 0}

    for stype in SEASON_TYPES:
        pdf = client.league_game_log(season, stype, "P", use_cache=use_cache)
        prows = parse.parse_player_log(pdf, season, stype)
        counts["player_rows"] += db.load_player_game(conn, prows)

        tdf = client.league_game_log(season, stype, "T", use_cache=use_cache)
        trows = parse.parse_team_log(tdf, season, stype)
        counts["team_rows"] += db.load_team_game(conn, trows)
        counts["games"] += db.load_games(conn, parse.derive_games(trows))

    conn.commit()
    return counts


def parse_seasons_arg(value: str) -> list[str]:
    """'1996-2026' -> ['1996-97', ..., '2025-26'] (range is by *start year*)."""
    start_str, _, end_str = value.partition("-")
    start, end = int(start_str), int(end_str)
    if start < parse.EARLIEST_SEASON:
        raise ValueError(f"earliest NBA season is {parse.EARLIEST_SEASON}-47")
    return parse.season_range(start, end - 1)  # end year is the *closing* year


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/update the local NBA DB from nba_api")
    ap.add_argument("--seasons", default="1996-2026",
                    help="START-END by start year, e.g. 1996-2026 (default) or 1946-2026")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument("--force", action="store_true", help="re-fetch even loaded seasons")
    ap.add_argument("--dry-run", action="store_true", help="show plan, fetch nothing")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    requested = parse_seasons_arg(args.seasons)
    current = parse.current_season_str()
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)

    todo = seasons_to_refetch(conn, requested, current, args.force)
    log.info("requested %d seasons; %d to fetch (current=%s)",
             len(requested), len(todo), current)

    if args.dry_run:
        # ~4 requests/season at the client's min interval, very rough ETA.
        est_min = len(todo) * 4 * 0.7 / 60
        log.info("DRY RUN — would fetch: %s", ", ".join(todo) or "(nothing)")
        log.info("estimated ~%.1f min of requests", est_min)
        conn.close()
        return

    client = NBAClient(CACHE_DIR)
    totals = {"player_rows": 0, "team_rows": 0, "games": 0}
    for season in todo:
        c = ingest_season(client, conn, season, current)
        for k in totals:
            totals[k] += c[k]
        log.info("loaded %s: %d games, %d player-rows", season, c["games"], c["player_rows"])

    conn.close()
    log.info("done: %d games, %d player-rows, %d team-rows across %d seasons",
             totals["games"], totals["player_rows"], totals["team_rows"], len(todo))


if __name__ == "__main__":
    main()
