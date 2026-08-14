"""
Build the sumo SQLite database (schema + resumable backfill)
============================================================
Two phases, both resumable so the ~4k-request crawl can be stopped and restarted
freely (it writes progress to a ``fetched`` ledger and to the tables themselves):

  Phase 1  torikumi -> ``bouts`` + ``basho``     (every sekitori bout, by day)
  Phase 2  rikishi  -> ``rikishi`` + ``measurements`` + ``ranks``
           (one fetch per distinct wrestler discovered in Phase 1)

Usage:
    python -m sumo.build --verify                 # full: 2005 -> now
    python -m sumo.build --start 202001           # shorter window
    python -m sumo.build --limit-basho 1 --verify # smoke test (one tournament)

The DB lives in sumo/data/sumo.db and is gitignored — it is fully regenerable
from this crawl.
"""

import time
import logging
import sqlite3
import argparse
import pathlib
from datetime import date

from . import api

log = logging.getLogger("sumo.build")

DB_PATH = pathlib.Path(__file__).parent / "data" / "sumo.db"

DAYS_PER_BASHO = 15  # every modern honbasho is 15 days

SCHEMA_SQL = """
-- One row per wrestler: stable identity + bio + *latest* measurements.
CREATE TABLE IF NOT EXISTS rikishi (
    id          INTEGER PRIMARY KEY,   -- sumo-api rikishi id (stable across shikona changes)
    sumodb_id   INTEGER,
    nsk_id      INTEGER,
    shikona_en  TEXT,                  -- current ring name, romaji
    shikona_jp  TEXT,
    heya        TEXT,                  -- training stable
    birth_date  TEXT,                  -- 'YYYY-MM-DD'
    shusshin    TEXT,                  -- birthplace / origin
    debut       TEXT,                  -- 'YYYYMM' of first professional basho
    height_cm   REAL,                  -- latest recorded
    weight_kg   REAL                   -- latest recorded
);

-- Measurement CHANGE-POINTS: the wrestler's size as recorded at basho_id,
-- valid until the next row. NOT one row per tournament — see api.py note.
CREATE TABLE IF NOT EXISTS measurements (
    rikishi_id INTEGER NOT NULL,
    basho_id   TEXT NOT NULL,          -- 'YYYYMM' the measurement was recorded
    height_cm  REAL,
    weight_kg  REAL,
    PRIMARY KEY (rikishi_id, basho_id),
    FOREIGN KEY (rikishi_id) REFERENCES rikishi(id)
);

-- Full rank history (numeric rank_value: lower = higher rank; Yokozuna 1E = 101).
-- Lets the analysis control for skill/seniority, not just raw size.
CREATE TABLE IF NOT EXISTS ranks (
    rikishi_id INTEGER NOT NULL,
    basho_id   TEXT NOT NULL,
    rank_value INTEGER,
    rank       TEXT,                   -- e.g. 'Maegashira 10 East'
    PRIMARY KEY (rikishi_id, basho_id),
    FOREIGN KEY (rikishi_id) REFERENCES rikishi(id)
);

-- One row per completed sekitori bout. east/west are the two wrestlers; the
-- winner is one of them. kimarite = the deciding technique ('' or 'fusen' for
-- absences, which the analysis excludes as non-contests).
CREATE TABLE IF NOT EXISTS bouts (
    basho_id     TEXT NOT NULL,
    division     TEXT NOT NULL,        -- 'Makuuchi' | 'Juryo'
    day          INTEGER NOT NULL,     -- 1..15
    match_no     INTEGER NOT NULL,
    east_id      INTEGER NOT NULL,
    west_id      INTEGER NOT NULL,
    east_shikona TEXT,
    west_shikona TEXT,
    east_rank    TEXT,
    west_rank    TEXT,
    winner_id    INTEGER NOT NULL,
    kimarite     TEXT,
    PRIMARY KEY (basho_id, division, day, match_no)
);

-- Tournament dimension (dates enable age-at-bout).
CREATE TABLE IF NOT EXISTS basho (
    id         TEXT PRIMARY KEY,       -- 'YYYYMM'
    start_date TEXT,
    end_date   TEXT,
    location   TEXT
);

-- Award EVENTS (tied to a tournament) --------------------------------------
-- Division champions. Makuuchi yusho = the sport's top honour.
CREATE TABLE IF NOT EXISTS yusho (
    basho_id   TEXT NOT NULL,
    division   TEXT NOT NULL,          -- Makuuchi, Juryo, Makushita, ...
    rikishi_id INTEGER NOT NULL,
    PRIMARY KEY (basho_id, division)
);

-- The three special prizes (Makuuchi only). Can be co-awarded, so rikishi_id
-- is part of the key.
CREATE TABLE IF NOT EXISTS sansho (
    basho_id   TEXT NOT NULL,
    prize      TEXT NOT NULL,          -- Shukun-sho | Kanto-sho | Gino-sho
    rikishi_id INTEGER NOT NULL,
    PRIMARY KEY (basho_id, prize, rikishi_id)
);

-- Career accolade CARD (one row per wrestler, totals as-of latest data).
CREATE TABLE IF NOT EXISTS rikishi_stats (
    rikishi_id     INTEGER PRIMARY KEY,
    career_basho   INTEGER,            -- tournaments contested
    total_matches  INTEGER,
    total_wins     INTEGER,
    total_losses   INTEGER,
    total_absences INTEGER,
    yusho          INTEGER,            -- championships (all divisions)
    makuuchi_yusho INTEGER,            -- top-division championships
    juryo_yusho    INTEGER,
    sansho_total   INTEGER,            -- special prizes won
    makuuchi_basho INTEGER,            -- tournaments in the top division
    makuuchi_wins  INTEGER,
    FOREIGN KEY (rikishi_id) REFERENCES rikishi(id)
);

-- Resumability ledger: an opaque scope string per unit of work already fetched.
CREATE TABLE IF NOT EXISTS fetched (
    scope TEXT PRIMARY KEY
);

CREATE INDEX IF NOT EXISTS idx_bouts_east    ON bouts(east_id);
CREATE INDEX IF NOT EXISTS idx_bouts_west    ON bouts(west_id);
CREATE INDEX IF NOT EXISTS idx_bouts_winner  ON bouts(winner_id);
CREATE INDEX IF NOT EXISTS idx_bouts_basho   ON bouts(basho_id);
CREATE INDEX IF NOT EXISTS idx_meas_rikishi  ON measurements(rikishi_id);
CREATE INDEX IF NOT EXISTS idx_ranks_rikishi ON ranks(rikishi_id);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ── Resumability ledger ──────────────────────────────────────────────────────

def _is_fetched(conn: sqlite3.Connection, scope: str) -> bool:
    return conn.execute("SELECT 1 FROM fetched WHERE scope = ?", (scope,)).fetchone() is not None


def _mark_fetched(conn: sqlite3.Connection, scope: str) -> None:
    conn.execute("INSERT OR IGNORE INTO fetched (scope) VALUES (?)", (scope,))


# ── Phase 1: bouts ───────────────────────────────────────────────────────────

def _upsert_bouts(conn: sqlite3.Connection, bouts: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO bouts
             (basho_id, division, day, match_no, east_id, west_id,
              east_shikona, west_shikona, east_rank, west_rank, winner_id, kimarite)
           VALUES (:basho_id, :division, :day, :match_no, :east_id, :west_id,
                   :east_shikona, :west_shikona, :east_rank, :west_rank, :winner_id, :kimarite)
           ON CONFLICT(basho_id, division, day, match_no) DO UPDATE SET
             winner_id = excluded.winner_id,
             kimarite  = excluded.kimarite,
             east_rank = excluded.east_rank,
             west_rank = excluded.west_rank""",
        bouts,
    )


