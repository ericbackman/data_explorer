"""NBA injuries — credit-free, from ESPN's free public API.

Pro Sports Transactions (the deep historical archive) sits behind Cloudflare, so
it can't be scraped credit-free. ESPN's open injuries feed gives the *current*
league-wide injury list instead — exactly the live-betting signal (who is OUT
tonight) that nba_api has no endpoint for.

This is a SNAPSHOT source: each run records the current injuries stamped with
pulled_at, mirroring odds_history.db. Run it on a schedule and the snapshots
accumulate into the per-game availability history a backtest needs — going
forward. (Past seasons need PST via Firecrawl, or a pre-extracted dataset.)

    python -m nba.injuries
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pathlib
import sqlite3
import time

import requests

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent
DB_PATH = PKG_DIR / "data" / "nba.db"

# Identify honestly rather than posing as a browser — this is a low-volume,
# personal-use client and the operator should be able to tell who we are.
USER_AGENT = "data_explorer/nba (+https://github.com/ericbackman/data_explorer)"
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
TIMEOUT_S = 30
MAX_RETRIES = 4
BACKOFF_BASE_S = 2.0

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS injuries (
    pulled_at    TEXT NOT NULL,      -- UTC ISO timestamp of this snapshot
    team_abbr    TEXT,
    team_name    TEXT,
    athlete_id   TEXT,
    player_name  TEXT,
    position     TEXT,
    status       TEXT,               -- Out / Day-To-Day / etc.
    injury_type  TEXT,               -- e.g. Ankle, Knee
    injury_date  TEXT,
    comment      TEXT,
    PRIMARY KEY (pulled_at, athlete_id)
);
CREATE INDEX IF NOT EXISTS idx_inj_player ON injuries(player_name);
CREATE INDEX IF NOT EXISTS idx_inj_status ON injuries(status);
CREATE INDEX IF NOT EXISTS idx_inj_pulled ON injuries(pulled_at);
"""


def fetch_injuries() -> dict:
    """GET the ESPN injuries feed with timeout + transient retry. Fails loud."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(ESPN_INJURIES_URL, timeout=TIMEOUT_S,
                             headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            backoff = BACKOFF_BASE_S ** attempt
            log.warning("ESPN fetch failed (%d/%d): %s — retrying in %.1fs",
                        attempt, MAX_RETRIES, e, backoff)
            time.sleep(backoff)
    raise RuntimeError(f"ESPN injuries fetch failed after {MAX_RETRIES} attempts") from last_err


def parse_injuries(payload: dict, pulled_at: str) -> list[dict]:
    """ESPN injuries payload -> flat snapshot rows. Defensive .get() chains so a
    missing optional field never crashes the run."""
    rows = []
    for team in payload.get("injuries", []):
        team_name = team.get("displayName")
        team_abbr = team.get("abbreviation")
        for it in team.get("injuries", []):
            athlete = it.get("athlete") or {}
            details = it.get("details") or {}
            pos = (athlete.get("position") or {}).get("abbreviation")
            rows.append({
                "pulled_at": pulled_at,
                "team_abbr": team_abbr,
                "team_name": team_name,
                "athlete_id": str(athlete.get("id")) if athlete.get("id") else athlete.get("displayName"),
                "player_name": athlete.get("displayName"),
                "position": pos,
                "status": it.get("status"),
                "injury_type": details.get("type") or (it.get("type") or {}).get("name"),
                "injury_date": it.get("date"),
                "comment": it.get("shortComment") or it.get("longComment"),
            })
    return rows


_COLS = ["pulled_at", "team_abbr", "team_name", "athlete_id", "player_name",
         "position", "status", "injury_type", "injury_date", "comment"]


def load(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executescript(SCHEMA_SQL)
    placeholders = ",".join("?" * len(_COLS))
    conn.executemany(
        f"INSERT OR REPLACE INTO injuries ({','.join(_COLS)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in _COLS) for r in rows],
    )
    conn.commit()
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot current NBA injuries from ESPN (free)")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pulled_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    payload = fetch_injuries()
    rows = parse_injuries(payload, pulled_at)
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    n = load(conn, rows)
    snapshots = conn.execute("SELECT COUNT(DISTINCT pulled_at) FROM injuries").fetchone()[0]
    conn.close()
    log.info("snapshot %s: %d injuries recorded (%d snapshot(s) total in DB)",
             pulled_at, n, snapshots)


if __name__ == "__main__":
    main()
