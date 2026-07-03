"""Tests for the who-owns-what roll-up against the sourced real trades."""

from trades import ownership
from trades.real_2026 import GIANNIS, KESSLER, WIZARDS_KNICKS


def test_blockbusters_group_by_acquiring_team():
    led = ownership.ownership([GIANNIS, KESSLER])
    assert set(led) == {"MIL", "UTA"}
    # Milwaukee holds Miami's unconditional firsts and the 2030 swap right.
    mil = {(a.year, a.round, a.kind) for a in led["MIL"]}
    assert (2031, 1, "pick") in mil
    assert (2033, 1, "pick") in mil
    assert (2030, 1, "swap") in mil
    # Utah holds both Laker firsts plus two swaps.
    uta_kinds = sorted(a.kind for a in led["UTA"])
    assert uta_kinds == ["pick", "pick", "swap", "swap"]


def test_swap_credited_to_the_chooser_not_the_origin():
    # Utah is who_chooses on the LAL swap → the swap is Utah's asset.
    led = ownership.ownership([KESSLER])
    assert "UTA" in led and "LAL" not in led
    swap = next(a for a in led["UTA"] if a.kind == "swap")
    assert swap.source == "LAL"


def test_conditional_pick_is_flagged_conditional():
    led = ownership.ownership([WIZARDS_KNICKS])
    asset = led["NYK"][0]
    assert asset.kind == "conditional"
    assert "top-8 protected" in asset.detail
