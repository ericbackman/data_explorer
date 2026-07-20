"""
Build the MLB draft + career-value SQLite database
====================================================
Orchestrates Phase A of the MLB draft backbone:

  1. Draft picks 1965-2025 from MLB StatsAPI (``draft_api.py``), cached as
     raw JSON per year under ``mlb/data/raw/drafts/`` (resumable — re-running
     skips any year already cached).
  2. Career source tables (People/Batting/Pitching/AwardsPlayers/HallOfFame)
     from the current Lahman distribution (``chadwick.py`` — see that
     module's docstring for why this is SABR's Box folder, not the GitHub
     repo the task assumed, plus one documented stale fallback file).
  3. The mlbam<->Lahman id bridge (``person_map.py``), primary pass via the
     Chadwick register, fallback pass via name+birth-year.
  4. Career value v0 (``career_value.py``): MAX(batting games, pitching
     games) per player.
  5. Validation against known facts (Strasburg #1 2009, Piazza round-62
     1988, Rick Monday #1 1965) + match-rate reporting.

Usage:
    python -m mlb.build                      # full build, 1965-2025
    python -m mlb.build --start-year 2020 --end-year 2025   # partial (fast iteration)
    python -m mlb.build --skip-drafts        # rebuild career/bridge/value only
    python -m mlb.build --validate-only       # just print the validation report
"""

from __future__ import annotations

import argparse
import csv
import logging
import pathlib
import sqlite3
import time

from . import career_value as cv
from . import chadwick
from . import draft_api
from . import person_map as pm

log = logging.getLogger("mlb.build")

MLB_DIR = pathlib.Path(__file__).parent
DATA_DIR = MLB_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
DRAFT_RAW_DIR = RAW_DIR / "drafts"
CHADWICK_RAW_DIR = RAW_DIR / "chadwick"
REGISTER_RAW_DIR = RAW_DIR / "register"
DB_PATH = DATA_DIR / "mlb_draft.db"

FIRST_DRAFT_YEAR = draft_api.FIRST_DRAFT_YEAR  # 1965
LAST_DRAFT_YEAR = 2025

DRAFT_FETCH_DELAY = 1.0  # seconds between live fetches — polite to StatsAPI

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS drafts (
    year            INTEGER NOT NULL,
    overall_pick    INTEGER NOT NULL,   -- StatsAPI's own global pick number
    round           TEXT,               -- native label: '1'..'80'+, 'C-A'/'C-B' (comp balance)
    round_sort      INTEGER,            -- 1-based index of round-group in API pick order
    round_pick      INTEGER,            -- pick's position within its own round
    bis_player_id   INTEGER,            -- Baseball Info Solutions id (kept for reference only)
    mlbam_id        INTEGER,            -- MLBAM person id; bridges to person_map
    player_name     TEXT,
    birth_date      TEXT,
    position        TEXT,
    team_id         INTEGER,            -- MLB StatsAPI team id
    team_name       TEXT,
    school_name     TEXT,
    school_class    TEXT,
    draft_type_code TEXT,               -- 'JR' = Rule 4 / June Amateur Draft in every year sampled
    is_drafted      INTEGER,
    is_pass         INTEGER,            -- defensive: no year sampled has any pass rows
    PRIMARY KEY (year, overall_pick)
);
CREATE INDEX IF NOT EXISTS idx_drafts_mlbam ON drafts(mlbam_id);
CREATE INDEX IF NOT EXISTS idx_drafts_year  ON drafts(year);

-- Lahman People.csv
CREATE TABLE IF NOT EXISTS people (
    player_id     TEXT PRIMARY KEY,   -- Lahman playerID, e.g. 'piazzmi01'
    birth_year    INTEGER,
    birth_month   INTEGER,
    birth_day     INTEGER,
    birth_city    TEXT,
    birth_country TEXT,
    birth_state   TEXT,
    death_year    INTEGER,
    death_month   INTEGER,
    death_day     INTEGER,
    death_country TEXT,
    death_state   TEXT,
    death_city    TEXT,
    name_first    TEXT,
    name_last     TEXT,
    name_given    TEXT,
    weight        INTEGER,
    height        INTEGER,
    bats          TEXT,
    throws        TEXT,
    debut         TEXT,
    bbref_id      TEXT,
    final_game    TEXT,
    retro_id      TEXT
);

