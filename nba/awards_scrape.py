"""Backfill the local NBA `player_awards` table from nba_api's PlayerAwards.

Unlike DraftHistory (one request for everything), PlayerAwards is per-player, so
this walks the players we care about one request at a time — rate-limited and
resumable. The target set is **drafted players who actually played** (the set the
Sleep Sports channel narrates); a player with zero awards is still marked fetched
so a re-run skips him.

The awards are the authoritative source for accolades — "eighteen All-Star
selections, one Most Valuable Player, five championships" off verified rows
instead of memory.

Usage
-----
  python -m nba.awards_scrape                 # all drafted-with-games players (resumable)
  python -m nba.awards_scrape --limit 25      # first 25 unfetched (a quick sample)
  python -m nba.awards_scrape --person 977    # just one player (Kobe)
"""

from __future__ import annotations

import argparse
import logging
import pathlib

from nba import db, parse
from nba.client import NBAClient

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"
DB_PATH = DATA_DIR / "nba.db"
CACHE_DIR = DATA_DIR / "cache"


def target_persons(conn) -> list[int]:
    """Drafted players who logged at least one game — the ones who could have
    awards and the ones the narration cares about, in a stable order."""
    return [r[0] for r in conn.execute(
        """
        SELECT DISTINCT d.person_id
        FROM drafts d
        WHERE d.person_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM player_game pg WHERE pg.player_id = d.person_id)
        ORDER BY d.person_id
        """
    )]


def ingest_awards(client: NBAClient, conn, person_id: int) -> int:
    df = client.player_awards(person_id)
    rows = parse.parse_player_awards(df, person_id)
    n = db.load_player_awards(conn, person_id, rows)
    conn.commit()
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/update the NBA player_awards table from nba_api")
    ap.add_argument("--person", type=int, default=None, help="one person_id (e.g. 977 = Kobe)")
    ap.add_argument("--limit", type=int, default=None, help="cap how many unfetched players to pull")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)
    client = NBAClient(CACHE_DIR)

    if args.person is not None:
        todo = [args.person]
    else:
        done = db.loaded_award_persons(conn)
        todo = [p for p in target_persons(conn) if p not in done]
        if args.limit:
            todo = todo[: args.limit]

    log.info("fetching awards for %d player(s)", len(todo))
    total = 0
    for i, pid in enumerate(todo, 1):
        n = ingest_awards(client, conn, pid)
        total += n
        if i % 25 == 0 or n:
            log.info("[%d/%d] person %d: %d award rows", i, len(todo), pid, n)

    grand = conn.execute("SELECT COUNT(*) FROM player_awards").fetchone()[0]
    persons = conn.execute("SELECT COUNT(*) FROM awards_fetched").fetchone()[0]
    conn.close()
    log.info("done: +%d rows this run; player_awards now %d rows across %d fetched players",
             total, grand, persons)


if __name__ == "__main__":
    main()
