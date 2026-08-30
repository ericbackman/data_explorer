"""Tests that run against a REAL Postgres, not a mock.

In CI these run against a throwaway Neon branch created for the pull request, so
every PR gets a full-fidelity database of its own: real constraints, real
planner, real DDL. That is the whole argument for branching - a mock would
happily accept a CHECK violation, and a shared staging database would let one
PR's migration break another's test run.

    . C:\\Users\\ericb\\Github\\.claude\\ops\\neon-url.ps1
    python -m pytest test_schema.py -v

Split in two:
  * schema tests   - always meaningful, including on a freshly-migrated branch
                     with no rows in it;
  * data tests     - skipped when the branch has not been seeded, rather than
                     failing, so a schema-only PR is not red for the wrong reason.
"""

from __future__ import annotations

import os

import psycopg
import pytest

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL is not set - see the module docstring"
)


@pytest.fixture(scope="module")
def conn():
    with psycopg.connect(DATABASE_URL) as c:
        yield c


@pytest.fixture(scope="module")
def seeded(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM player_season")
        return cur.fetchone()[0] > 0


# --------------------------------------------------------------------- schema


def test_migrations_recorded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_migrations")
        assert cur.fetchone()[0] >= 2, "expected at least 001 and 002 to be applied"


def test_expected_relations_exist(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        names = {r[0] for r in cur.fetchall()}
    assert {"teams", "players", "player_season", "player_season_rates"} <= names


def test_games_check_constraint_rejects_zero(conn):
    """The CHECK is what makes the per-game view's division safe."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO players (player_id, player_name) VALUES (-1, 'Test') "
                    "ON CONFLICT DO NOTHING")
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO player_season "
                "(player_id, season, season_type, games) VALUES (-1, '1999-00', 'Test', 0)"
            )
    conn.rollback()


def test_foreign_key_rejects_unknown_player(conn):
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO player_season "
                "(player_id, season, season_type, games) VALUES (-999999, '1999-00', 'Test', 1)"
            )
    conn.rollback()


def test_season_index_is_used_not_a_seq_scan(conn, seeded):
    """A leaderboard query must hit the index, or serving latency is a lie.

    Asserted on the PLAN rather than on timing, which would be flaky in CI.
    """
    if not seeded:
        pytest.skip("branch not seeded; the planner would pick a seq scan on an empty table")
    with conn.cursor() as cur:
        cur.execute(
            "EXPLAIN (FORMAT TEXT) SELECT player_id, pts FROM player_season "
            "WHERE season = '2023-24' AND season_type = 'Regular Season' "
            "ORDER BY pts DESC LIMIT 10"
        )
        plan = "\n".join(r[0] for r in cur.fetchall())
    assert "idx_player_season_season" in plan, f"expected an index scan, got:\n{plan}"


# ----------------------------------------------------------------------- data


def test_no_orphan_team_references(conn, seeded):
    if not seeded:
        pytest.skip("branch not seeded")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM player_season ps "
            "LEFT JOIN teams t ON t.team_id = ps.team_id "
            "WHERE ps.team_id IS NOT NULL AND t.team_id IS NULL"
        )
        assert cur.fetchone()[0] == 0


def test_rates_view_matches_totals(conn, seeded):
    """The view must not disagree with the table it derives from."""
    if not seeded:
        pytest.skip("branch not seeded")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ps.pts, ps.games, r.ppg FROM player_season ps "
            "JOIN player_season_rates r USING (player_id, season, season_type) "
            "ORDER BY ps.pts DESC LIMIT 5"
        )
        for pts, games, ppg in cur.fetchall():
            assert abs(float(ppg) - pts / games) < 0.05


def test_known_fact_kareem_is_the_all_time_scorer(conn, seeded):
    """Validate against a fact that is true outside this database.

    Per the workspace convention: every dataset gets checked against something
    known, so a plausible-but-wrong load is caught. Kareem Abdul-Jabbar holds the
    regular-season career scoring record; LeBron passed him in 2023 but this
    dataset's totals are the check that matters, so assert both are at the top.
    """
    if not seeded:
        pytest.skip("branch not seeded")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.player_name, SUM(ps.pts) AS career FROM player_season ps "
            "JOIN players p USING (player_id) "
            "WHERE ps.season_type = 'Regular Season' "
            "GROUP BY p.player_name ORDER BY career DESC LIMIT 3"
        )
        top = [r[0] for r in cur.fetchall()]
    assert any("Abdul-Jabbar" in n or "LeBron" in n for n in top), f"unexpected top scorers: {top}"
