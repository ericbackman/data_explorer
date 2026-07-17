"""Convert the local sports SQLite DBs into one compressed DuckDB file.

Each SQLite DB becomes a schema (``nba.*``, ``nfl.*``, ``pga.*``) inside a single
``sports.duckdb``. DuckDB's columnar compression typically shrinks the ~6 GB of
SQLite to ~2-3 GB, and the Kaggle notebook opens the file natively — no SQLite
extension, no internet — read-only.

This runs LOCALLY (where duckdb + internet for the sqlite extension are available);
the Kaggle notebook never runs it.

Standalone, to test/measure:
    python build_duckdb.py <output.duckdb>
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# v1.0.0 on-disk format so ANY DuckDB >= 1.0 can open the file (Kaggle's image may
# ship an older DuckDB than the 1.5+ that writes it).
_STORAGE_VERSION = "v1.0.0"


def build_combined(sources: dict[str, Path], dest: Path) -> dict[str, int]:
    """Build one DuckDB file at ``dest`` with a schema per source DB.

    Returns ``{alias: table_count}``. Overwrites ``dest`` if present. Requires the
    duckdb package and its sqlite extension (auto-installed on first use).

    SQLite's loose typing lets a column declared REAL hold a stray text value like
    ``" "``; a naive ``SELECT *`` copy then trips DuckDB's strict types. So we read
    the data as text and ``TRY_CAST`` each column back to the type DuckDB inferred
    from the SQLite schema — dirty tokens (blank/space/junk) become NULL instead of
    blowing up the whole conversion.
    """
    import duckdb

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Build into a temp file, promote atomically on success — so a crash mid-build
    # never leaves a partial file that later looks "fresh" and gets reused/uploaded.
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)

    con = duckdb.connect()  # in-memory control connection
    counts: dict[str, int] = {}
    try:
        con.execute("INSTALL sqlite; LOAD sqlite;")
        con.execute(f"ATTACH '{tmp.as_posix()}' AS out (STORAGE_VERSION '{_STORAGE_VERSION}');")
        for alias, sqlite_path in sources.items():
            if not sqlite_path.exists():
                logger.warning("Skip %s — not found: %s", alias, sqlite_path)
                continue
            counts[alias] = _copy_db(con, alias, sqlite_path)
            logger.info("Converted %s: %d tables", alias, counts[alias])
        con.execute("DETACH out;")
    finally:
        con.close()

    dest.unlink(missing_ok=True)
    tmp.replace(dest)  # atomic promote — only reached if the build above succeeded
    return counts


def _needs_cast(duck_type: str) -> bool:
    """True for numeric/temporal DuckDB types we coerce; text/blob is kept as-is."""
    t = duck_type.upper()
    return any(k in t for k in
               ("INT", "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC",
                "DATE", "TIME", "BOOL"))


def _copy_db(con, alias: str, sqlite_path: Path) -> int:
    """Copy every table of one SQLite file into schema ``alias`` of the output DB."""
    src = f"src_{alias}"
    posix = sqlite_path.as_posix()

    # Pass 1 — metadata only (no row read, so dirty values can't error): the type
    # DuckDB infers from each SQLite column's declared type is our cast target.
    con.execute("SET sqlite_all_varchar=false;")
    con.execute(f"ATTACH '{posix}' AS {src} (TYPE sqlite, READ_ONLY);")
    schema: dict[str, list[tuple[str, str]]] = {}
    for table, column, dtype in con.execute(
        "SELECT table_name, column_name, data_type FROM duckdb_columns() "
        "WHERE database_name = ? ORDER BY table_name, column_index", [src]
    ).fetchall():
        schema.setdefault(table, []).append((column, dtype))
    con.execute(f"DETACH {src};")

    # Pass 2 — read every column as text, TRY_CAST back to the intended type.
    con.execute("SET sqlite_all_varchar=true;")
    con.execute(f"ATTACH '{posix}' AS {src} (TYPE sqlite, READ_ONLY);")
    con.execute(f"CREATE SCHEMA IF NOT EXISTS out.{alias};")
    for table, columns in schema.items():
        exprs = []
        for column, dtype in columns:
            if _needs_cast(dtype):
                exprs.append(f'TRY_CAST(NULLIF(TRIM("{column}"), \'\') AS {dtype}) AS "{column}"')
            else:
                exprs.append(f'"{column}"')
        con.execute(
            f'CREATE TABLE out.{alias}."{table}" AS '
            f'SELECT {", ".join(exprs)} FROM {src}.main."{table}";'
        )
    con.execute(f"DETACH {src};")
    con.execute("SET sqlite_all_varchar=false;")
    return len(schema)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python build_duckdb.py <output.duckdb>")
        return 2
    dest = Path(args[0]).resolve()
    from push_datasets import SOURCES  # reuse the one source manifest

    counts = build_combined(SOURCES, dest)
    logger.info("Wrote %s (%.2f GB); schemas: %s",
                dest, dest.stat().st_size / 1024**3, counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
