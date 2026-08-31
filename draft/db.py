"""SQLite schema + idempotent loader for the unified cross-sport draft database.

One table, every sport. A draft pick is the same shape in every league —
(year, round, overall pick, team, player, where-they-came-from) — so NBA, NFL,
NHL and MLB all normalize into `draft_picks`, discriminated by a `sport` column.
That makes cross-sport questions a single query, and keeping the per-source IDs
(`native_player_id` / `native_team_id`) means a pick can still be joined back to
that sport's box-score DB (nba.db, nfl.db) via ATTACH or a pandas merge.

Raw facts only: we store what each league's draft record says and derive analysis
(busts, steals, positional trends) at query time. Loads use INSERT OR REPLACE on
the natural key, so re-running any source converges instead of duplicating.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS draft_picks (
    sport            TEXT    NOT NULL,    -- NBA | NFL | NHL | MLB
    draft_year       INTEGER NOT NULL,
    draft_type       TEXT    NOT NULL DEFAULT 'regular',  -- regular | supplemental | territorial | hardship
    round            INTEGER,
    pick_in_round    INTEGER,
    overall_pick     INTEGER NOT NULL,    -- selection number; sources without one get a derived sequence
    team_abbr        TEXT,                -- normalized stable franchise code (see teams.py)
    team_name        TEXT,                -- as-drafted team name, kept for provenance
    native_team_id   TEXT,                -- source team id (join key to the sport's box-score DB)
    player_name      TEXT,
    native_player_id TEXT,                -- source player id: nba PERSON_ID, nfl gsis_id, nhl playerId, mlb person.id
    position         TEXT,                -- raw, as the source labels it
    origin           TEXT,                -- college / school / junior club / country of origin
    origin_type      TEXT,                -- College/University, Other Team/Club, amateur league, ...
    source           TEXT    NOT NULL,    -- nba_api | nflverse | nhl_records | mlb_statsapi
    PRIMARY KEY (sport, draft_year, draft_type, overall_pick)
);

CREATE INDEX IF NOT EXISTS idx_draft_player    ON draft_picks(native_player_id);
CREATE INDEX IF NOT EXISTS idx_draft_sportyear ON draft_picks(sport, draft_year);
CREATE INDEX IF NOT EXISTS idx_draft_team      ON draft_picks(sport, team_abbr);
CREATE INDEX IF NOT EXISTS idx_draft_name      ON draft_picks(player_name);
"""

# Exact column order rows are written in. Adapters may carry extra keys; we
# project to just these before inserting.
COLUMNS = [
    "sport", "draft_year", "draft_type", "round", "pick_in_round", "overall_pick",
    "team_abbr", "team_name", "native_team_id", "player_name", "native_player_id",
    "position", "origin", "origin_type", "source",
]

# The natural primary key. INSERT OR REPLACE on this is what makes re-runs converge.
KEY = ("sport", "draft_year", "draft_type", "overall_pick")


def connect(db_path: Path | str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def assert_unique_keys(rows: list[dict], sport: str) -> None:
    """Fail loud if two parsed rows share a natural key.

    INSERT OR REPLACE would silently let the second row overwrite the first, so a
    source that numbers two real selections identically (territorial picks with
    overall_pick=0, an overlapping supplemental draft) would lose data without a
    peep. We refuse to load until the adapter disambiguates them.
    """
    seen: dict[tuple, dict] = {}
    for r in rows:
        k = tuple(r.get(c) for c in KEY)
        if k in seen:
            raise ValueError(
                f"{sport}: duplicate draft key {dict(zip(KEY, k))} — "
                f"{seen[k].get('player_name')!r} vs {r.get('player_name')!r}. "
                "Two picks share a natural key; fix the adapter's "
                "overall_pick / draft_type derivation before loading."
            )
        seen[k] = r


def load(conn: sqlite3.Connection, rows: list[dict], *, sport: str) -> int:
    """Idempotently upsert one sport's parsed draft rows. Returns rows written."""
    if not rows:
        log.warning("%s: no rows to load", sport)
        return 0
    assert_unique_keys(rows, sport)
    placeholders = ",".join("?" * len(COLUMNS))
    sql = f"INSERT OR REPLACE INTO draft_picks ({','.join(COLUMNS)}) VALUES ({placeholders})"
    conn.executemany(sql, [tuple(r.get(c) for c in COLUMNS) for r in rows])
    conn.commit()
    return len(rows)


def loaded_years(conn: sqlite3.Connection, sport: str) -> set[int]:
    """Years that already have at least one pick for this sport (resume support)."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT draft_year FROM draft_picks WHERE sport = ?", (sport,))}


def summary(conn: sqlite3.Connection) -> dict:
    out = {"total": conn.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0],
           "by_sport": {}}
    for sport, n, lo, hi in conn.execute(
            "SELECT sport, COUNT(*), MIN(draft_year), MAX(draft_year) "
            "FROM draft_picks GROUP BY sport ORDER BY sport"):
        out["by_sport"][sport] = {"picks": n, "year_min": lo, "year_max": hi}
    return out
