"""Tests for the full-draft ownership board derivation."""

from trades import board
from trades.teams import TEAMS
from trades.real_2026 import BOARD_2026_R1, WIZARDS_KNICKS


def test_board_has_one_cell_per_team():
    cells = board.draft_board(2026, 1, [])
    assert set(cells) == set(TEAMS)
    assert all(c.controller == c.origin and not c.traded for c in cells.values())


def test_sourced_obligations_override_controller():
    cells = board.draft_board(2026, 1, BOARD_2026_R1)
    assert cells["WAS"].controller == "NYK"
    assert cells["WAS"].conditional and cells["WAS"].traded
    assert "top-8 protected" in cells["WAS"].condition
    # Untouched team keeps its own pick.
    assert cells["BOS"].controller == "BOS" and not cells["BOS"].traded


def test_wrong_year_or_round_does_not_apply():
    # WIZARDS_KNICKS is a 2026 R1 obligation; it must not show on a 2027 board.
    cells_2027 = board.draft_board(2027, 1, [WIZARDS_KNICKS])
    assert cells_2027["WAS"].controller == "WAS"
    cells_r2 = board.draft_board(2026, 2, [WIZARDS_KNICKS])
    assert cells_r2["WAS"].controller == "WAS"


def test_slot_strip_splits_at_the_protection_boundary():
    strips = board.slot_strips(WIZARDS_KNICKS.assets[0])
    assert len(strips) == 1
    s = strips[0]
    assert len(s.cells) == 30
    assert s.protected_slots == list(range(1, 9))      # top-8 → 1..8
    assert s.convey_slots == list(range(9, 31))        # 9..30 convey
    assert all(c.controller == "NYK" for c in s.cells if c.kind == "convey")


def test_rolling_pick_makes_one_strip_per_year_with_fallback_on_the_last():
    from trades.real_2026 import BLAZERS_BULLS
    strips = board.slot_strips(BLAZERS_BULLS.assets[0])
    assert [s.year for s in strips] == [2026, 2027]
    # First year's protected slots roll; last year's are terminal fallback.
    assert all(c.kind == "roll" for c in strips[0].cells if c.slot <= 14)
    assert all(c.kind == "fallback" for c in strips[1].cells if c.slot <= 14)
