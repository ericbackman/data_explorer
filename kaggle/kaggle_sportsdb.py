"""Read-only query layer over the sports DBs published to this Kaggle dataset.

Kaggle twin of ``analysis/sportsdb.py``. The data ships as a single compressed
``sports.duckdb`` file (built by ``push_datasets.py``), with one schema per sport
(``nba.*``, ``nfl.*``, ``pga.*``). Kaggle mounts it READ-ONLY at
``/kaggle/input/<dataset>/``, and we open it ``read_only=True`` — so analysis can
never mutate the source, the same guarantee the local layer makes.

The file is written in DuckDB's ``v1.0.0`` on-disk format, so any DuckDB >= 1.0 in
the notebook can read it — no SQLite extension, no internet.

In a Kaggle notebook cell::

    import sys; sys.path.append('/kaggle/input/sports-dbs')
    import kaggle_sportsdb as sportsdb
    sportsdb.databases()                                       # schemas + table counts
    sportsdb.q("SELECT * FROM nba.player_game LIMIT 5")        # -> pandas
    sportsdb.pl("SELECT * FROM pga.events")                    # -> polars

Add another database via one line in ``push_datasets.SOURCES``, then re-push.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # only needed by type checkers
    import duckdb
    import pandas as pd
    import polars as pl_

logger = logging.getLogger(__name__)

# sports.duckdb sits next to THIS file inside the mounted dataset, so resolve from
# __file__ — works regardless of the dataset slug. Override for local testing.
_BASE = Path(os.getenv("SPORTSDB_DATA_DIR", str(Path(__file__).resolve().parent)))
_DB = _BASE / "sports.duckdb"

_con: "duckdb.DuckDBPyConnection | None" = None


def connect(refresh: bool = False) -> "duckdb.DuckDBPyConnection":
    """Return a cached read-only DuckDB connection to ``sports.duckdb``.

    Pass ``refresh=True`` to reopen. Raises a clear, actionable error if the file
    isn't mounted or DuckDB isn't available in the notebook.
    """
    global _con
    if _con is not None and not refresh:
        return _con

    try:
        import duckdb
    except ImportError as exc:  # extremely rare on Kaggle, but fail loudly with the fix
        raise RuntimeError(
            "duckdb isn't installed in this notebook. Turn Internet ON in the "
            "notebook settings (right sidebar) and run:  !pip install duckdb"
        ) from exc

    if not _DB.exists():
        raise RuntimeError(
            f"sports.duckdb not found at {_DB}. Add the 'sports-dbs' dataset via "
            "'Add Input' (right sidebar), or fix SPORTSDB_DATA_DIR for local runs."
        )

    _con = duckdb.connect(str(_DB), read_only=True)
    logger.info("Opened %s read-only", _DB.name)
    return _con


def q(sql: str) -> "pd.DataFrame":
    """Run SQL and return a pandas DataFrame."""
    return connect().execute(sql).df()


def pl(sql: str) -> "pl_.DataFrame":
    """Run SQL and return a Polars DataFrame (zero-copy from DuckDB via Arrow)."""
    return connect().execute(sql).pl()


def databases() -> "pd.DataFrame":
    """List the schemas (one per sport) and how many tables each has."""
    return connect().execute(
        "SELECT schema_name AS database, count(*) AS tables "
        "FROM duckdb_tables() GROUP BY schema_name ORDER BY schema_name"
    ).df()


def tables() -> "pd.DataFrame":
    """List every table across all schemas."""
    return connect().execute(
        "SELECT schema_name AS database, table_name "
        "FROM duckdb_tables() ORDER BY schema_name, table_name"
    ).df()


if __name__ == "__main__":
    # Local smoke test: point at a folder containing sports.duckdb via SPORTSDB_DATA_DIR.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    connect()
    print("\nSchemas:")
    print(databases().to_string(index=False))
    print(f"\nTotal tables: {len(tables())}")
