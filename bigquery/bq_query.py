"""Run a BigQuery query with a cost estimate first and a hard cap always.

    . C:\\Users\\ericb\\Github\\.claude\\ops\\gcp-credentials.ps1
    python bq_query.py --file q.sql
    python bq_query.py --sql "SELECT ..." --max-gb 5
    python bq_query.py --estimate-only --file q.sql
    python bq_query.py --usage                  # month-to-date vs the free 1 TB

WHY THIS EXISTS RATHER THAN JUST USING `bq query`
BigQuery bills by bytes SCANNED, not rows returned, and the free tier is 1 TB a
month. A single careless `SELECT *` over an unpartitioned fact table can spend a
meaningful slice of the month in one keystroke, and nothing warns you first.

So every query here goes through two gates:

1. **Dry run.** Costs nothing, returns exactly how many bytes the real query
   would scan. Printed before anything runs.
2. **maximum_bytes_billed.** A HARD server-side cap - BigQuery cancels the job
   rather than exceeding it. This is the actual protection: the dry run informs,
   the cap enforces. A dry run alone would be advisory, and advisory limits do
   not survive a distracted afternoon.

The free-tier percentages below are guidance, not a limit anyone enforces. The
real ceiling is the cap, plus a billing budget alert in the console.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery

LOG = logging.getLogger("bq")

GIB = 1024**3
TIB = 1024**4
FREE_TIER_BYTES = TIB  # 1 TiB of query processing per month, always free.
DEFAULT_MAX_GB = 10.0

USAGE_SQL = """
SELECT
  COALESCE(SUM(total_bytes_billed), 0) AS bytes_billed,
  COUNT(*) AS jobs
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH)
  AND job_type = 'QUERY'
  AND state = 'DONE'
"""


def require_credentials() -> str:
    key = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project = os.getenv("GCP_PROJECT")
    if not key or not project:
        sys.exit(
            "GOOGLE_APPLICATION_CREDENTIALS / GCP_PROJECT are not set.\n"
            "  . C:\\Users\\ericb\\Github\\.claude\\ops\\gcp-credentials.ps1"
        )
    return project


def human(nbytes: int) -> str:
    if nbytes >= GIB:
        return f"{nbytes / GIB:.2f} GiB"
    return f"{nbytes / (1024 * 1024):.1f} MiB"


def estimate(client: bigquery.Client, sql: str) -> int:
    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=cfg)
    return job.total_bytes_processed or 0


def show_usage(client: bigquery.Client) -> int:
    """Month-to-date bytes billed, straight from BigQuery rather than a local tally.

    A local counter would drift the moment a query ran from the console or the
    bq CLI; INFORMATION_SCHEMA is the same source Google bills from.
    """
    try:
        row = next(iter(client.query(USAGE_SQL).result()))
    except GoogleAPIError as err:
        LOG.error("could not read INFORMATION_SCHEMA: %s", err)
        LOG.error("the service account needs roles/bigquery.resourceViewer for this.")
        return 1
    used = int(row["bytes_billed"])
    pct = 100.0 * used / FREE_TIER_BYTES
    LOG.info("month to date: %s billed across %s queries", human(used), f"{row['jobs']:,}")
    LOG.info("free tier:     %s of 1 TiB (%.2f%%)", human(used), pct)
    if pct >= 80:
        LOG.warning("over 80%% of the free monthly allowance is gone.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--sql")
    src.add_argument("--file", type=Path)
    ap.add_argument("--max-gb", type=float, default=DEFAULT_MAX_GB,
                    help=f"hard cap on bytes billed (default {DEFAULT_MAX_GB} GiB)")
    ap.add_argument("--estimate-only", action="store_true")
    ap.add_argument("--usage", action="store_true", help="month-to-date usage, then exit")
    ap.add_argument("--max-rows", type=int, default=50)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    project = require_credentials()
    client = bigquery.Client(project=project)

    if args.usage:
        return show_usage(client)

    if not args.sql and not args.file:
        ap.error("one of --sql / --file / --usage is required")
    sql = args.sql if args.sql else args.file.read_text(encoding="utf-8")

    try:
        scanned = estimate(client, sql)
    except GoogleAPIError as err:
        # A dry run also validates syntax and permissions, so this is where most
        # mistakes surface - before anything is billed.
        LOG.error("query rejected at dry run: %s", err)
        return 1

    cap_bytes = int(args.max_gb * GIB)
    LOG.info("estimated scan: %s  (%.3f%% of the monthly free tier)",
             human(scanned), 100.0 * scanned / FREE_TIER_BYTES)
    LOG.info("hard cap:       %.1f GiB", args.max_gb)

    if scanned > cap_bytes:
        LOG.error(
            "REFUSED: the estimate exceeds the cap. Add a date predicate (both fact "
            "tables require one), select fewer columns, or raise --max-gb deliberately."
        )
        return 2

    if args.estimate_only:
        LOG.info("--estimate-only: not running.")
        return 0

    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=cap_bytes)
    try:
        job = client.query(sql, job_config=cfg)
        rows = list(job.result(max_results=args.max_rows))
    except GoogleAPIError as err:
        LOG.error("query failed: %s", err)
        return 1

    LOG.info("actual billed:  %s\n", human(job.total_bytes_billed or 0))
    if not rows:
        LOG.info("(no rows)")
        return 0

    headers = list(rows[0].keys())
    widths = [max(len(h), *(len(str(r[h])) for r in rows)) for h in headers]
    LOG.info("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    LOG.info("  ".join("-" * w for w in widths))
    for r in rows:
        LOG.info("  ".join(str(r[h]).ljust(w) for h, w in zip(headers, widths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