def _upsert_basho(conn: sqlite3.Connection, meta: dict) -> None:
    conn.execute(
        """INSERT INTO basho (id, start_date, end_date, location)
           VALUES (:id, :start_date, :end_date, :location)
           ON CONFLICT(id) DO UPDATE SET
             start_date = excluded.start_date,
             end_date   = excluded.end_date,
             location   = excluded.location""",
        meta,
    )


def scrape_bouts(conn: sqlite3.Connection, session, basho_ids: list[str], delay: float) -> int:
    """Phase 1: walk basho x division x day, filling bouts + basho. Returns the
    number of bouts inserted/updated this run."""
    total = 0
    for basho_id in basho_ids:
        basho_total = 0
        for division in api.DIVISIONS:
            for day in range(1, DAYS_PER_BASHO + 1):
                scope = f"day:{basho_id}:{division}:{day}"
                if _is_fetched(conn, scope):
                    continue
                raw = api.fetch_torikumi(session, basho_id, division, day)
                time.sleep(delay)
                bouts = api.parse_bouts(raw)
                if not bouts:
                    # No completed bouts => future/unplayed day. Don't mark
                    # fetched (so it's retried later) and stop this division.
                    break
                _upsert_basho(conn, api.parse_basho_meta(raw, basho_id))
                _upsert_bouts(conn, bouts)
                _mark_fetched(conn, scope)
                conn.commit()
                total += len(bouts)
                basho_total += len(bouts)
        if basho_total:
            log.info("  %s: %d bouts", basho_id, basho_total)
    return total


