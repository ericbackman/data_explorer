"""
NHL Draft Scrape
================
Loads every NHL entry draft pick (1963 -> present) into nhl.db's `drafts`
table.

Primary source: records.nhl.com/site/api/draft -- a single Cayenne-backed
call that returns ALL picks ever in one response (verified 2026-07: 13,152
rows, draftYear 1963-2026). Critically, this endpoint carries `playerId`,
the same NHL person-id space used by `players` / `skater_boxscores` /
`goalie_boxscores`, so drafts join straight onto the existing boxscore data.

Fallback: api-web.nhle.com/v1/draft/picks/{year}/all -- per-year, richer team
metadata (full team name, logos) but NO playerId field at all, so picks
loaded from it can't be joined to a player's career stats. Only used if the
bulk endpoint is unreachable; fetched/cached one year at a time so it's
resumable.

Usage:
    python -m nhl.draft_scrape                # fetch (or reuse cache) + load + validate
    python -m nhl.draft_scrape --no-fetch      # load from raw/ cache only, no network
    python -m nhl.draft_scrape --force-fetch   # ignore cache, hit the network again
    python -m nhl.draft_scrape --verify-only   # skip fetch+load, just run validation
"""

import json
import logging
import sqlite3
import argparse
import pathlib

from . import api as nhl_api

log = logging.getLogger("draft_scrape")

DB_PATH = pathlib.Path(__file__).parent / "data" / "nhl.db"
RAW_DIR = pathlib.Path(__file__).parent / "data" / "raw"

BULK_URL = "https://records.nhl.com/site/api/draft"
BULK_CACHE = RAW_DIR / "draft_bulk.json"

FALLBACK_URL_TMPL = "https://api-web.nhle.com/v1/draft/picks/{year}/all"
FALLBACK_CACHE_TMPL = str(RAW_DIR / "draft_fallback_{year}.json")

# records.nhl.com data starts at the first modern entry draft.
FIRST_DRAFT_YEAR = 1963

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS drafts (
    draft_year      INTEGER NOT NULL,
    overall_pick    INTEGER NOT NULL,
    round_number    INTEGER,
    round_pick      INTEGER,          -- pick within the round
    player_id       INTEGER,          -- NHL person id; NULL only for api-web-fallback rows
    player_name     TEXT,
    first_name      TEXT,
    last_name       TEXT,
    position        TEXT,
    team_id         INTEGER,          -- same id space as teams.team_id (pre-1997 defunct teams may be absent there)
    team_abbrev     TEXT,             -- tricode AT DRAFT TIME (e.g. 'WIN', 'QUE', 'HFD')
    amateur_league  TEXT,
    amateur_club    TEXT,
    country_code    TEXT,
    height          INTEGER,
    weight          INTEGER,
    source          TEXT NOT NULL,    -- 'records' | 'api-web'
    PRIMARY KEY (draft_year, overall_pick)
);

CREATE INDEX IF NOT EXISTS idx_drafts_player ON drafts(player_id);
CREATE INDEX IF NOT EXISTS idx_drafts_team   ON drafts(team_id);
CREATE INDEX IF NOT EXISTS idx_drafts_year   ON drafts(draft_year);
"""

DRAFT_UPSERT = """
INSERT INTO drafts
 (draft_year, overall_pick, round_number, round_pick, player_id, player_name,
  first_name, last_name, position, team_id, team_abbrev, amateur_league,
  amateur_club, country_code, height, weight, source)
VALUES
 (:draft_year, :overall_pick, :round_number, :round_pick, :player_id, :player_name,
  :first_name, :last_name, :position, :team_id, :team_abbrev, :amateur_league,
  :amateur_club, :country_code, :height, :weight, :source)
ON CONFLICT(draft_year, overall_pick) DO UPDATE SET
    player_id      = excluded.player_id,
    player_name    = excluded.player_name,
    team_id        = excluded.team_id,
    team_abbrev    = excluded.team_abbrev,
    source         = excluded.source