-- Lahman Batting.csv
CREATE TABLE IF NOT EXISTS batting (
    player_id TEXT NOT NULL,
    year_id   INTEGER NOT NULL,
    stint     INTEGER NOT NULL,
    team_id   TEXT,
    lg_id     TEXT,
    g INTEGER, ab INTEGER, r INTEGER, h INTEGER, doubles INTEGER, triples INTEGER,
    hr INTEGER, rbi INTEGER, sb INTEGER, cs INTEGER, bb INTEGER, so INTEGER,
    ibb INTEGER, hbp INTEGER, sh INTEGER, sf INTEGER, gidp INTEGER,
    PRIMARY KEY (player_id, year_id, stint)
);
CREATE INDEX IF NOT EXISTS idx_batting_player ON batting(player_id);

-- Lahman Pitching.csv
CREATE TABLE IF NOT EXISTS pitching (
    player_id TEXT NOT NULL,
    year_id   INTEGER NOT NULL,
    stint     INTEGER NOT NULL,
    team_id   TEXT,
    lg_id     TEXT,
    w INTEGER, l INTEGER, g INTEGER, gs INTEGER, cg INTEGER, sho INTEGER, sv INTEGER,
    ipouts INTEGER, h INTEGER, er INTEGER, hr INTEGER, bb INTEGER, so INTEGER,
    baopp REAL, era REAL, ibb INTEGER, wp INTEGER, hbp INTEGER, bk INTEGER,
    bfp INTEGER, gf INTEGER, r INTEGER, sh INTEGER, sf INTEGER, gidp INTEGER,
    PRIMARY KEY (player_id, year_id, stint)
);
CREATE INDEX IF NOT EXISTS idx_pitching_player ON pitching(player_id);

-- Lahman AwardsPlayers.csv (STALE through 2021 only — see chadwick.py docstring)
CREATE TABLE IF NOT EXISTS awards_players (
    player_id TEXT NOT NULL,
    award_id  TEXT NOT NULL,
    year_id   INTEGER,
    lg_id     TEXT,
    tie       TEXT,
    notes     TEXT
);
CREATE INDEX IF NOT EXISTS idx_awards_player ON awards_players(player_id);