# ── Phase 2: wrestlers ───────────────────────────────────────────────────────

def _discover_rikishi_ids(conn: sqlite3.Connection) -> list[int]:
    """Distinct wrestler ids that appear in bouts but aren't yet in rikishi."""
    rows = conn.execute(
        """SELECT east_id AS id FROM bouts
           UNION
           SELECT west_id FROM bouts
           EXCEPT
           SELECT id FROM rikishi"""
    ).fetchall()
    return [r[0] for r in rows]


def _store_rikishi(conn: sqlite3.Connection, raw: dict) -> None:
    conn.execute(
        """INSERT INTO rikishi
             (id, sumodb_id, nsk_id, shikona_en, shikona_jp, heya,
              birth_date, shusshin, debut, height_cm, weight_kg)
           VALUES (:id, :sumodb_id, :nsk_id, :shikona_en, :shikona_jp, :heya,
                   :birth_date, :shusshin, :debut, :height_cm, :weight_kg)
           ON CONFLICT(id) DO UPDATE SET
             shikona_en = excluded.shikona_en,
             height_cm  = excluded.height_cm,
             weight_kg  = excluded.weight_kg""",
        api.parse_rikishi(raw),
    )
    measurements = api.parse_measurements(raw)
    if measurements:
        conn.executemany(
            """INSERT INTO measurements (rikishi_id, basho_id, height_cm, weight_kg)
               VALUES (:rikishi_id, :basho_id, :height_cm, :weight_kg)
               ON CONFLICT(rikishi_id, basho_id) DO UPDATE SET
                 height_cm = excluded.height_cm, weight_kg = excluded.weight_kg""",
            measurements,
        )
    ranks = api.parse_ranks(raw)
    if ranks:
        conn.executemany(
            """INSERT INTO ranks (rikishi_id, basho_id, rank_value, rank)
               VALUES (:rikishi_id, :basho_id, :rank_value, :rank)
               ON CONFLICT(rikishi_id, basho_id) DO UPDATE SET
                 rank_value = excluded.rank_value, rank = excluded.rank""",
            ranks,
        )


def scrape_rikishi(conn: sqlite3.Connection, session, delay: float) -> int:
    """Phase 2: fetch every not-yet-stored wrestler discovered in Phase 1.
    A wrestler that fails to fetch is logged loudly and retried on the next run
    (it simply won't be in the rikishi table yet)."""
    ids = _discover_rikishi_ids(conn)
    log.info("Phase 2: %d wrestlers to fetch", len(ids))
    stored = 0
    for i, rid in enumerate(ids, 1):
        try:
            raw = api.fetch_rikishi(session, rid)
        except Exception as exc:                       # network / 404 on one id
            log.warning("  rikishi %s failed (%s) — will retry next run", rid, exc)
            continue
        time.sleep(delay)
        _store_rikishi(conn, raw)
        conn.commit()
        stored += 1
        if i % 50 == 0:
            log.info("  ...%d/%d wrestlers", i, len(ids))
    return stored


# ── Phase 3: awards (yusho + sansho) ─────────────────────────────────────────

