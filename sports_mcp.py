"""Local MCP server exposing the workspace sports databases, READ-ONLY.

Lets any Claude surface (Code, Desktop) answer questions over the local SQLite
DBs without shell access -- it speaks MCP over stdio. Three tools:

  * list_databases()              -- what DBs exist (slug, category, table count)
  * describe_schema(database)     -- tables + columns for one DB
  * run_sql(database, query)      -- run a SELECT/WITH query, capped rows

Read-only is enforced twice: the SQLite connection is opened mode=ro (writes
raise), and a statement guard rejects anything that isn't a single SELECT/WITH.

Register it (point `command` at this repo's venv python):

    {
      "mcpServers": {
        "sports-data": {
          "command": "C:\\\\Users\\\\ericb\\\\Github\\\\data_explorer\\\\.venv\\\\Scripts\\\\python.exe",
          "args": ["C:\\\\Users\\\\ericb\\\\Github\\\\data_explorer\\\\sports_mcp.py"]
        }
      }
    }
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_dashboard import INTERNAL, MANIFEST, WORKSPACE  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

MAX_ROWS = 200
mcp = FastMCP("sports-data")


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


# slug -> (label, category, absolute path)
_DBS = {_slug(label): (label, cat, WORKSPACE / rel) for label, cat, rel in MANIFEST}


def _resolve(name: str):
    """Resolve a user-supplied DB name (slug, label, or substring) to one entry."""
    key = _slug(name)
    if key in _DBS:
        return _DBS[key]
    hits = [(k, v) for k, v in _DBS.items() if key and (key in k or key in _slug(v[0]))]
    if len(hits) == 1:
        return hits[0][1]
    if not hits:
        raise ValueError(f"no database matching {name!r}. Try list_databases().")
    raise ValueError(f"{name!r} is ambiguous: {', '.join(k for k, _ in hits)}")


def _connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _list_databases() -> str:
    out = ["Available databases (use the slug as the `database` argument):", ""]
    for slug, (label, cat, path) in _DBS.items():
        if not path.exists():
            out.append(f"- {slug}  [{cat}]  {label} (file missing)")
            continue
        conn = _connect_ro(path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            conn.close()
        out.append(f"- {slug}  [{cat}]  {label}: {n} tables")
    return "\n".join(out)


def _describe_schema(database: str) -> str:
    label, cat, path = _resolve(database)
    if not path.exists():
        return f"{label}: database file not found."
    conn = _connect_ro(path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            if r[0] not in INTERNAL]
        out = [f"{label} [{cat}]: {len(tables)} tables", ""]
        for t in tables:
            cols = [f"{r[1]} {r[2]}".strip() for r in conn.execute(f"PRAGMA table_info('{t}')")]
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
                count = f"{n:,} rows"
            except sqlite3.Error:
                count = "rows"
            out.append(f"- {t} ({count}): {', '.join(cols)}")
        return "\n".join(out)
    finally:
        conn.close()


def _run_sql(database: str, query: str) -> str:
    label, cat, path = _resolve(database)
    q = query.strip().rstrip(";").strip()
    if ";" in q:
        return "Error: only a single statement is allowed (no ';')."
    if not re.match(r"(?is)^(select|with)\b", q):
        return "Error: only read-only SELECT / WITH queries are allowed."
    if not path.exists():
        return f"{label}: database file not found."
    conn = _connect_ro(path)
    try:
        cur = conn.execute(q)
        rows = cur.fetchmany(MAX_ROWS + 1)
        cols = [d[0] for d in cur.description] if cur.description else []
    except sqlite3.Error as exc:
        return f"SQL error: {exc}"
    finally:
        conn.close()

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    if not rows:
        return "(0 rows)"
    header = " | ".join(cols)
    body = "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in rows)
    note = f"\n... (truncated to {MAX_ROWS} rows)" if truncated else f"\n({len(rows)} rows)"
    return f"{header}\n{body}{note}"


@mcp.tool()
def list_databases() -> str:
    """List the available local sports databases (NBA, NFL, PGA, betting, …) with
    their slug, category, and table count. Use a slug as the `database` argument
    for the other tools."""
    return _list_databases()


@mcp.tool()
def describe_schema(database: str) -> str:
    """Return every table and its columns (with row counts) for one database.
    Read this before writing SQL so column names are exact. `database` is a slug
    from list_databases (or a unique substring of its name)."""
    return _describe_schema(database)


@mcp.tool()
def run_sql(database: str, query: str) -> str:
    """Run a READ-ONLY SQL query against a database and return the rows (capped at
    200). Only a single SELECT/WITH statement is allowed; writes are rejected and
    the connection is opened read-only. `database` is a slug from list_databases."""
    return _run_sql(database, query)


if __name__ == "__main__":
    mcp.run()  # stdio transport
