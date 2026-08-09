"""Property tests for competition scoring (osrs/scoring.py).

score_player() is YOUR contribution, so these don't pin a formula — they check
properties any sane scoring must satisfy. test_empty passes now (it's pure
plumbing); the other two go RED until you implement a monotonic score_player(),
then GREEN. That red->green flip is the point. Run: python -m pytest osrs/
"""

import pytest

from osrs import scoring

# score_player() is deliberately unimplemented (it raises NotImplementedError) -
# implementing it is the exercise. These two tests pin the properties it must
# satisfy, so they are EXPECTED to fail until then.
#
# Marked xfail rather than left raw-red so that `pytest` at the repo root exits
# 0: a visitor should not have to know this convention to tell a healthy repo
# from a broken one. The red->green flip this file is built around still shows -
# once score_player() works these report as XPASS, which is the signal to delete
# this marker.
pending_contribution = pytest.mark.xfail(
    reason="score_player() is an open contribution point - see osrs/scoring.py",
    raises=NotImplementedError,
)


def _gains(**skill_to_xp):
    """Tiny helper: _gains(Slayer=1_000_000) -> one player's skill_gains list."""
    return [
        {"skill": skill, "xp_gained": xp, "levels_gained": 0,
         "before_xp": 0, "after_xp": xp, "before_level": 1, "after_level": 1}
        for skill, xp in skill_to_xp.items()
    ]


def test_empty_input_returns_empty():
    # Plumbing only — passes before score_player is implemented.
    assert scoring.rank_gains({}) == []


@pending_contribution
def test_dominant_player_ranks_first():
    # "grinder" gained more XP in EVERY skill than "casual". No reasonable metric
    # should rank casual above grinder (monotonicity) — whatever formula you pick.
    ranked = scoring.rank_gains({
        "grinder": _gains(Slayer=2_000_000, Mining=500_000),
        "casual":  _gains(Slayer=100_000,   Mining=50_000),
    })
    winner = next(r for r in ranked if r["rank"] == 1)
    assert winner["rsn"] == "grinder"


@pending_contribution
def test_ranks_are_contiguous_places():
    ranked = scoring.rank_gains({
        "a": _gains(Mining=10), "b": _gains(Mining=20), "c": _gains(Mining=30),
    })
    assert sorted(r["rank"] for r in ranked) == [1, 2, 3]
