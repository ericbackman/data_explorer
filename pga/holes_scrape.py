"""Backfill hole-level data by re-parsing the cached season scoreboards.

The original Tier-1 backfill already downloaded full-season scoreboards, and
those nest per-hole linescores under each round -- so this needs NO network. It
re-reads data/raw/schedule/{year}.json and loads event_holes + player_hole_scores
for the stroke-play events already present in the tournaments table (match-play
events aren't in tournaments, so they're skipped automatically).

    python -m pga.holes_scrape --seasons 2005-2026
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .db import connect, init_db, load_event_holes
from .espn_client import EARLIEST_SEASON
from .parse import parse_event_holes
from .scrape import parse_seasons

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"
DEFAULT_CACHE = _ROOT / "data" / "raw"


def backfill(seasons: list[int], db_path: Path, cache_dir: Path) -> dict:
    conn = connect(db_path)
    init_db(conn)
    valid = {r[0] for r in conn.execute("SELECT event_id FROM tournaments")}
    try:
        total_events = total_holes = 0
        for year in seasons:
            cache_file = cache_dir / "schedule" / f"{year}.json"
            if not cache_file.exists():
                logger.warning("no season cache for %s (%s) -- skipping", year, cache_file)
                continue
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            loaded = 0
            for event in data.get("events", []):
                try:
                    eid = int(event.get("id"))
                except (TypeError, ValueError):
                    continue
                if eid not in valid:  # not a loaded stroke-play event
                    continue
                event_holes, hole_scores = parse_event_holes(event)
                if not hole_scores:
                    continue
                load_event_holes(conn, event_holes, hole_scores)
                loaded += 1
                total_holes += len(hole_scores)
            total_events += loaded
            logger.info("season %s: %d events loaded, %d hole-scores cumulative",
                        year, loaded, total_holes)
        n_hs = conn.execute("SELECT COUNT(*) FROM player_hole_scores").fetchone()[0]
        n_eh = conn.execute("SELECT COUNT(*) FROM event_holes").fetchone()[0]
        return {"events": total_events, "player_hole_scores": n_hs, "event_holes": n_eh}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill hole-level scores from cached scoreboards.")
    parser.add_argument("--seasons", default=f"{EARLIEST_SEASON}-2026")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    seasons = parse_seasons(args.seasons)
    logger.info("hole backfill, seasons %s -> %s (no network; re-parsing cache)", seasons[0], seasons[-1])
    stats = backfill(seasons, args.db, args.cache)
    logger.info("done: %s", stats)


if __name__ == "__main__":
    main()