-- Lahman HallOfFame.csv
CREATE TABLE IF NOT EXISTS hall_of_fame (
    player_id   TEXT NOT NULL,
    year_id     INTEGER,
    voted_by    TEXT,
    ballots     INTEGER,
    needed      INTEGER,
    votes       INTEGER,
    inducted    TEXT,   -- 'Y' / 'N'
    category    TEXT,
    needed_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_hof_player   ON hall_of_fame(player_id);
CREATE INDEX IF NOT EXISTS idx_hof_inducted ON hall_of_fame(inducted);

-- mlbam_id (drafts) <-> player_id (Lahman career tables) bridge
CREATE TABLE IF NOT EXISTS person_map (
    mlbam_id     INTEGER PRIMARY KEY,
    player_id    TEXT NOT NULL,
    match_method TEXT NOT NULL,   -- 'register' | 'name_birthyear'
    matched_via  TEXT
);
CREATE INDEX IF NOT EXISTS idx_person_map_player ON person_map(player_id);

-- Career value v0 — see career_value.py docstring for the definition
CREATE TABLE IF NOT EXISTS career_value (
    player_id   TEXT PRIMARY KEY,
    batting_g   INTEGER NOT NULL DEFAULT 0,
    pitching_g  INTEGER NOT NULL DEFAULT 0,
    value_games INTEGER NOT NULL DEFAULT 0
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ── Step 1: drafts ───────────────────────────────────────────────────────────

def load_drafts(conn: sqlite3.Connection, session, start_year: int, end_year: int) -> int:
    """Fetch (or read from cache) every draft year in range and upsert into
    ``drafts``. Resumable: a year whose raw JSON is already cached is never
    re-fetched from the network."""
    import json

    DRAFT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for year in range(start_year, end_year + 1):
        cache_path = DRAFT_RAW_DIR / f"{year}.json"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            log.info("draft %d: cached", year)
        else:
            raw = draft_api.fetch_draft_year(session, year)
            cache_path.write_text(json.dumps(raw), encoding="utf-8")
            log.info("draft %d: fetched and cached", year)
            time.sleep(DRAFT_FETCH_DELAY)

        picks = draft_api.parse_draft_year(raw)
        conn.executemany(
            """INSERT INTO drafts
               (year, overall_pick, round, round_sort, round_pick, bis_player_id,
                mlbam_id, player_name, birth_date, position, team_id, team_name,
                school_name, school_class, draft_type_code, is_drafted, is_pass)
               VALUES (:year, :overall_pick, :round, :round_sort, :round_pick,
                       :bis_player_id, :mlbam_id, :player_name, :birth_date,
                       :position, :team_id, :team_name, :school_name,
                       :school_class, :draft_type_code, :is_drafted, :is_pass)
               ON CONFLICT(year, overall_pick) DO UPDATE SET
                 player_name = excluded.player_name,
                 mlbam_id    = excluded.mlbam_id""",
            picks,
        )
        conn.commit()
        total += len(picks)
        log.info("draft %d: %d picks loaded", year, len(picks))
    return total


# ── Step 2: Lahman career tables ─────────────────────────────────────────────

def _int_or_none(value):
    if value in (None, ""):
        return None
    return int(value)


def _float_or_none(value):
    if value in (None, ""):
        return None
    return float(value)


def _read_csv(path: pathlib.Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_people(conn: sqlite3.Connection, rows: list[dict]) -> int:
    records = [
        (
            r["playerID"], _int_or_none(r.get("birthYear")), _int_or_none(r.get("birthMonth")),
            _int_or_none(r.get("birthDay")), r.get("birthCity"), r.get("birthCountry"),
            r.get("birthState"), _int_or_none(r.get("deathYear")), _int_or_none(r.get("deathMonth")),
            _int_or_none(r.get("deathDay")), r.get("deathCountry"), r.get("deathState"),
            r.get("deathCity"), r.get("nameFirst"), r.get("nameLast"), r.get("nameGiven"),
            _int_or_none(r.get("weight")), _int_or_none(r.get("height")), r.get("bats"),
            r.get("throws"), r.get("debut"), r.get("bbrefID"), r.get("finalGame"), r.get("retroID"),
        )
        for r in rows if r.get("playerID")
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO people
           (player_id, birth_year, birth_month, birth_day, birth_city, birth_country,
            birth_state, death_year, death_month, death_day, death_country, death_state,
            death_city, name_first, name_last, name_given, weight, height, bats, throws,
            debut, bbref_id, final_game, retro_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        records,
    )
    conn.commit()
    return len(records)


def load_batting(conn: sqlite3.Connection, rows: list[dict]) -> int:
    records = [
        (
            r["playerID"], int(r["yearID"]), int(r["stint"]), r.get("teamID"), r.get("lgID"),
            _int_or_none(r.get("G")), _int_or_none(r.get("AB")), _int_or_none(r.get("R")),
            _int_or_none(r.get("H")), _int_or_none(r.get("2B")), _int_or_none(r.get("3B")),
            _int_or_none(r.get("HR")), _int_or_none(r.get("RBI")), _int_or_none(r.get("SB")),
            _int_or_none(r.get("CS")), _int_or_none(r.get("BB")), _int_or_none(r.get("SO")),
            _int_or_none(r.get("IBB")), _int_or_none(r.get("HBP")), _int_or_none(r.get("SH")),
            _int_or_none(r.get("SF")), _int_or_none(r.get("GIDP")),
        )
        for r in rows if r.get("playerID") and r.get("yearID") and r.get("stint")
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO batting
           (player_id, year_id, stint, team_id, lg_id, g, ab, r, h, doubles, triples,
            hr, rbi, sb, cs, bb, so, ibb, hbp, sh, sf, gidp)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        records,
    )
    conn.commit()
    return len(records)


def load_pitching(conn: sqlite3.Connection, rows: list[dict]) -> int:
    records = [
        (
            r["playerID"], int(r["yearID"]), int(r["stint"]), r.get("teamID"), r.get("lgID"),
            _int_or_none(r.get("W")), _int_or_none(r.get("L")), _int_or_none(r.get("G")),
            _int_or_none(r.get("GS")), _int_or_none(r.get("CG")), _int_or_none(r.get("SHO")),
            _int_or_none(r.get("SV")), _int_or_none(r.get("IPouts")), _int_or_none(r.get("H")),
            _int_or_none(r.get("ER")), _int_or_none(r.get("HR")), _int_or_none(r.get("BB")),
            _int_or_none(r.get("SO")), _float_or_none(r.get("BAOpp")), _float_or_none(r.get("ERA")),
            _int_or_none(r.get("IBB")), _int_or_none(r.get("WP")), _int_or_none(r.get("HBP")),
            _int_or_none(r.get("BK")), _int_or_none(r.get("BFP")), _int_or_none(r.get("GF")),
            _int_or_none(r.get("R")), _int_or_none(r.get("SH")), _int_or_none(r.get("SF")),
            _int_or_none(r.get("GIDP")),
        )
        for r in rows if r.get("playerID") and r.get("yearID") and r.get("stint")
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO pitching
           (player_id, year_id, stint, team_id, lg_id, w, l, g, gs, cg, sho, sv,
            ipouts, h, er, hr, bb, so, baopp, era, ibb, wp, hbp, bk, bfp, gf, r, sh, sf, gidp)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        records,
    )
    conn.commit()
    return len(records)


def load_awards_players(conn: sqlite3.Connection, rows: list[dict]) -> int:
    records = [
        (r["playerID"], r["awardID"], _int_or_none(r.get("yearID")), r.get("lgID"),
         r.get("tie"), r.get("notes"))
        for r in rows if r.get("playerID") and r.get("awardID")
    ]
    conn.executemany(
        "INSERT INTO awards_players (player_id, award_id, year_id, lg_id, tie, notes) VALUES (?,?,?,?,?,?)",
        records,
    )
    conn.commit()
    return len(records)


def load_hall_of_fame(conn: sqlite3.Connection, rows: list[dict]) -> int:
    records = [
        (
            r["playerID"], _int_or_none(r.get("yearid") or r.get("yearID")), r.get("votedBy"),
            _int_or_none(r.get("ballots")), _int_or_none(r.get("needed")), _int_or_none(r.get("votes")),
            r.get("inducted"), r.get("category"), r.get("needed_note"),
        )
        for r in rows if r.get("playerID")
    ]
    conn.executemany(
        """INSERT INTO hall_of_fame
           (player_id, year_id, voted_by, ballots, needed, votes, inducted, category, needed_note)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        records,
    )
    conn.commit()
    return len(records)


def load_chadwick_tables(conn: sqlite3.Connection, session) -> dict[str, int]:
    """Download (or read cached) the 5 Lahman CSVs and load all 5 tables.
    Clears + reloads each table (small, cheap, avoids partial-reload drift)."""
    paths = chadwick.fetch_lahman_csvs(session, CHADWICK_RAW_DIR)

    people_rows = _read_csv(paths["People.csv"])
    batting_rows = _read_csv(paths["Batting.csv"])
    pitching_rows = _read_csv(paths["Pitching.csv"])
    awards_rows = _read_csv(paths["AwardsPlayers.csv"])
    hof_rows = _read_csv(paths["HallOfFame.csv"])

    conn.execute("DELETE FROM people")
    conn.execute("DELETE FROM batting")
    conn.execute("DELETE FROM pitching")
    conn.execute("DELETE FROM awards_players")
    conn.execute("DELETE FROM hall_of_fame")
    conn.commit()

    counts = {
        "people": load_people(conn, people_rows),
        "batting": load_batting(conn, batting_rows),
        "pitching": load_pitching(conn, pitching_rows),
        "awards_players": load_awards_players(conn, awards_rows),
        "hall_of_fame": load_hall_of_fame(conn, hof_rows),
    }
    return counts


# ── Step 3: id bridge ────────────────────────────────────────────────────────

def load_person_map(conn: sqlite3.Connection, session) -> dict[str, int]:
    """Build person_map: primary pass via the Chadwick register, fallback
    pass via name+birth-year for drafted players the register pass missed.
    Returns match-rate stats for the report."""
    shard_paths = chadwick.fetch_register(session, REGISTER_RAW_DIR)
    register_rows: list[dict] = []
    for path in shard_paths:
        register_rows.extend(_read_csv(path))

    people_rows = [
        dict(zip(
            ("playerID", "bbrefID", "retroID", "nameFirst", "nameLast", "birthYear"),
            row,
        ))
        for row in conn.execute(
            "SELECT player_id, bbref_id, retro_id, name_first, name_last, birth_year FROM people"
        )
    ]

    bbref_to_id, retro_to_id = pm.index_people_by_bbref_retro(people_rows)
    register_mapping = pm.map_register_to_lahman(register_rows, bbref_to_id, retro_to_id)

    draft_rows = [
        dict(zip(("mlbam_id", "player_name", "birth_date"), row))
        for row in conn.execute(
            "SELECT DISTINCT mlbam_id, player_name, birth_date FROM drafts WHERE mlbam_id IS NOT NULL"
        )
    ]
    unmapped = [r for r in draft_rows if r["mlbam_id"] not in register_mapping]
    name_index = pm.index_people_by_name_birthyear(people_rows)
    fallback_mapping = pm.fallback_name_birthyear_match(unmapped, name_index)

    full_mapping = {**register_mapping, **fallback_mapping}
    conn.execute("DELETE FROM person_map")
    conn.executemany(
        "INSERT INTO person_map (mlbam_id, player_id, match_method, matched_via) VALUES (?,?,?,?)",
        [
            (mlbam_id, info["player_id"], info["match_method"], info["matched_via"])
            for mlbam_id, info in full_mapping.items()
        ],
    )
    conn.commit()

    drafted_ids = {r["mlbam_id"] for r in draft_rows}
    return {
        "register_rows_with_mlbam": len(register_mapping),
        "drafted_players_total": len(drafted_ids),
        "drafted_players_mapped_register": sum(
            1 for i in drafted_ids if full_mapping.get(i, {}).get("match_method") == "register"
        ),
        "drafted_players_mapped_fallback": len(fallback_mapping),
        "drafted_players_unmapped": len(drafted_ids) - len(full_mapping.keys() & drafted_ids),
    }


# ── Step 4: career value v0 ──────────────────────────────────────────────────

def load_career_value(conn: sqlite3.Connection) -> int:
    batting_rows = [
        {"playerID": r[0], "G": r[1]} for r in conn.execute("SELECT player_id, g FROM batting")
    ]
    pitching_rows = [
        {"playerID": r[0], "G": r[1]} for r in conn.execute("SELECT player_id, g FROM pitching")
    ]
    values = cv.compute_career_value(batting_rows, pitching_rows)

    conn.execute("DELETE FROM career_value")
    conn.executemany(
        "INSERT INTO career_value (player_id, batting_g, pitching_g, value_games) VALUES (?,?,?,?)",
        [(pid, v["batting_g"], v["pitching_g"], v["value_games"]) for pid, v in values.items()],
    )
    conn.commit()
    return len(values)


# ── Validation ───────────────────────────────────────────────────────────────

def _one_pick(conn: sqlite3.Connection, year: int, overall_pick: int | None = None, player_name: str | None = None):
    """Look up a single pick by (year, overall_pick) or (year, player_name).
    Note: a round can have several picks (one per team with a slot in it),
    so identifying "the round-62 pick" means matching the player, not just
    grabbing the first row in that round."""
    if overall_pick is not None:
        return conn.execute(
            "SELECT year, overall_pick, round, player_name, team_name, mlbam_id "
            "FROM drafts WHERE year=? AND overall_pick=?",
            (year, overall_pick),
        ).fetchone()
    return conn.execute(
        "SELECT year, overall_pick, round, player_name, team_name, mlbam_id "
        "FROM drafts WHERE year=? AND player_name=?",
        (year, player_name),
    ).fetchone()


def validate(conn: sqlite3.Connection) -> None:
    log.info("=" * 78)
    log.info("VALIDATION")
    log.info("=" * 78)

    strasburg = _one_pick(conn, 2009, overall_pick=1)
    log.info("2009 #1 overall: %s", strasburg)
    assert strasburg and strasburg[3] == "Stephen Strasburg" and "Washington" in strasburg[4], \
        f"FAILED: expected Strasburg/Washington, got {strasburg}"

    monday = _one_pick(conn, 1965, overall_pick=1)
    log.info("1965 #1 overall: %s", monday)
    assert monday and monday[3] == "Rick Monday", f"FAILED: expected Rick Monday, got {monday}"

    piazza = _one_pick(conn, 1988, player_name="Mike Piazza")
    log.info("1988 Piazza pick: %s", piazza)
    assert piazza and piazza[2] == "62" and "Los Angeles" in piazza[4], \
        f"FAILED: expected round 62 / LA Dodgers, got {piazza}"

    piazza_value = conn.execute(
        """SELECT cv.value_games FROM career_value cv
           JOIN person_map m ON m.player_id = cv.player_id
           WHERE m.mlbam_id = ?""",
        (piazza[5],),
    ).fetchone()
    log.info("Piazza mapped career value_games: %s (expect ~1912)", piazza_value)

    n_drafts = conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
    n_people = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    n_mapped_drafted = conn.execute(
        "SELECT COUNT(DISTINCT d.mlbam_id) FROM drafts d JOIN person_map m ON m.mlbam_id = d.mlbam_id"
    ).fetchone()[0]
    n_drafted_distinct = conn.execute(
        "SELECT COUNT(DISTINCT mlbam_id) FROM drafts WHERE mlbam_id IS NOT NULL"
    ).fetchone()[0]
    n_with_mlb_games = conn.execute(
        """SELECT COUNT(DISTINCT d.mlbam_id) FROM drafts d
           JOIN person_map m ON m.mlbam_id = d.mlbam_id
           JOIN career_value cv ON cv.player_id = m.player_id
           WHERE cv.value_games > 0"""
    ).fetchone()[0]

    log.info("Row counts: drafts=%d  people=%d", n_drafts, n_people)
    log.info(
        "Distinct drafted players: %d | mapped to a Lahman id: %d (%.1f%%) | "
        "with any MLB games: %d (%.1f%% of drafted, %.1f%% of mapped)",
        n_drafted_distinct, n_mapped_drafted,
        100 * n_mapped_drafted / n_drafted_distinct if n_drafted_distinct else 0,
        n_with_mlb_games,
        100 * n_with_mlb_games / n_drafted_distinct if n_drafted_distinct else 0,
        100 * n_with_mlb_games / n_mapped_drafted if n_mapped_drafted else 0,
    )
    log.info("=" * 78)
    log.info("ALL VALIDATION CHECKS PASSED")
    log.info("=" * 78)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build MLB draft + career-value SQLite DB")
    parser.add_argument("--start-year", type=int, default=FIRST_DRAFT_YEAR)
    parser.add_argument("--end-year", type=int, default=LAST_DRAFT_YEAR)
    parser.add_argument("--skip-drafts", action="store_true")
    parser.add_argument("--skip-chadwick", action="store_true")
    parser.add_argument("--skip-person-map", action="store_true")
    parser.add_argument("--skip-value", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        init_schema(conn)

        if args.validate_only:
            validate(conn)
            return

        draft_session = draft_api.make_session()
        chadwick_session = chadwick.make_session()

        if not args.skip_drafts:
            n = load_drafts(conn, draft_session, args.start_year, args.end_year)
            log.info("Drafts loaded: %d picks, years %d-%d", n, args.start_year, args.end_year)

        if not args.skip_chadwick:
            counts = load_chadwick_tables(conn, chadwick_session)
            log.info("Chadwick tables loaded: %s", counts)

        if not args.skip_person_map:
            stats = load_person_map(conn, chadwick_session)
            log.info("Person map built: %s", stats)

        if not args.skip_value:
            n = load_career_value(conn)
            log.info("Career value computed for %d players", n)

        conn.execute("ANALYZE")
        conn.commit()
        validate(conn)
    finally:
        conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    log.info("Done. %s (%.2f MB)", DB_PATH.name, size_mb)


if __name__ == "__main__":
    main()