"""

TEAM_INSERT = "INSERT OR IGNORE INTO teams (team_id, abbrev) VALUES (?, ?)"


# ── Fetch (bulk, primary) ────────────────────────────────────────────────────

def fetch_bulk(session, force: bool = False) -> list[dict]:
    """All draft picks ever, in one call. Cached to disk; reused unless
    ``force`` is set, since this endpoint rarely changes except to append the
    current year's just-completed draft."""
    if BULK_CACHE.exists() and not force:
        log.info("Using cached bulk draft JSON: %s", BULK_CACHE)
        return json.loads(BULK_CACHE.read_text(encoding="utf-8"))["data"]

    log.info("Fetching %s ...", BULK_URL)
    payload = nhl_api.get_json(session, BULK_URL)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    BULK_CACHE.write_text(json.dumps(payload), encoding="utf-8")
    rows = payload.get("data", [])
    log.info("Bulk draft endpoint returned %d rows", len(rows))
    return rows


def parse_bulk_row(row: dict) -> dict:
    """One records.nhl.com draft row -> a flat drafts-table record."""
    return {
        "draft_year": row["draftYear"],
        "overall_pick": row["overallPickNumber"],
        "round_number": row.get("roundNumber"),
        "round_pick": row.get("pickInRound"),
        "player_id": row.get("playerId"),
        "player_name": row.get("playerName"),
        "first_name": row.get("firstName"),
        "last_name": row.get("lastName"),
        "position": row.get("position"),
        "team_id": row.get("draftedByTeamId"),
        "team_abbrev": row.get("triCode"),
        "amateur_league": row.get("amateurLeague"),
        "amateur_club": row.get("amateurClubName"),
        "country_code": row.get("countryCode"),
        "height": row.get("height"),
        "weight": row.get("weight"),
        "source": "records",
    }


# ── Fetch (per-year, fallback only) ─────────────────────────────────────────

def fetch_year_fallback(session, year: int) -> list[dict]:
    """Per-year picks from api-web.nhle.com. No playerId field -- rows loaded
    from here can't join to players/boxscores. Cached per-year so this path
    is resumable if the bulk endpoint is down for a while."""
    cache_path = pathlib.Path(FALLBACK_CACHE_TMPL.format(year=year))
    if cache_path.exists():
        picks = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        payload = nhl_api.get_json(session, FALLBACK_URL_TMPL.format(year=year))
        picks = payload.get("picks", [])
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(picks), encoding="utf-8")
    return picks


def parse_fallback_row(row: dict, year: int) -> dict:
    """One api-web draft-pick row -> a flat drafts-table record. player_id is
    always NULL here -- the endpoint doesn't expose the NHL person id."""
    return {
        "draft_year": year,
        "overall_pick": row.get("overallPick"),
        "round_number": row.get("round"),
        "round_pick": row.get("pickInRound"),
        "player_id": None,
        "player_name": f"{row.get('firstName', '')} {row.get('lastName', '')}".strip() or None,
        "first_name": row.get("firstName"),
        "last_name": row.get("lastName"),
        "position": row.get("positionCode"),
        "team_id": row.get("teamId"),
        "team_abbrev": row.get("teamAbbrev"),
        "amateur_league": row.get("amateurLeague"),
        "amateur_club": row.get("amateurClubName"),
        "country_code": row.get("countryCode"),
        "height": row.get("height"),
        "weight": row.get("weight"),
        "source": "api-web",
    }


def fetch_all_fallback(session, first_year: int, last_year: int) -> list[dict]:
    records = []
    for year in range(first_year, last_year + 1):
        try:
            picks = fetch_year_fallback(session, year)
        except Exception:  # noqa: BLE001 -- log and keep going, per-year is resumable
            log.exception("  fallback fetch failed for %d, skipping", year)
            continue
        records.extend(parse_fallback_row(p, year) for p in picks)
    return records


