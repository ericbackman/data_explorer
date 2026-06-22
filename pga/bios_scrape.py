"""Backfill player biographies from ESPN's athlete endpoint.

One cached call per player id already in the `players` table -> a `player_bios`
row (age, turned-pro, birthplace, handedness, college, ht/wt). Resumable: the
HTTP cache means a re-run re-fetches nothing, and INSERT OR REPLACE makes
re-loading a no-op. Obscure/amateur ids that 404 are logged and skipped.

    python -m pga.bios_scrape                 # all players
    python -m pga.bios_scrape --min-results 4 # only players with >=4 appearances
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .db import connect, init_db, load_bios
from .espn_client import EspnClient
from .parse import parse_athlete

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"
DEFAULT_CACHE = _ROOT / "data" / "raw"


def scrape_bios(db_path: Path, cache_dir: Path, *, min_results: int = 1,
                limit: int | None = None) -> dict:
    client = EspnClient(cache_dir)
    conn = connect(db_path)
    init_db(conn)
    try:
        rows = conn.execute(
            """
            SELECT p.player_id
            FROM players p
            WHERE (SELECT COUNT(*) FROM player_results r WHERE r.player_id = p.player_id) >= ?
            ORDER BY p.player_id
            """,
            (min_results,),
        ).fetchall()
        ids = [r[0] for r in rows]
        if limit is not None:
            ids = ids[:limit]
        logger.info("fetching bios for %d players (min_results=%d)", len(ids), min_results)

        ok = fail = 0
        for i, pid in enumerate(ids, 1):
            try:
                bio = parse_athlete(client.athlete(pid))
                if bio:
                    load_bios(conn, [bio])
                    ok += 1
                else:
                    fail += 1
            except Exception:
                # 404 for obscure/amateur ids is expected -- log quietly, continue.
                fail += 1
                logger.debug("no bio for player %s", pid)
            if i % 250 == 0:
                logger.info("  %d/%d (%d ok, %d skipped)", i, len(ids), ok, fail)
        total = conn.execute("SELECT COUNT(*) FROM player_bios").fetchone()[0]
        return {"fetched_ok": ok, "skipped": fail, "total_bios": total}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill player bios from ESPN.")
    parser.add_argument("--min-results", type=int, default=1,
                        help="only players with at least this many event results")
    parser.add_argument("--limit", type=int, default=None, help="cap players (for a test run)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    stats = scrape_bios(args.db, args.cache, min_results=args.min_results, limit=args.limit)
    logger.info("done: %s", stats)


if __name__ == "__main__":
    main()
