"""Backfill / update the local soccer database from ESPN's scoreboard API.

The efficient backbone
----------------------
One scoreboard request per competition-year returns the whole edition: every
match with its final score, penalty shootout, and an embedded event stream
(goals/cards). So a full pull of World Cup history is ~23 requests (one per
tournament), not one-per-match — seconds, not hours.

Per-match lineups (who started) are a separate, more expensive tier (one
`summary` request per match) added by `--with-lineups`; it joins onto the
matches this builds.

Usage
-----
  python -m soccer.scrape                          # all World Cups (default)
  python -m soccer.scrape --competition fifa.world --dry-run
  python -m soccer.scrape --competition uefa.euro --years 1996-2024
  python -m soccer.scrape --force                  # re-fetch even loaded editions
"""
from __future__ import annotations

import argparse
import datetime
import logging
import pathlib

from soccer import db, parse
from soccer.espn_client import EspnSoccerClient

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent     # data_explorer/soccer/
DATA_DIR = PKG_DIR / "data"                            # gitignored: db + cache
DB_PATH = DATA_DIR / "soccer.db"
CACHE_DIR = DATA_DIR / "cache"

# Editions that no longer change once played, so "loaded once" == "correct
# forever". The live/current tournament is always re-fetched (scores update).
# FIFA World Cup years: every 4th year from 1930, minus 1942 & 1946 (WWII).
WORLD_CUP_YEARS = [y for y in range(1930, 2027, 4) if y not in (1942, 1946)]
# UEFA Euro: every 4th year from 1960; 2020 was played in 2021 but ESPN files it
# under 2020. (Only needed when extending past the World Cup.)
EURO_YEARS = [y for y in range(1960, 2025, 4)]

DEFAULT_YEARS: dict[str, list[int]] = {
    "fifa.world": WORLD_CUP_YEARS,
    "uefa.euro": EURO_YEARS,
}


def default_years(slug: str) -> list[int]:
    """Years to pull for a competition when --years isn't given."""
    if slug in DEFAULT_YEARS:
        return DEFAULT_YEARS[slug]
    # Leagues / club cups: ESPN's soccer data is reliable from ~2001 onward.
    return list(range(2001, datetime.date.today().year + 1))


def parse_years_arg(value: str) -> list[int]:
    """'1996-2024' -> [1996..2024];  '2022' -> [2022]."""
    if "-" in value:
        lo, _, hi = value.partition("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(value)]


def seasons_to_fetch(conn, comp_id: int, years: list[int], current_year: int,
                     force: bool) -> list[int]:
    """Years we actually hit the network for: the current year always (live
    scores), plus any past year not yet loaded. Older loaded years are immutable.
    """
    if force:
        return list(years)
    todo = []
    for y in years:
        if y >= current_year:
            todo.append(y)  # live edition — re-fetch for updated scores
            continue
        sid = parse.season_id_for(comp_id, y)
        if not db.loaded_match_ids(conn, sid):
            todo.append(y)
    return todo


def ingest_year(client: EspnSoccerClient, conn, meta: parse.CompetitionMeta,
                year: int, current_year: int) -> dict:
    """Fetch + load one competition-year. Returns a small stat summary."""
    use_cache = year < current_year  # live edition's cached JSON goes stale intra-day
    data = client.scoreboard(meta.slug, year, use_cache=use_cache)
    parsed = parse.parse_scoreboard(meta, year, data)
    if parsed.season is None:
        return {"matches": 0, "events": 0}
    db.load_competition(conn, parsed.competition, parsed.season)
    n_matches = db.load_matches(conn, parsed.teams, parsed.matches)
    # event scorers/carded players become the player dimension (no lineups yet)
    db.load_match_detail(conn, players=parsed.players, lineups=[], events=parsed.events)
    return {"matches": n_matches, "events": len(parsed.events)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/update the local soccer DB from ESPN")
    ap.add_argument("--competition", default="fifa.world",
                    help="ESPN league code (default fifa.world). See parse.COMPETITIONS")
    ap.add_argument("--years", help="START-END or single year; default = the competition's editions")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument("--force", action="store_true", help="re-fetch even loaded editions")
    ap.add_argument("--dry-run", action="store_true", help="show plan, fetch nothing")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    meta = parse.COMPETITIONS.get(args.competition)
    if meta is None:
        ap.error(f"unknown competition {args.competition!r}; known: {', '.join(parse.COMPETITIONS)}")

    years = parse_years_arg(args.years) if args.years else default_years(meta.slug)
    current_year = datetime.date.today().year
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)
    db.init_db(conn)

    todo = seasons_to_fetch(conn, meta.competition_id, years, current_year, args.force)
    log.info("%s: %d editions requested, %d to fetch (current year=%d)",
             meta.name, len(years), len(todo), current_year)

    if args.dry_run:
        log.info("DRY RUN — would fetch %s: %s", meta.slug,
                 ", ".join(map(str, todo)) or "(nothing)")
        conn.close()
        return

    client = EspnSoccerClient(CACHE_DIR)
    totals = {"matches": 0, "events": 0}
    failed = []
    for year in todo:
        try:
            c = ingest_year(client, conn, meta, year, current_year)
        except Exception as e:  # one bad edition must not abort the whole run
            log.error("%s %d failed: %s — skipping (re-run to retry)", meta.slug, year, e)
            failed.append(year)
            continue
        totals["matches"] += c["matches"]
        totals["events"] += c["events"]
        log.info("loaded %s %d: %d matches, %d events", meta.slug, year, c["matches"], c["events"])

    # Loud notice if the user's match_outcome() rule isn't implemented yet.
    s = db.summary(conn)
    unresolved = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE outcome IS NULL AND home_score IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    log.info("done: %d matches, %d events across %d editions",
             totals["matches"], totals["events"], len(todo) - len(failed))
    log.info("DB totals: %s", s)
    if unresolved:
        log.warning("%d played matches have outcome=NULL — implement parse.match_outcome() "
                    "and re-run (idempotent) to backfill the result column.", unresolved)
    if failed:
        log.warning("%d edition(s) failed (cache makes done ones free on re-run): %s",
                    len(failed), ", ".join(map(str, failed)))


if __name__ == "__main__":
    main()
