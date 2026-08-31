"""Loader semantics: idempotency, key-replace, and the fail-loud dup guard."""
from __future__ import annotations

import pytest

from draft import db


def _row(**kw) -> dict:
    base = {c: None for c in db.COLUMNS}
    base.update(sport="NBA", draft_year=2023, draft_type="regular",
                overall_pick=1, source="test")
    base.update(kw)
    return base


def test_load_is_idempotent():
    conn = db.connect(":memory:")
    rows = [_row(overall_pick=1, player_name="A"), _row(overall_pick=2, player_name="B")]
    assert db.load(conn, rows, sport="NBA") == 2
    db.load(conn, rows, sport="NBA")  # re-run must converge, not duplicate
    assert conn.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0] == 2


def test_load_replaces_on_natural_key():
    conn = db.connect(":memory:")
    db.load(conn, [_row(overall_pick=1, player_name="Old")], sport="NBA")
    db.load(conn, [_row(overall_pick=1, player_name="New")], sport="NBA")
    name = conn.execute("SELECT player_name FROM draft_picks WHERE overall_pick=1").fetchone()[0]
    assert name == "New"


def test_assert_unique_keys_raises_on_collision():
    rows = [_row(overall_pick=1, player_name="A"), _row(overall_pick=1, player_name="B")]
    with pytest.raises(ValueError, match="duplicate draft key"):
        db.assert_unique_keys(rows, "NBA")


def test_supplemental_may_reuse_overall_number():
    # An NHL supplemental pick reuses the regular overall numbering; draft_type
    # partitions the key, so this must NOT collide.
    rows = [_row(sport="NHL", overall_pick=1, draft_type="regular"),
            _row(sport="NHL", overall_pick=1, draft_type="supplemental")]
    db.assert_unique_keys(rows, "NHL")  # no raise
    conn = db.connect(":memory:")
    assert db.load(conn, rows, sport="NHL") == 2


def test_summary_and_loaded_years():
    conn = db.connect(":memory:")
    db.load(conn, [_row(draft_year=2000, overall_pick=1),
                   _row(draft_year=2001, overall_pick=1)], sport="NBA")
    assert db.loaded_years(conn, "NBA") == {2000, 2001}
    summ = db.summary(conn)
    assert summ["total"] == 2
    assert summ["by_sport"]["NBA"] == {"picks": 2, "year_min": 2000, "year_max": 2001}
