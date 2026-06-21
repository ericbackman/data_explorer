"""Orchestrator: discover a season's events, fetch each leaderboard, load to DB.

Resumable by construction -- the HTTP cache means a re-run re-fetches nothing,
and INSERT OR REPLACE means re-loading an event is a no-op on the data.

Usage:
    python -m pga_data.scrape --seasons 2024
    python -m pga_data.scrape --seasons 2005-2026
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .db import connect, init_db, load_event, summary
from .espn_client import EARLIEST_SEASON, EspnClient
from .parse import UnsupportedEventError, parse_leaderboard

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"
DEFAULT_CACHE = _ROOT / "data" / "raw"


def parse_seasons(spec: str) -> list[int]:
    """'2024' -> [2024]; '2005-2026' -> [2005..2026]."""
    if "-" in spec:
        lo, hi = (int(x) for x in spec.split("-", 1))
    else:
        lo = hi = int(spec)
    if lo > hi:
        lo, hi = hi, lo
    if lo < EARLIEST_SEASON:
        logger.warning("ESPN has no data before %s; clamping %s -> %s",
                       EARLIEST_SEASON, lo, EARLIEST_SEASON)
        lo = EARLIEST_SEASON
    return list(range(lo, hi + 1))


def scrape_seasons(seasons: list[int], db_path: Path, cache_dir: Path) -> dict:
    client = EspnClient(cache_dir)
    conn = connect(db_path)
    init_db(conn)
    try:
        for year in seasons:
            try:
                events = client.season_events(year)
            except Exception:
                # A throttled/failed schedule fetch must not abort the other 20
                # seasons -- log it and move on; a later re-run picks it up.
                logger.exception("could not fetch schedule for season %s -- skipping", year)
                continue
            ok = fail = skipped = 0
            for stub in events:
                eid = stub.get("id")
                name = stub.get("name", "?")
                try:
                    raw = client.leaderboard(eid)
                    parsed = parse_leaderboard(raw)
                    load_event(conn, parsed)
                    ok += 1
                except UnsupportedEventError as exc:
                    # Team/match-play formats have no stroke-play leader -- expected.
                    skipped += 1
                    logger.info("skipped %s: %s", eid, exc)
                except Exception:
                    # One bad event must not abort a 20-year backfill -- log
                    # loudly with the id so it can be inspected, then continue.
                    fail += 1
                    logger.exception("FAILED event %s (%s) in season %s", eid, name, year)
            logger.info("season %s done: %d loaded, %d skipped, %d failed",
                        year, ok, skipped, fail)
    finally:
        conn.close()
    conn = connect(db_path)
    try:
        return summary(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scrape PGA Tour history from ESPN into SQLite.")
    parser.add_argument("--seasons", default=f"{EARLIEST_SEASON}-2026",
                        help="single year '2024' or range '2005-2026'")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    seasons = parse_seasons(args.seasons)
    logger.info("scraping seasons %s -> %s", seasons[0], seasons[-1])
    stats = scrape_seasons(seasons, args.db, args.cache)
    logger.info("DB summary: %s", stats)


if __name__ == "__main__":
    main()
