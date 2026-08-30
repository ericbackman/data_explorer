"""Show TiDB choosing between its row store and its columnar store.

    . C:\\Users\\ericb\\Github\\.claude\\ops\\tidb-env.ps1
    python htap_demo.py                  # the full comparison
    python htap_demo.py --check-replica   # is TiFlash built yet?

THE CLAIM BEING TESTED
TiDB keeps two physical representations of ONE table - TiKV (row) and TiFlash
(columnar) - and the optimizer picks per query. If that is real, then the same
analytical SQL should produce a visibly different plan and a materially
different runtime depending on which engine it is allowed to read from, with no
change to the table, no ETL, and no second system.

This script proves or disproves that on Eric's own data rather than repeating
the marketing claim. `tidb_isolation_read_engines` restricts which engines the
optimizer may consider, so the same query can be run each way.

The timings are indicative, not a benchmark: TiDB Cloud Starter auto-scales
compute, so a cold instance inflates the first query. Each statement is run once
to warm it and then timed over several runs, and the MEDIAN is reported - but
the PLAN is the real evidence, because it is deterministic and the timing is not.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time

from tidb_connect import connect, server_version

LOG = logging.getLogger("htap")

# Full-table aggregate: no index helps, every row must be read. This is the shape
# columnar storage exists for, and it touches only 3 of 28 columns - which is
# precisely where a column store wins, because a row store must still read whole
# rows off disk to get at them.
ANALYTICAL_SQL = """
SELECT season,
       COUNT(*)        AS games,
       AVG(pts)        AS avg_pts,
       AVG(plus_minus) AS avg_pm
FROM player_game
WHERE season_type = 'Regular Season'
GROUP BY season
ORDER BY season DESC
"""

# Point lookup: one player's most recent games. This is what the row store and
# the (player_id, game_date) index are for, and it should stay fast regardless.
OLTP_SQL = """
SELECT game_date, matchup, pts, reb, ast
FROM player_game
WHERE player_id = %s
ORDER BY game_date DESC
LIMIT 10
"""

RUNS = 5


def check_replica(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT PROGRESS, AVAILABLE FROM information_schema.tiflash_replica "
            "WHERE TABLE_NAME = 'player_game'"
        )
        row = cur.fetchone()
    if not row:
        LOG.warning("no TiFlash replica on player_game - run load.py (without --skip-tiflash)")
        return False
    progress, available = float(row[0] or 0), int(row[1] or 0)
    LOG.info("TiFlash replica: progress=%.0f%%  available=%s", progress * 100, bool(available))
    return available == 1


def set_engines(conn, engines: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"SET SESSION tidb_isolation_read_engines = '{engines}'")


def plan_engines(conn, sql: str, params: tuple = ()) -> tuple[str, set[str]]:
    """Return the plan text and which storage engines it mentions."""
    with conn.cursor() as cur:
        cur.execute("EXPLAIN " + sql, params)
        rows = cur.fetchall()
    text = "\n".join("  ".join(str(c) for c in r) for r in rows)
    engines = set()
    for token, label in (("tiflash", "tiflash"), ("tikv", "tikv"), ("cop[tiflash]", "tiflash")):
        if token in text.lower():
            engines.add(label)
    return text, engines


def timed(conn, sql: str, params: tuple = (), runs: int = RUNS) -> float:
    """Median wall-clock seconds, after one discarded warm-up run."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cur.fetchall()
        samples = []
        for _ in range(runs):
            start = time.perf_counter()
            cur.execute(sql, params)
            cur.fetchall()
            samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check-replica", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = connect()
    try:
        LOG.info("TiDB: %s\n", server_version(conn))

        available = check_replica(conn)
        if args.check_replica:
            return 0 if available else 1
        if not available:
            LOG.error("\nTiFlash is not available yet; the comparison would be meaningless.")
            return 1

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM player_game")
            LOG.info("player_game rows: %s\n", f"{cur.fetchone()[0]:,}")

        LOG.info("=" * 68)
        LOG.info("ANALYTICAL: full-table aggregate, 3 of 28 columns")
        LOG.info("=" * 68)

        results = {}
        for label, engines in (("row store (TiKV only)", "tikv"),
                               ("columnar allowed (TiKV+TiFlash)", "tikv,tiflash")):
            set_engines(conn, engines)
            plan, used = plan_engines(conn, ANALYTICAL_SQL)
            secs = timed(conn, ANALYTICAL_SQL)
            results[label] = (secs, used)
            LOG.info("\n%s", label)
            LOG.info("  engines in plan: %s", ", ".join(sorted(used)) or "(none identified)")
            LOG.info("  median of %d runs: %.3f s", RUNS, secs)
            LOG.info("  plan:\n%s", "\n".join("    " + ln for ln in plan.splitlines()[:6]))

        row_secs = results["row store (TiKV only)"][0]
        col_secs = results["columnar allowed (TiKV+TiFlash)"][0]
        col_used = results["columnar allowed (TiKV+TiFlash)"][1]

        LOG.info("\n" + "-" * 68)
        if "tiflash" in col_used:
            LOG.info("The optimizer chose TiFlash when allowed to.")
            if col_secs < row_secs:
                LOG.info("Columnar was %.1fx faster (%.3fs vs %.3fs).",
                         row_secs / col_secs, col_secs, row_secs)
            else:
                # Report it rather than bury it - at 1.48M rows on an auto-scaling
                # instance the row store can genuinely win, and claiming otherwise
                # would be dishonest.
                LOG.info("Columnar was NOT faster here (%.3fs vs %.3fs) - at this row "
                         "count the row store can win; the plan change is the real point.",
                         col_secs, row_secs)
        else:
            LOG.info("The optimizer did NOT choose TiFlash even when allowed. "
                     "Check the replica is available and statistics are current "
                     "(ANALYZE TABLE player_game).")

        LOG.info("\n" + "=" * 68)
        LOG.info("TRANSACTIONAL: one player's last 10 games")
        LOG.info("=" * 68)
        set_engines(conn, "tikv,tiflash")
        # LeBron James, nba_api person id.
        plan, used = plan_engines(conn, OLTP_SQL, (2544,))
        secs = timed(conn, OLTP_SQL, (2544,))
        LOG.info("  engines in plan: %s", ", ".join(sorted(used)) or "(none identified)")
        LOG.info("  median of %d runs: %.4f s", RUNS, secs)
        LOG.info("  plan:\n%s", "\n".join("    " + ln for ln in plan.splitlines()[:4]))
        LOG.info("\nSame table, same instant, both workloads - which is the whole")
        LOG.info("argument for HTAP over a Postgres-plus-warehouse pair.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
