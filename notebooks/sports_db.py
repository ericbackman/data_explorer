"""Read-only query helpers for the data_explorer sports databases.

Shared by the Jupyter notebook (``explore.ipynb``) and the marimo notebook
(``explore.py``) so both speak to the data the same way.

Design notes
------------
* The notebooks live in a git **worktree** under ``.claude/worktrees/...``, but
  the ``.db`` files are gitignored and exist only in the MAIN checkout. We find
  that checkout by walking up to the first ancestor literally named
  ``data_explorer`` -- no absolute home path is ever hardcoded.
* Every connection is opened ``mode=ro`` (SQLite read-only URI), so exploration
  physically cannot mutate a database. That matches the repo rule: "Queries are
  read-only -- never mutate a DB during analysis."
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

# --- Locate the real data root (out of the worktree) -----------------------


def _find_data_root(start: Path | None = None) -> Path:
    """Walk upward from ``start`` to the ``data_explorer`` repo root."""
    start = (start or Path.cwd()).resolve()
    for path in (start, *start.parents):
        if path.name == "data_explorer":
            return path
    raise FileNotFoundError(
        f"Could not find a 'data_explorer' directory above {start}. "
        "Set DATA_ROOT by hand if your layout differs."
    )


DATA_ROOT = _find_data_root()


def discover_databases(root: Path | None = None) -> dict[str, Path]:
    """Map a friendly name -> path for every ``.db`` under the repo.

    Friendly name is the sport folder for ``<sport>/data/foo.db`` layouts,
    otherwise the file stem. ``.claude`` (worktrees, caches) is skipped.
    """
    root = root or DATA_ROOT
    found: dict[str, Path] = {}
    for db in sorted(root.rglob("*.db")):
        if ".claude" in db.parts:
            continue
        name = db.parent.parent.name if db.parent.name == "data" else db.stem
        found[name] = db
    return found


DATABASES = discover_databases()


# --- Read-only access ------------------------------------------------------


def connect(db: str) -> sqlite3.Connection:
    """Open a READ-ONLY connection to a discovered database by friendly name."""
    if db not in DATABASES:
        raise KeyError(f"Unknown db {db!r}. Known: {sorted(DATABASES)}")
    uri = f"file:{DATABASES[db].as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def q(sql: str, db: str = "nba", params: tuple = ()) -> pd.DataFrame:
    """Run read-only SQL and return a DataFrame.

    Builds the frame from the cursor directly (instead of ``pd.read_sql``) to
    sidestep pandas' "only SQLAlchemy connectable" warning for raw sqlite3.
    """
    with connect(db) as conn:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return pd.DataFrame(cur.fetchall(), columns=cols)


def tables(db: str = "nba") -> list[str]:
    """List user table names in a database (fast -- no row counts)."""
    rows = q(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        db,
    )
    return rows["name"].tolist()


def schema(db: str, table: str) -> pd.DataFrame:
    """Column names + declared types for one table."""
    return q(f'PRAGMA table_info("{table}")', db)[["name", "type"]]


# --- Your turn -------------------------------------------------------------
# `play_by_play` is 17.7M rows; a bare `SELECT *` will exhaust memory. Decide
# how a "safe" exploratory query should behave and implement it here.
#
# Trade-offs to weigh:
#   * Auto-append a LIMIT when the SQL has none -> safe, but silently truncates
#     (a count or an aggregate could look "complete" when it isn't).
#   * Only guard `SELECT *` / `SELECT ... FROM` without LIMIT, leave aggregates
#     (COUNT, SUM, GROUP BY) untouched -> smarter, more code to get right.
#   * Hard cap rows fetched and warn loudly when the cap is hit -> never
#     truncates silently, but you must surface the warning.
#
# def peek(sql: str, db: str = "nba", limit: int = 1_000) -> pd.DataFrame:
#     """Like q(), but protect against accidentally pulling millions of rows."""
#     raise NotImplementedError("Implement your safety guard (see notes above).")
