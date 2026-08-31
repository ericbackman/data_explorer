"""Build / refresh the unified cross-sport draft database (drafts.db).

    python -m draft.build                            # all sports, all history
    python -m draft.build --sports nba,nfl           # a subset
    python -m draft.build --sports mlb --years 2000-2025
    python -m draft.build --dry-run                  # fetch + validate, write nothing

Idempotent: every source loads with INSERT OR REPLACE on the natural key, so
re-running converges. One bad season is logged and skipped inside each adapter,
never aborting the others.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from draft import db
from draft.sources import mlb, nba, nfl, nhl

log = logging.getLogger(__name__)

PKG_DIR = Path(__file__).resolve().parent        # data_explorer/draft/
DB_PATH = PKG_DIR.parent / "drafts.db"           # data_explorer/drafts.db (repo root)

SOURCES = {"nba": nba, "nfl": nfl, "nhl": nhl, "mlb": mlb}


def parse_years(value: str | None) -> list[int] | None:
    """'2000-2025' -> [2000..2025]; '2023' -> [2023]; None/empty -> None (full history)."""
    if not value:
        return None
    start, _, end = value.partition("-")
    return list(range(int(start), int(end) + 1)) if end else [int(start)]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the unified cross-sport draft DB")
    ap.add_argument("--sports", default="nba,nfl,nhl,mlb",
                    help="comma list of: " + ", ".join(SOURCES))
    ap.add_argument("--years", default=None,
                    help="START-END (default: each source's full history)")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument("--dry-run", action="store_true", help="fetch + validate, write nothing")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    for s in sports:
        if s not in SOURCES:
            raise SystemExit(f"unknown sport {s!r}; choices: {list(SOURCES)}")
    years = parse_years(args.years)

    conn = None if args.dry_run else db.connect(args.db)
    try:
        for s in sports:
            mod = SOURCES[s]
            rows = mod.fetch(years)
            if args.dry_run:
                db.assert_unique_keys(rows, mod.SPORT)  # validate the key even when not writing
                log.info("[dry-run] %s: %d picks (not written)", mod.SPORT, len(rows))
                continue
            n = db.load(conn, rows, sport=mod.SPORT)
            log.info("== %s: %d picks loaded ==", mod.SPORT, n)

        if conn is not None:
            summ = db.summary(conn)
            log.info("drafts.db now holds %d picks:", summ["total"])
            for sport, info in summ["by_sport"].items():
                log.info("  %-4s %6d picks  %s-%s",
                         sport, info["picks"], info["year_min"], info["year_max"])
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
