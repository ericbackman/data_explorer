"""Reusable loader: copy one SQLite table into the Supabase Postgres serving DB.

Usage:
    python load_to_supabase.py <sqlite_path> <src_table> <dest_table>

Reads the pooler connection string from supabase.env (key `pooler_url`) in
~\.config. Coerces SQLite type-affinity junk (blank/whitespace sitting in
numeric columns) to NULL so Postgres COPY doesn't reject the row.

Pattern: keep heavy raw data + DuckDB analysis LOCAL; push only small, curated,
already-analyzed serving tables to Supabase for gated dashboards/apps.
"""
import os
import re
import sys
import sqlite3
import psycopg

# supabase.env lives in the user config dir, outside any repo
ENV = os.path.expanduser(r"~\.config\supabase.env")

# SQLite declared type (affinity) -> Postgres column type
TYPE_MAP = [
    ("INT", "bigint"),
    ("CHAR", "text"), ("CLOB", "text"), ("TEXT", "text"),
    ("REAL", "double precision"), ("FLOA", "double precision"), ("DOUB", "double precision"),
    ("BLOB", "bytea"),
    ("BOOL", "boolean"),
    ("DATE", "text"), ("TIME", "text"),
]


def pg_type(sqlite_decl: str) -> str:
    d = (sqlite_decl or "").upper()
    for needle, pg in TYPE_MAP:
        if needle in d:
            return pg
    return "text"  # SQLite is dynamically typed; text is the safe default


def make_conv(t):
    """Return a value converter that turns SQLite junk into clean Postgres values."""
    if t == "bigint":
        def f(v):
            if v is None or isinstance(v, int):
                return v
            if isinstance(v, float):
                return int(v)
            s = str(v).strip()
            if s == "":
                return None
            try:
                return int(float(s))
            except ValueError:
                return None
        return f
    if t == "double precision":
        def f(v):
            if v is None or isinstance(v, (int, float)):
                return v
            s = str(v).strip()
            if s == "":
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return f
    if t == "boolean":
        def f(v):
            if v is None:
                return None
            s = str(v).strip().lower()
            if s in ("1", "true", "t", "yes"):
                return True
            if s in ("0", "false", "f", "no"):
                return False
            return None
        return f
    return lambda v: v  # text / bytea passthrough


def load_env(path):
    cfg = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r'^\s*([^=]+?)\s*=\s*"?([^"]*)"?\s*$', line)
            if m:
                cfg[m.group(1).strip()] = m.group(2).strip()
    return cfg


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sqlite_path, src_table, dest_table = sys.argv[1], sys.argv[2], sys.argv[3]
    cfg = load_env(ENV)
    dsn = cfg["pooler_url"]

    sq = sqlite3.connect(sqlite_path)
    cols = sq.execute(f"PRAGMA table_info({src_table})").fetchall()
    if not cols:
        print(f"ERROR: source table {src_table} not found in {sqlite_path}")
        sys.exit(1)
    colnames = [c[1] for c in cols]
    pgtypes = [pg_type(c[2]) for c in cols]
    convs = [make_conv(t) for t in pgtypes]
    coldefs = ", ".join(f'"{n}" {t}' for n, t in zip(colnames, pgtypes))
    nrows = sq.execute(f"SELECT count(*) FROM {src_table}").fetchone()[0]
    print(f"Source {src_table}: {len(colnames)} cols, {nrows} rows")

    pg = psycopg.connect(dsn, connect_timeout=15)
    pg.autocommit = False
    collist = ", ".join(f'"{c}"' for c in colnames)
    with pg.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{dest_table}" CASCADE')
        cur.execute(f'CREATE TABLE "{dest_table}" ({coldefs})')
        with cur.copy(f'COPY "{dest_table}" ({collist}) FROM STDIN') as copy:
            for row in sq.execute(f"SELECT {collist} FROM {src_table}"):
                copy.write_row([conv(v) for conv, v in zip(convs, row)])
    pg.commit()
    with pg.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{dest_table}"')
        loaded = cur.fetchone()[0]
    print(f"Loaded into Supabase public.{dest_table}: {loaded} rows")
    pg.close()
    sq.close()


if __name__ == "__main__":
    main()
