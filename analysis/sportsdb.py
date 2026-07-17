"""Read-only DuckDB query layer over the local sports/betting SQLite databases.

DuckDB attaches each SQLite file READ_ONLY and acts as a fast analytical
front-end: the .db files stay the single source of truth and are never mutated.
This mirrors, by hand, the read-only guarantee of the workspace ``sports_mcp.py``
server — you get columnar speed and cross-database joins with zero risk to the
originals.

Typical use inside a notebook::

    import sportsdb
    con = sportsdb.connect()            # attaches every available core DB
    sportsdb.databases()                # what got attached
    df = sportsdb.q("SELECT * FROM nba.player_game LIMIT 5")   # -> pandas
    pf = sportsdb.pl("SELECT * FROM pga.tournaments")          # -> polars

Add another database by adding one line to ``MANIFEST`` below.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:  # imported lazily; only needed for type checkers
    import pandas as pd
    import polars as pl_

logger = logging.getLogger(__name__)

# Workspace layout resolved relative to THIS file — never hardcode user paths,
# so the project stays portable (Windows, the macOS mirror, CI, …).
_ANALYSIS_DIR = Path(__file__).resolve().parent
_DATA_EXPLORER = _ANALYSIS_DIR.parent
_WORKSPACE = _DATA_EXPLORER.parent

# alias -> SQLite file. The alias is the schema you query against
# (e.g. ``nba.player_game``). Add a line to wire up another DB.
MANIFEST: dict[str, Path] = {
    "nba": _DATA_EXPLORER / "nba" / "data" / "nba.db",
    "nfl": _DATA_EXPLORER / "nfl" / "data" / "nfl.db",
    "pga": _DATA_EXPLORER / "pga" / "data" / "pga.db",
    "betting": _WORKSPACE / "betting_stuff" / "data" / "odds_history.db",
    # --- uncomment / edit to add more ---
    # "nba_comebacks": _DATA_EXPLORER / "nba_comebacks.db",
    # "mtg": _WORKSPACE / "MTG-Deckbuilding" / "data" / "mtg.db",
    # "life": _WORKSPACE / "life_tracker" / "life_tracker.db",
    # "games": _WORKSPACE / "videogame-stattracker" / "stats.db",
}

_con: duckdb.DuckDBPyConnection | None = None


def connect(refresh: bool = False) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection with every available DB attached read-only.

    The connection is cached for reuse; pass ``refresh=True`` to rebuild it
    (e.g. after editing ``MANIFEST``). Missing files are skipped with an
    explicit warning so a mid-scrape DB doesn't break the whole notebook —
    never silently.
    """
    global _con
    if _con is not None and not refresh:
        return _con

    con = duckdb.connect()  # in-memory engine; the SQLite files hold the data
    con.execute("INSTALL sqlite; LOAD sqlite;")

    attached: list[str] = []
    missing: list[tuple[str, Path]] = []
    for alias, path in MANIFEST.items():
        if not path.exists():
            missing.append((alias, path))
            continue
        # READ_ONLY is the whole point: analysis can never corrupt the source.
        con.execute(
            f"ATTACH '{path.as_posix()}' AS {alias} (TYPE sqlite, READ_ONLY);"
        )
        attached.append(alias)

    if not attached:
        checked = "\n  ".join(f"{a}: {p}" for a, p in MANIFEST.items())
        raise RuntimeError(f"No databases found to attach. Checked:\n  {checked}")

    logger.info("Attached read-only: %s", ", ".join(attached))
    for alias, path in missing:
        logger.warning("Skipped %s — file not found: %s", alias, path)

    _con = con
    return con


def q(sql: str) -> "pd.DataFrame":
    """Run SQL against the attached DBs and return a pandas DataFrame."""
    return connect().execute(sql).df()


def pl(sql: str) -> "pl_.DataFrame":
    """Run SQL and return a Polars DataFrame (zero-copy from DuckDB via Arrow)."""
    return connect().execute(sql).pl()


def databases() -> "pd.DataFrame":
    """List the file-backed databases currently attached."""
    return q(
        "SELECT database_name, path FROM duckdb_databases() "
        "WHERE path IS NOT NULL AND path <> '' ORDER BY database_name"
    )


def tables() -> "pd.DataFrame":
    """List every table across all attached databases."""
    return q(
        "SELECT table_catalog AS database, table_name "
        "FROM information_schema.tables "
        "WHERE table_catalog NOT IN ('system', 'temp', 'memory') "
        "ORDER BY database, table_name"
    )


if __name__ == "__main__":
    # Quick CLI smoke test: `python sportsdb.py`
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    connect()
    print("\nAttached databases:")
    print(databases().to_string(index=False))
    print(f"\nTotal tables across all DBs: {len(tables())}")
