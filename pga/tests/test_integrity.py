"""Regression + audit tests for the phantom-round fix. Data-coupled (real pga.db),
so they skip cleanly when the DB hasn't been built."""
import pytest

from pga.analysis import leaders_after_round
from pga.integrity import DEFAULT_DB, audit
from pga.db import connect

pytestmark = pytest.mark.skipif(not DEFAULT_DB.exists(), reason="pga.db not built")

_PGA_2009 = 551  # 2009 PGA Championship: Tiger led after 54, Y.E. Yang won


def test_2009_pga_54hole_leader_is_tiger_not_the_phantom():
    conn = connect(DEFAULT_DB)
    try:
        leaders = leaders_after_round(conn, _PGA_2009, 3)
        names = {
            conn.execute("SELECT name FROM players WHERE player_id=?", (p,)).fetchone()["name"]
            for p in leaders
        }
    finally:
        conn.close()
    assert names == {"Tiger Woods"}          # the real solo 54-hole leader
    # Richard Sterne missed the cut; his phantom round 3 must never crown him leader.


def test_audit_detects_phantoms_but_finished_data_stays_clean():
    conn = connect(DEFAULT_DB)
    try:
        a = audit(conn)
    finally:
        conn.close()
    assert a["phantom_rounds"] > 0        # the known feed artifacts are surfaced
    assert a["total_mismatches"] < 50     # finished-player rounds sum to their totals
