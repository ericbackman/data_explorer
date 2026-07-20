"""Backfill the local NBA `drafts` table from nba_api's DraftHistory endpoint.

Unlike the game-log backbone (one request per season), DraftHistory returns the
*entire* draft history in a single request, so the default pull is one cheap,
cached call that loads every pick from 1947 to the latest draft.

The drafts table is what the Sleep Sports channel reads from: one verified row
per pick (season, overall_pick, team, player, "from ORGANIZATION"), so a
narration says "with the third pick, the Denver Nuggets select Carmelo Anthony,
from Syracuse" off a database row instead of a hand-typed, misremembered fact.

Usage
-----
  python -m nba.draft_scrape                 # all draft history (one request)
  python -m nba.draft_scrape --season 2003   # just the 2003 draft
  python -m nba.draft_scrape --dry-run
"""

from __future__ import annotations

import argparse
import logging
import pathlib

from nba import db, parse
from nba.client import NBAClient

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent  # data_explorer/nba/
DATA_DIR = PKG_DIR / "data"                         # gitignored: db + cache live here
DB_PATH = DATA_DIR / "nba.db"
CACHE_DIR = DATA_DIR / "cache"


def ingest_drafts(client: NBAClient, conn, season: str | None) -> int:
    """Fetch + load draft picks (all history, or one year). Returns rows loaded."""
    df = client.draft_history(season=season)
    rows = parse.parse_draft(df)
    dropped = len(df) - len(rows)
    if dropped:
        log.info("skipped %d row(s) with no usable pick slot", dropped)
    n = db.load_drafts(conn, rows)
    conn.commit()
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/update the NBA drafts table from nba_api")
    ap.add_argument("--season", default=None,
                    help="single draft year, e.g. 2003 (default: all draft history)")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument("--dry-run", action="store_true", help="fetch + parse, load nothing")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    client = NBAClient(CACHE_DIR)

    if args.dry_run:
        df = client.draft_history(season=args.season)
        rows = parse.parse_draft(df)
        log.info("DRY RUN — parsed %d pick rows from %d raw (season=%s); loading nothing",
                 len(rows), len(df), args.season or "all")
        return

    conn = db.connect(args.db)
    n = ingest_drafts(client, conn, args.season)
    seasons = sorted(db.loaded_draft_seasons(conn))
    conn.close()
    log.info("loaded %d pick rows; drafts table now spans %s–%s (%d drafts)",
             n, seasons[0] if seasons else "?", seasons[-1] if seasons else "?", len(seasons))


if __name__ == "__main__":
    main()
