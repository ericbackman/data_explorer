"""Load the exported Parquet files into BigQuery, partitioned and clustered.

Run `export_to_parquet.py` first, and dot-source the credentials:

    . C:\\Users\\ericb\\Github\\.claude\\ops\\gcp-credentials.ps1
    python load_to_bigquery.py --dry-run     # show the plan, touch nothing
    python load_to_bigquery.py

WHY PARTITION AND CLUSTER AT ALL
BigQuery has no indexes and bills by bytes SCANNED, so the physical layout of a
table IS its performance and cost model - there is no second lever. An
unpartitioned `play_by_play` costs a full 18.3M-row scan for every query,
against a 1 TB/month free allowance. Partitioned on game_date and clustered on
team, a single-season query reads a small fraction of that.

MONTHLY, NOT DAILY
The data starts in 1946. ~80 years of daily partitions is ~29,000, past
BigQuery's 10,000-partition ceiling, so the load would fail. Monthly is ~960 and
still prunes a season query hard.

`require_partition_filter` is set on both fact tables ON PURPOSE: a query with no
date predicate is REJECTED rather than quietly scanning everything. That is the
single most effective guard against burning the free tier by accident.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery

LOG = logging.getLogger("load")

HERE = Path(__file__).resolve().parent
DEFAULT_EXPORT = HERE / "export"
DATASET = "nba"
LOCATION = "US"  # BigQuery's free tier applies in US multi-region.


class TableSpec:
    def __init__(self, name: str, partition_on: str | None = None, cluster_on: tuple[str, ...] = ()):
        self.name = name
        self.partition_on = partition_on
        self.cluster_on = cluster_on


# `games` is a 73k-row dimension - partitioning it would add pruning overhead for
# no benefit, so it is left flat and clustered only.
TABLES = [
    TableSpec("games", cluster_on=("season", "season_type")),
    TableSpec("player_game", partition_on="game_date", cluster_on=("team_id", "season_type")),
    TableSpec("play_by_play", partition_on="game_date", cluster_on=("team_id", "action_type")),
]


def require_credentials() -> str:
    """Fail loudly and specifically rather than letting the client library guess."""
    key = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project = os.getenv("GCP_PROJECT")
    if not key or not project:
        sys.exit(
            "GOOGLE_APPLICATION_CREDENTIALS / GCP_PROJECT are not set.\n"
            "Dot-source the credential reader first:\n"
            "  . C:\\Users\\ericb\\Github\\.claude\\ops\\gcp-credentials.ps1"
        )
    if not Path(key).exists():
        sys.exit(f"GOOGLE_APPLICATION_CREDENTIALS points at a missing file: {key}")
    return project


def build_job_config(spec: TableSpec) -> bigquery.LoadJobConfig:
    cfg = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        # Replace, so re-running is idempotent instead of appending duplicates.
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    if spec.partition_on:
        cfg.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.MONTH,
            field=spec.partition_on,
            require_partition_filter=True,
        )
    if spec.cluster_on:
        cfg.clustering_fields = list(spec.cluster_on)
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT)
    ap.add_argument("--dataset", default=DATASET)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--tables", nargs="*", default=[t.name for t in TABLES])
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    project = require_credentials()

    specs = [t for t in TABLES if t.name in args.tables]
    missing = [s.name for s in specs if not (args.export_dir / f"{s.name}.parquet").exists()]
    if missing:
        LOG.error("missing Parquet for %s - run export_to_parquet.py first", ", ".join(missing))
        return 1

    LOG.info("project: %s   dataset: %s   location: %s", project, args.dataset, LOCATION)
    for s in specs:
        path = args.export_dir / f"{s.name}.parquet"
        LOG.info(
            "  %-14s %6.1f MB  partition=%s  cluster=%s",
            s.name,
            path.stat().st_size / (1024 * 1024),
            f"{s.partition_on} (MONTH, filter required)" if s.partition_on else "none",
            ",".join(s.cluster_on) or "none",
        )

    if args.dry_run:
        LOG.info("\n--dry-run: nothing was created or uploaded.")
        return 0

    client = bigquery.Client(project=project)
    dataset_ref = bigquery.Dataset(f"{project}.{args.dataset}")
    dataset_ref.location = LOCATION
    client.create_dataset(dataset_ref, exists_ok=True)
    LOG.info("dataset ready: %s.%s", project, args.dataset)

    for s in specs:
        path = args.export_dir / f"{s.name}.parquet"
        table_id = f"{project}.{args.dataset}.{s.name}"
        LOG.info("loading %s ...", table_id)
        try:
            with path.open("rb") as fh:
                job = client.load_table_from_file(fh, table_id, job_config=build_job_config(s))
            job.result()  # blocks; raises on failure rather than returning a bad job
        except GoogleAPIError as err:
            LOG.error("load failed for %s: %s", s.name, err)
            return 1

        table = client.get_table(table_id)
        LOG.info(
            "  %s: %s rows, %.1f MB stored",
            s.name,
            f"{table.num_rows:,}",
            table.num_bytes / (1024 * 1024),
        )

    LOG.info("\ndone. Query with bq_query.py, which dry-runs and caps bytes billed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
