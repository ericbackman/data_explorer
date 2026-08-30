"""Shared TiDB Cloud connection helper.

Reads TIDB_* environment variables set by .claude/ops/tidb-env.ps1 and fails
loudly and specifically when they are missing, rather than letting PyMySQL raise
a generic socket error three frames deeper.

TLS is REQUIRED and non-negotiable on TiDB Cloud Starter - the public endpoint
refuses a plaintext handshake. PyMySQL enables TLS as soon as any `ssl` argument
is passed, and the system CA store verifies the server certificate, so no CA
bundle needs shipping alongside this repo.

Two Starter limits are worth knowing before debugging a "random" disconnect,
because neither looks like a limit when it bites:
  * a connection is terminated after ~30 minutes regardless of activity;
  * AWS public endpoints idle out after 340 seconds.
Both surface as an abrupt closed connection mid-script. Long jobs should
reconnect rather than hold one handle open.
"""

from __future__ import annotations

import os
import sys

import pymysql

REQUIRED = ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD")


def connect(database: str | None = None, autocommit: bool = True) -> pymysql.Connection:
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        sys.exit(
            f"missing {', '.join(missing)}.\n"
            "  . C:\\Users\\ericb\\Github\\.claude\\ops\\tidb-env.ps1"
        )

    return pymysql.connect(
        host=os.environ["TIDB_HOST"],
        port=int(os.getenv("TIDB_PORT", "4000")),
        user=os.environ["TIDB_USER"],
        password=os.environ["TIDB_PASSWORD"],
        database=database or os.getenv("TIDB_DATABASE", "test"),
        # Any ssl argument turns TLS on; verification uses the system CA store.
        ssl={"ssl_mode": "VERIFY_IDENTITY"},
        autocommit=autocommit,
        charset="utf8mb4",
        # Starter caps transactions at 30 minutes; keep batches well inside it.
        read_timeout=120,
        write_timeout=120,
    )


def server_version(conn: pymysql.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        return cur.fetchone()[0]
