"""NFL draft picks (1980-present) from nflverse `draft_picks` (Pro Football
Reference sourced, via nflreadr's release channel).

Unlike pull.py (which goes through nflreadpy's own R-package-style cache),
this hits the nflverse-data GitHub release asset directly so the raw CSV is
cached under our own data/raw/ (no pyarrow-only parquet path needed -- CSV is
published alongside it). One-shot full-table load: the source ships the whole
history in a single file, so there's no per-season delete+insert like pull.py.

    python -m nfl.draft_ingest              # download (if not cached) + load `drafts`
    python -m nfl.draft_ingest --refresh     # force re-download the cached CSV
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sqlite3
import time

import pandas as pd
import requests

from nfl import pull

log = logging.getLogger(__name__)

DRAFT_PICKS_URL = "https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv"
RAW_DIR = pull.PKG_DIR / "data" / "raw"
RAW_PATH = RAW_DIR / "draft_picks.csv"
TABLE = "drafts"

# Columns the nflverse draft_picks CSV is expected to carry (verified 2026-07-20
# against the live release asset). Fail loud if the source drops/renames one of
# these rather than silently loading a thinner table.
EXPECTED_COLUMNS = {
    "season", "round", "pick", "team", "gsis_id", "pfr_player_id", "cfb_player_id",
    "pfr_player_name", "hof", "position", "category", "side", "college", "age", "to",
    "allpro", "probowls", "seasons_started", "w_av", "car_av", "dr_av", "games",
}

# Known-good (season, overall pick) -> player spot checks. If these don't match
# after a load, suspect a column shift / mis-parse, not the reference facts.
VALIDATION_CASES = [
    (1998, 1, "Peyton Manning", "IND"),
    (2000, 199, "Tom Brady", "NWE"),
    (1983, 27, "Dan Marino", "MIA"),
]


def _download_with_retry(url: str, attempts: int = 3, timeout: int = 60) -> bytes:
    """GET url, retrying transient failures (network errors, 429, 5xx) with backoff.

    Non-transient 4xx (e.g. 404) fails immediately -- a retry can't fix a bad URL.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            log.warning("download attempt %d/%d errored: %s", attempt, attempts, exc)
        else:
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = requests.exceptions.HTTPError(f"transient HTTP {resp.status_code}")
                log.warning("download attempt %d/%d: transient HTTP %d", attempt, attempts, resp.status_code)
            else:
                resp.raise_for_status()  # non-transient 4xx -> raise now, no retry
                return resp.content
        if attempt < attempts:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to download {url} after {attempts} attempts") from last_exc


def fetch_raw(refresh: bool = False) -> pathlib.Path:
    """Return the cached CSV path, downloading (with retry) only if missing/--refresh."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if RAW_PATH.exists() and not refresh:
        log.info("using cached %s", RAW_PATH)
        return RAW_PATH
    log.info("downloading %s", DRAFT_PICKS_URL)
    content = _download_with_retry(DRAFT_PICKS_URL)
    RAW_PATH.write_bytes(content)
    log.info("cached %d bytes -> %s", len(content), RAW_PATH)
    return RAW_PATH


def load(conn: sqlite3.Connection, csv_path: pathlib.Path) -> int:
    """DROP+recreate `drafts` from the cached CSV. Idempotent; fails loud on schema drift."""
    df = pd.read_csv(csv_path, low_memory=False)
    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"draft_picks schema surprise -- missing expected columns: {sorted(missing)} "
            f"(got: {sorted(df.columns)})"
        )
    conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
    df.to_sql(TABLE, conn, if_exists="replace", index=False)
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_season ON {TABLE}(season)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_season_pick ON {TABLE}(season, pick)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_pfr_player_id ON {TABLE}(pfr_player_id)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_gsis_id ON {TABLE}(gsis_id)")
    conn.commit()
    return len(df)


def validate(conn: sqlite3.Connection) -> None:
    """Spot-check known picks, then print row count / season range / w_av coverage / team codes."""
    failures = []
    for season, pick, expected_name, expected_team in VALIDATION_CASES:
        row = conn.execute(
            f"SELECT pfr_player_name, team FROM {TABLE} WHERE season=? AND pick=?", (season, pick)
        ).fetchone()
        if row is None:
            failures.append(f"{season} overall #{pick}: no row found (expected {expected_name})")
            continue
        name, team = row
        if name != expected_name or team != expected_team:
            failures.append(
                f"{season} overall #{pick}: got {name!r}/{team!r}, expected {expected_name!r}/{expected_team!r}"
            )
        else:
            log.info("VALIDATED %d overall #%d = %s (%s)", season, pick, name, team)
    if failures:
        raise AssertionError("draft validation failed:\n" + "\n".join(failures))

    n = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    lo, hi = conn.execute(f"SELECT MIN(season), MAX(season) FROM {TABLE}").fetchone()
    nn_wav = conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE w_av IS NOT NULL").fetchone()[0]
    nn_carav = conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE car_av IS NOT NULL").fetchone()[0]
    teams = [r[0] for r in conn.execute(f"SELECT DISTINCT team FROM {TABLE} ORDER BY team")]
    log.info("drafts: %d rows, seasons %d-%d", n, lo, hi)
    log.info("w_av non-null: %d/%d (%.1f%%); car_av non-null: %d/%d (%.1f%%)",
              nn_wav, n, 100 * nn_wav / n, nn_carav, n, 100 * nn_carav / n)
    log.info("distinct team codes (%d): %s", len(teams), teams)


def main() -> None:
    ap = argparse.ArgumentParser(description="Load nflverse draft_picks (PFR) into nfl.db `drafts`")
    ap.add_argument("--db", default=str(pull.DB_PATH))
    ap.add_argument("--refresh", action="store_true", help="force re-download even if cached")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    csv_path = fetch_raw(refresh=args.refresh)
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        n = load(conn, csv_path)
        log.info("loaded %d rows into %s", n, TABLE)
        validate(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