def scrape_awards(conn: sqlite3.Connection, session, basho_ids: list[str], delay: float) -> int:
    """Fetch each tournament's champions + special prizes. Resumable per basho."""
    total = 0
    for basho_id in basho_ids:
        scope = f"awards:{basho_id}"
        if _is_fetched(conn, scope):
            continue
        try:
            raw = api.fetch_basho(session, basho_id)
        except Exception as exc:
            log.warning("  awards %s failed (%s) — will retry next run", basho_id, exc)
            continue
        time.sleep(delay)
        yusho = api.parse_yusho(raw, basho_id)
        sansho = api.parse_sansho(raw, basho_id)
        if yusho:
            conn.executemany(
                """INSERT INTO yusho (basho_id, division, rikishi_id)
                   VALUES (:basho_id, :division, :rikishi_id)
                   ON CONFLICT(basho_id, division) DO UPDATE SET rikishi_id = excluded.rikishi_id""",
                yusho,
            )
        if sansho:
            conn.executemany(
                "INSERT OR IGNORE INTO sansho (basho_id, prize, rikishi_id) VALUES (:basho_id, :prize, :rikishi_id)",
                sansho,
            )
        _mark_fetched(conn, scope)
        conn.commit()
        total += len(yusho) + len(sansho)
    return total


# ── Phase 4: career accolade cards ───────────────────────────────────────────

def scrape_stats(conn: sqlite3.Connection, session, delay: float) -> int:
    """Fetch career totals for every wrestler that lacks a stats row (covers both
    newly-discovered wrestlers and any already stored before stats existed)."""
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM rikishi WHERE id NOT IN (SELECT rikishi_id FROM rikishi_stats)"
    ).fetchall()]
    log.info("Phase 4: %d wrestlers need career stats", len(ids))
    stored = 0
    for i, rid in enumerate(ids, 1):
        try:
            raw = api.fetch_rikishi_stats(session, rid)
        except Exception as exc:
            log.warning("  stats %s failed (%s) — will retry next run", rid, exc)
            continue
        time.sleep(delay)
        conn.execute(
            """INSERT INTO rikishi_stats
                 (rikishi_id, career_basho, total_matches, total_wins, total_losses,
                  total_absences, yusho, makuuchi_yusho, juryo_yusho, sansho_total,
                  makuuchi_basho, makuuchi_wins)
               VALUES (:rikishi_id, :career_basho, :total_matches, :total_wins, :total_losses,
                       :total_absences, :yusho, :makuuchi_yusho, :juryo_yusho, :sansho_total,
                       :makuuchi_basho, :makuuchi_wins)
               ON CONFLICT(rikishi_id) DO UPDATE SET
                 career_basho=excluded.career_basho, total_matches=excluded.total_matches,
                 total_wins=excluded.total_wins, total_losses=excluded.total_losses,
                 total_absences=excluded.total_absences, yusho=excluded.yusho,
                 makuuchi_yusho=excluded.makuuchi_yusho, juryo_yusho=excluded.juryo_yusho,
                 sansho_total=excluded.sansho_total, makuuchi_basho=excluded.makuuchi_basho,
                 makuuchi_wins=excluded.makuuchi_wins""",
            api.parse_stats(raw, rid),
        )
        conn.commit()
        stored += 1
        if i % 50 == 0:
            log.info("  ...%d/%d stats", i, len(ids))
    return stored


# ── Verify ───────────────────────────────────────────────────────────────────

