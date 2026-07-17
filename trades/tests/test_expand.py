"""Tests for the model + protected-pick expansion (the parts already built)."""

import pytest

from trades.model import Pick, Protection, ProtectedPick, Trade
from trades.expand import Decision, Outcome, expand, expand_protected_pick


def test_protection_labels():
    p = Protection.top(4)
    assert p.label() == "top-4 protected"
    assert p.conveys_label() == "lands 5-30"
    assert Protection.none().is_unprotected


def test_protection_rejects_out_of_range():
    with pytest.raises(ValueError):
        Protection(frozenset({0}))
    with pytest.raises(ValueError):
        Protection.top(40)


def test_schedule_must_be_ascending():
    with pytest.raises(ValueError):
        ProtectedPick(
            origin="PHX", round=1, to="BKN", fallback="2nds",
            schedule=((2027, Protection.top(4)), (2026, Protection.top(4))),
        )


def test_protected_pick_builds_a_chain():
    pp = ProtectedPick(
        origin="PHX", round=1, to="BKN", fallback="two 2nds",
        schedule=((2026, Protection.top(4)), (2027, Protection.top(2))),
    )
    root = expand_protected_pick(pp)
    # 2026 decision -> conveys leaf + (2027 decision -> conveys leaf + fallback leaf)
    assert isinstance(root, Decision)
    assert "2026" in root.prompt
    convey_2026, roll_2026 = root.branches
    assert isinstance(convey_2026.node, Outcome)
    assert convey_2026.node.result == "conveys to BKN"

    y2027 = roll_2026.node
    assert isinstance(y2027, Decision) and "2027" in y2027.prompt
    fallback_leaf = y2027.branches[1].node
    assert isinstance(fallback_leaf, Outcome)
    assert fallback_leaf.result == "two 2nds"


def test_unconditional_pick_is_a_leaf():
    tree = expand(Trade(name="t", teams=("A", "B"),
                        assets=[Pick(origin="A", year=2027, round=1, to="B")]))
    (_caption, root), = tree.roots
    assert isinstance(root, Outcome)
    assert root.result == "conveys to B"
