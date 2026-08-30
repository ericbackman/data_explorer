"""Create the schema and load player_game into TiDB, then add a TiFlash replica.

    . C:\\Users\\ericb\\Github\\.claude\\ops\\tidb-env.ps1
    python load.py --counts-only     # what would load, touching nothing
    python load.py                   # schema + 1.48M rows + TiFlash replica
    python load.py --skip-tiflash    # row store only

The TiFlash step is the point of using TiDB at all: ONE `ALTER TABLE ... SET
TIFLASH REPLICA 1` gives the same table a columnar copy, kept in sync by TiDB
itself. There is no ETL, no second system, and no window where the two
representations disagree - which is exactly what you would be building by hand
if you were syncing Postgres to a warehouse.

Replica building is ASYNCHRONOUS. The script polls until it reports available,
because an EXPLAIN run too early will simply not choose TiFlash and the demo
would look like it failed when it had merely not finished.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

import pymysql

from tidb_connect import connect, server_version

LOG = logging.getLogger("load")

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "nba" / "data" / "nba.db"
SCHEMA_FILE = HERE / "schema" / "001_player_game.sql"

# 2k rows per multi-row INSERT. Larger batches are faster until they collide with
# TiDB's transaction size limits; this stays comfortably under.
BATCH = 2000

COLUMNS = [
    "game_id", "player_id", "team_id", "season", "season_type", "game_date",
    "matchup", "wl", "min", "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
    "ftm", "fta", "ft_pct", "oreb", "dreb", "reb", "ast", "stl", "blk",
    "tov", "pf", "pts", "plus_minus",
]

SELECT_SQL = f"SELECT {', '.join(COLUMNS)} FROM player_game"


def apply_schema(conn) -> None:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    # Split on ';' at statement level - these are simple DDL statements with no
    # embedded semicolons, so a full parser would be overkill.
    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
    with conn.cursor() as cur:
        for stmt in statements:
            try:
                cur.execute(stmt)
            except pymysql.err.OperationalError as err:
                # 1061 = duplicate key name: the CREATE INDEX already ran. That is
                # the one error re-running should tolerate; anything else is real.
                if err.args[0] == 1061:
                    continue
                raise
    LOG.info("schema applied (%d statements)", len(statements))


def load_rows(conn, rows_iter, total_hint: int) -> int:
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    sql = f"INSERT INTO player_game ({', '.join(COLUMNS)}) VALUES ({placeholders})"
    loaded = 0
    with conn.cursor() as cur:
        batch: list[tuple] = []
        for row in rows_iter:
            batch.append(row)
            if len(batch) >= BATCH:
                cur.executemany(sql, batch)
                loaded += len(batch)
                batch = []
                if loaded % (BATCH * 25) == 0:
                    LOG.info("  %s / %s rows", f"{loaded:,}", f"{total_hint:,}")
        if batch:
            cur.executemany(sql, batch)
            loaded += len(batch)
    return loaded


def enable_tiflash(conn, timeout_s: int = 900) -> bool:
    """Add a columnar replica and wait for it to finish building."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE player_game SET TIFLASH REPLICA 1")
    LOG.info("TiFlash replica requested; waiting for it to build ...")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT PROGRESS, AVAILABLE FROM information_schema.tiflash_replica "
                "WHERE TABLE_NAME = 'player_game'"
            )
            row = cur.fetchone()
        if row:
            progress, available = float(row[0] or 0), int(row[1] or 0)
            if available == 1:
                LOG.info("TiFlash replica AVAILABLE")
                return True
            LOG.info("  building ... %.0f%%", progress * 100)
        time.sleep(15)

    LOG.warning("TiFlash replica did not become available within %ds", timeout_s)
    LOG.warning("It may still finish; re-check with htap_demo.py --check-replica")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--counts-only", action="store_true")
    ap.add_argument("--skip-tiflash", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.db.exists():
        LOG.error("source database not found: %s", args.db)
        return 1

    src = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        total = src.execute("SELECT count(*) FROM player_game").fetchone()[0]
        LOG.info("source rows: %s", f"{total:,}")
        if args.counts_only:
            LOG.info("--counts-only: nothing written.")
            return 0

        conn = connect()
        LOG.info("connected to TiDB: %s", server_version(conn))
        try:
            apply_schema(conn)

            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM player_game")
                existing = cur.fetchone()[0]
            if existing:
                # Re-running should be idempotent, not additive - the PK would
                # reject duplicates anyway, but failing 700k rows in is a poor way
                # to find that out.
                LOG.info("table already holds %s rows; truncating first", f"{existing:,}")
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE TABLE player_game")

            LOG.info("loading ...")
            loaded = load_rows(conn, src.execute(SELECT_SQL), total)
            LOG.info("loaded %s rows", f"{loaded:,}")

            if loaded != total:
                LOG.error("row count mismatch: read %s, loaded %s", f"{total:,}", f"{loaded:,}")
                return 1

            if not args.skip_tiflash:
                enable_tiflash(conn)
        finally:
            conn.close()
    finally:
        src.close()

    LOG.info("\ndone. Run htap_demo.py to see the optimizer pick between engines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
