"""Apply pending SQL migrations to a Postgres database, in order, exactly once.

    python migrate.py                 # uses $DATABASE_URL
    python migrate.py --status        # what is applied vs pending
    python migrate.py --dry-run

No framework: migrations are plain .sql files named `NNN_description.sql`,
applied in numeric order and recorded in `schema_migrations`. That keeps this
readable by anyone and adds no dependency, which matters because this same
script runs in CI against a throwaway Neon branch on every pull request.

Each migration runs in ONE transaction together with its `schema_migrations`
insert. A migration that fails halfway therefore leaves nothing behind - not a
partially-applied schema recorded as complete, which is the failure mode that
makes migration state untrustworthy. Postgres has transactional DDL, so this is
actually true here in a way it would not be on MySQL.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

import psycopg

LOG = logging.getLogger("migrate")

HERE = Path(__file__).resolve().parent
MIGRATIONS_DIR = HERE / "migrations"
NAME_RE = re.compile(r"^(\d+)_[a-z0-9_]+\.sql$")

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER     PRIMARY KEY,
    name        TEXT        NOT NULL,
    checksum    TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def discover(directory: Path) -> list[tuple[int, Path]]:
    """Return (version, path) sorted by version, rejecting ambiguous names."""
    found: dict[int, Path] = {}
    for path in sorted(directory.glob("*.sql")):
        m = NAME_RE.match(path.name)
        if not m:
            sys.exit(f"migration name must be NNN_lower_snake.sql: {path.name}")
        version = int(m.group(1))
        if version in found:
            # Two files claiming the same version have no defined order, so the
            # database you get depends on filesystem sorting. Refuse.
            sys.exit(f"duplicate migration version {version}: {found[version].name} and {path.name}")
        found[version] = path
    return sorted(found.items())


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def require_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "  local: . C:\\Users\\ericb\\Github\\.claude\\ops\\neon-url.ps1\n"
            "  CI:    supplied by the create-branch action"
        )
    return url


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrations = discover(MIGRATIONS_DIR)
    if not migrations:
        LOG.error("no migrations found in %s", MIGRATIONS_DIR)
        return 1

    with psycopg.connect(require_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(BOOTSTRAP)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version")
            applied = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        # A file edited after it was applied means the database and the repo
        # disagree about what the schema IS. Report it rather than re-running,
        # which would either no-op or fail confusingly.
        drift = [
            (v, p.name)
            for v, p in migrations
            if v in applied and applied[v][1] != checksum(p)
        ]
        for version, name in drift:
            LOG.warning("CHECKSUM DRIFT: %03d_%s was edited after it was applied", version, name)

        pending = [(v, p) for v, p in migrations if v not in applied]

        if args.status or args.dry_run:
            for v, p in migrations:
                mark = "applied" if v in applied else "PENDING"
                LOG.info("  %-8s %s", mark, p.name)
            LOG.info("\n%d applied, %d pending", len(applied), len(pending))
            return 1 if drift else 0

        if not pending:
            LOG.info("up to date (%d applied)", len(applied))
            return 1 if drift else 0

        for version, path in pending:
            LOG.info("applying %s ...", path.name)
            sql = path.read_text(encoding="utf-8")
            try:
                # One transaction for the DDL *and* the bookkeeping row.
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(sql)
                        cur.execute(
                            "INSERT INTO schema_migrations (version, name, checksum) "
                            "VALUES (%s, %s, %s)",
                            (version, path.name, checksum(path)),
                        )
            except psycopg.Error as err:
                LOG.error("FAILED %s: %s", path.name, err)
                LOG.error("rolled back; no partial schema and nothing recorded.")
                return 1
            LOG.info("  ok")

        LOG.info("applied %d migration(s)", len(pending))
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
