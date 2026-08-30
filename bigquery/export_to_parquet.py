"""Export NBA tables from SQLite to Parquet, shaped for BigQuery.

Parquet rather than CSV because BigQuery reads the column types out of the file:
`game_date` arrives as a real DATE (so it can be a partition key) instead of a
string that would need a second pass to CAST.

Two shaping decisions happen here, both forced by how BigQuery works:

1. **`game_date` is denormalized into `play_by_play`.** That table has only
   `game_id` - no date at all. BigQuery has no indexes, so partition pruning is
   the only way to avoid scanning all 18.3M rows, and you cannot partition on a
   column that isn't in the table. So it is joined in from `games` at export.

2. **Partitioning will be MONTHLY, not daily.** The data starts in 1946, and
   ~80 years of daily partitions is ~29,000 - past BigQuery's 10,000-partition
   ceiling. Monthly is ~960 and still prunes a season query hard.

Read-only against the source DB (mode=ro), so it can never touch Eric's data.

    python export_to_parquet.py                 # all three tables
    python export_to_parquet.py --tables games  # just one
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

LOG = logging.getLogger("export")

# Rows per read batch. 18.3M x 21 columns will not fit in memory at once; this
# keeps peak usage near 200 MB while still giving Parquet large row groups.
BATCH_ROWS = 250_000

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "nba" / "data" / "nba.db"
DEFAULT_OUT = HERE / "export"

# game_date is TEXT 'YYYY-MM-DD' in SQLite; declare it DATE so BigQuery can
# partition on it directly.
DATE_COLUMNS = {"game_date"}

QUERIES: dict[str, str] = {
    # Dimension table - small, joined against constantly.
    "games": "SELECT * FROM games",
    # Fact table, already carries game_date.
    "player_game": "SELECT * FROM player_game",
    # Fact table, needs the partition key joined in (see module docstring).
    # LEFT JOIN so a play whose game is missing from `games` still exports, with
    # a NULL date, rather than being silently dropped.
    "play_by_play": """
        SELECT pbp.*, g.game_date, g.season, g.season_type
        FROM play_by_play AS pbp
        LEFT JOIN games AS g ON g.game_id = pbp.game_id
    """,
}


def declared_types(con: sqlite3.Connection) -> dict[str, str]:
    """Map column name -> declared SQLite type, across every table in the DB.

    Sampling rows to guess types does NOT work here, and failed the first time
    this ran: `shot_x` / `shot_y` / `shot_distance` are NULL for the opening
    plays of a game (a period-start event has no shot), so a sample of the first
    rows types them as string, and the export then dies ~1M rows in when a real
    shot arrives. The declared types are right there in the schema and are
    authoritative for this database, so use them.

    Column names are unique across the three exported tables apart from the join
    keys, which agree, so a flat map is safe.
    """
    types: dict[str, str] = {}
    tables = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for t in tables:
        for _, name, decl, *_ in con.execute(f'PRAGMA table_info("{t}")'):
            types.setdefault(name, (decl or "").upper())
    return types


def arrow_schema(cursor: sqlite3.Cursor, decl: dict[str, str]) -> pa.Schema:
    """Build an Arrow schema from the DB's declared types."""
    fields = []
    for d in cursor.description:
        name = d[0]
        if name in DATE_COLUMNS:
            fields.append(pa.field(name, pa.date32()))
            continue
        t = decl.get(name, "TEXT")
        if "INT" in t:
            fields.append(pa.field(name, pa.int64()))
        elif any(k in t for k in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
            fields.append(pa.field(name, pa.float64()))
        else:
            fields.append(pa.field(name, pa.string()))
    return pa.schema(fields)


def to_columns(rows: list[tuple], schema: pa.Schema, anomalies: dict[str, int]) -> list[pa.Array]:
    """Convert a batch to Arrow arrays, coercing to the declared type.

    SQLite permits a value of any type in any column, so coercion is per-value
    rather than assumed. Anything that cannot be coerced becomes NULL and is
    COUNTED - the count is reported at the end rather than swallowed, so a
    systematic type problem is visible instead of silently thinning the data.
    """
    arrays = []
    for i, field in enumerate(schema):
        col = [r[i] for r in rows]

        if pa.types.is_date32(field.type):
            col = [None if v in (None, "") else str(v)[:10] for v in col]
            arrays.append(pa.array(col, type=pa.string()).cast(pa.date32()))
            continue

        if pa.types.is_string(field.type):
            arrays.append(pa.array([None if v is None else str(v) for v in col], type=pa.string()))
            continue

        cast = int if pa.types.is_integer(field.type) else float
        out: list[object] = []
        for v in col:
            if v is None:
                out.append(None)
                continue
            try:
                out.append(cast(v))
            except (TypeError, ValueError):
                out.append(None)
                anomalies[field.name] = anomalies.get(field.name, 0) + 1
        arrays.append(pa.array(out, type=field.type))

    return arrays


def export_table(
    con: sqlite3.Connection, name: str, sql: str, out_dir: Path, decl: dict[str, str]
) -> int:
    cur = con.cursor()
    cur.execute(sql)

    first = cur.fetchmany(BATCH_ROWS)
    if not first:
        LOG.warning("%s: no rows, skipping", name)
        return 0

    schema = arrow_schema(cur, decl)
    out_path = out_dir / f"{name}.parquet"
    total = 0
    anomalies: dict[str, int] = {}

    # ZSTD over SNAPPY: BigQuery reads both, and the upload is the slow part.
    writer = pq.ParquetWriter(out_path, schema, compression="zstd")
    try:
        batch = first
        while batch:
            writer.write_table(
                pa.Table.from_arrays(to_columns(batch, schema, anomalies), schema=schema)
            )
            total += len(batch)
            if total % (BATCH_ROWS * 8) == 0:
                LOG.info("  %s: %s rows...", name, f"{total:,}")
            batch = cur.fetchmany(BATCH_ROWS)
    finally:
        writer.close()

    size_mb = out_path.stat().st_size / (1024 * 1024)
    LOG.info("%s: %s rows -> %s (%.1f MB)", name, f"{total:,}", out_path.name, size_mb)
    if anomalies:
        LOG.warning("  %s: values that would not cast, set NULL: %s", name, anomalies)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--tables", nargs="*", choices=sorted(QUERIES), default=sorted(QUERIES))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.db.exists():
        LOG.error("source database not found: %s", args.db)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        decl = declared_types(con)
        for name in args.tables:
            export_table(con, name, QUERIES[name], args.out, decl)
    finally:
        con.close()

    LOG.info("done -> %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