def verify(conn: sqlite3.Connection) -> None:
    n_bouts = conn.execute("SELECT COUNT(*) FROM bouts").fetchone()[0]
    n_rikishi = conn.execute("SELECT COUNT(*) FROM rikishi").fetchone()[0]
    n_meas = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    span = conn.execute("SELECT MIN(basho_id), MAX(basho_id) FROM bouts").fetchone()
    log.info("bouts=%d  rikishi=%d  measurements=%d  basho span=%s..%s",
             n_bouts, n_rikishi, n_meas, span[0], span[1])
    log.info("Bouts by division:")
    for div, n in conn.execute("SELECT division, COUNT(*) FROM bouts GROUP BY division"):
        log.info("  %-9s %d", div, n)
    # Sanity check against a known fact: Hakuho (id 26 on sumo-api) should have
    # the most Makuuchi wins of anyone in the window.
    top = conn.execute(
        """SELECT r.shikona_en, COUNT(*) AS wins
           FROM bouts b JOIN rikishi r ON r.id = b.winner_id
           WHERE b.division = 'Makuuchi'
           GROUP BY b.winner_id ORDER BY wins DESC LIMIT 3"""
    ).fetchall()
    log.info("Most Makuuchi wins in window (sanity): %s",
             ", ".join(f"{name} {w}" for name, w in top))

    n_yusho, n_sansho, n_stats = (conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                  for t in ("yusho", "sansho", "rikishi_stats"))
    log.info("awards: yusho=%d  sansho=%d  stats_cards=%d", n_yusho, n_sansho, n_stats)
    if n_yusho:
        # Sanity: across a full-history build, Hakuho tops Makuuchi championships.
        top_y = conn.execute(
            """SELECT r.shikona_en, COUNT(*) AS titles
               FROM yusho y JOIN rikishi r ON r.id = y.rikishi_id
               WHERE y.division = 'Makuuchi'
               GROUP BY y.rikishi_id ORDER BY titles DESC LIMIT 3"""
        ).fetchall()
        log.info("Most Makuuchi yusho (sanity): %s",
                 ", ".join(f"{name} {t}" for name, t in top_y))


def _default_end() -> str:
    """The most recent honbasho id that has started, from today's date."""
    today = date.today()
    months = [m for m in api.BASHO_MONTHS if m <= today.month]
    if months:
        return f"{today.year}{max(months):02d}"
    return f"{today.year - 1}11"  # before January's basho: last year's Kyushu


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the sumo SQLite database")
    parser.add_argument("--start", default=api.DEFAULT_START_BASHO, help="Earliest basho YYYYMM (default 200501)")
    parser.add_argument("--end", default=None, help="Latest basho YYYYMM (default: most recent)")
    parser.add_argument("--delay", type=float, default=0.2, help="Seconds between live requests (politeness)")
    parser.add_argument("--limit-basho", type=int, default=None, help="Only the first N basho (smoke test)")
    parser.add_argument("--skip-bouts", action="store_true", help="Skip Phase 1 (bouts)")
    parser.add_argument("--skip-rikishi", action="store_true", help="Skip Phase 2 (bios)")
    parser.add_argument("--skip-awards", action="store_true", help="Skip Phase 3 (yusho/sansho)")
    parser.add_argument("--skip-stats", action="store_true", help="Skip Phase 4 (career cards)")
    parser.add_argument("--verify", action="store_true", help="Print summary counts after build")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    end = args.end or _default_end()
    basho_ids = api.enumerate_basho(args.start, end)
    if args.limit_basho:
        basho_ids = basho_ids[:args.limit_basho]
    log.info("Backfill %d basho: %s .. %s", len(basho_ids), basho_ids[0], basho_ids[-1])

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        init_schema(conn)
        session = api.make_session()
        if not args.skip_bouts:
            log.info("Phase 1: bouts")
            n = scrape_bouts(conn, session, basho_ids, args.delay)
            log.info("Phase 1 done: %d bouts inserted/updated", n)
        if not args.skip_rikishi:
            log.info("Phase 2: wrestlers")
            n = scrape_rikishi(conn, session, args.delay)
            log.info("Phase 2 done: %d wrestlers stored", n)
        if not args.skip_awards:
            log.info("Phase 3: awards (yusho + sansho)")
            n = scrape_awards(conn, session, basho_ids, args.delay)
            log.info("Phase 3 done: %d award rows", n)
        if not args.skip_stats:
            log.info("Phase 4: career accolade cards")
            n = scrape_stats(conn, session, args.delay)
            log.info("Phase 4 done: %d cards stored", n)
        conn.execute("ANALYZE")
        conn.commit()
        if args.verify:
            verify(conn)
    finally:
        conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    log.info("Done. %s (%.2f MB)", DB_PATH.name, size_mb)


if __name__ == "__main__":
    main()