# ── Load ─────────────────────────────────────────────────────────────────────

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def load_drafts(conn: sqlite3.Connection, records: list[dict]) -> int:
    conn.executemany(DRAFT_UPSERT, records)
    team_ids = {(r["team_id"], r["team_abbrev"]) for r in records if r["team_id"] is not None}
    conn.executemany(TEAM_INSERT, sorted(team_ids))
    conn.commit()
    return len(records)


# ── Validate ─────────────────────────────────────────────────────────────────

KNOWN_FACTS = [
    (2005, 1, "Crosby", "PIT"),
    (1984, 1, "Lemieux", "PIT"),
    (1998, 171, "Datsyuk", "DET"),
]


def validate(conn: sqlite3.Connection) -> None:
    total, min_year, max_year = conn.execute(
        "SELECT COUNT(*), MIN(draft_year), MAX(draft_year) FROM drafts"
    ).fetchone()
    log.info("drafts: %d rows, years %s-%s", total, min_year, max_year)

    ok = True
    for year, pick, expect_last, expect_team in KNOWN_FACTS:
        row = conn.execute(
            "SELECT last_name, team_abbrev, player_id FROM drafts WHERE draft_year=? AND overall_pick=?",
            (year, pick),
        ).fetchone()
        if row is None:
            log.error("VALIDATION FAIL: no row for %d pick #%d", year, pick)
            ok = False
            continue
        last_name, team_abbrev, player_id = row
        passed = last_name == expect_last and team_abbrev == expect_team
        ok = ok and passed
        log.info(
            "%s %d #%d = %s (%s), player_id=%s  [expected %s/%s]",
            "PASS" if passed else "FAIL",
            year, pick, last_name, team_abbrev, player_id, expect_last, expect_team,
        )
    if not ok:
        raise SystemExit("Draft validation failed -- see FAIL lines above")

    # Join hit-rate vs the existing players table, post-RTSS-floor (1997+).
    player_ids = {r[0] for r in conn.execute("SELECT player_id FROM players")}
    post97 = conn.execute(
        "SELECT player_id FROM drafts WHERE draft_year >= 1997 AND player_id IS NOT NULL"
    ).fetchall()
    hits = sum(1 for (pid,) in post97 if pid in player_ids)
    log.info("Join hit-rate vs players table (1997+ draftees): %d/%d (%.1f%%) -- "
             "most late-round/recent picks never play an NHL game, so this is "
             "expected to be well under 100%%.", hits, len(post97),
             100 * hits / len(post97) if post97 else 0)

    r1 = conn.execute(
        "SELECT player_id FROM drafts WHERE draft_year >= 1997 AND round_number = 1 AND player_id IS NOT NULL"
    ).fetchall()
    r1_hits = sum(1 for (pid,) in r1 if pid in player_ids)
    log.info("Round-1 hit-rate (1997+): %d/%d (%.1f%%)", r1_hits, len(r1),
              100 * r1_hits / len(r1) if r1 else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load NHL draft picks into nhl.db")
    parser.add_argument("--no-fetch", action="store_true", help="Load from raw/ cache only, no network")
    parser.add_argument("--force-fetch", action="store_true", help="Ignore cache, hit the network again")
    parser.add_argument("--verify-only", action="store_true", help="Skip fetch+load, just run validation")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH.name} not found. Run `python -m nhl.build` first.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        init_schema(conn)

        if not args.verify_only:
            session = nhl_api.make_session()
            records: list[dict] = []
            try:
                if args.no_fetch and not BULK_CACHE.exists():
                    raise SystemExit(f"--no-fetch given but {BULK_CACHE} doesn't exist yet")
                bulk_rows = fetch_bulk(session, force=args.force_fetch and not args.no_fetch)
                records = [parse_bulk_row(r) for r in bulk_rows]
            except Exception:  # noqa: BLE001 -- log, fall back to per-year api-web
                log.exception("Bulk draft fetch failed; falling back to api-web per-year")
                import datetime
                last_year = datetime.date.today().year
                records = fetch_all_fallback(session, FIRST_DRAFT_YEAR, last_year)

            n = load_drafts(conn, records)
            log.info("Loaded %d draft picks into %s", n, DB_PATH.name)

        validate(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
