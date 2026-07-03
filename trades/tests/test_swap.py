"""Contract for resolve_swap — YOUR implementation target.

These tests describe the behaviour without over-constraining the exact wording,
so you have room to choose how the branches read. Run just this file:

    .venv/Scripts/python.exe -m pytest trades/tests/test_swap.py
"""

import pytest

from trades.model import Protection, Swap
from trades.expand import Decision, Outcome, Node, resolve_swap


def _leaves(node: Node) -> list[Outcome]:
    if isinstance(node, Outcome):
        return [node]
    out: list[Outcome] = []
    for br in node.branches:
        out.extend(_leaves(br.node))
    return out


def test_unconditional_favorable_swap_gives_chooser_the_better_pick():
    swap = Swap(year=2027, round=1, teams=("UTA", "CLE"), who_chooses="UTA")
    node = resolve_swap(swap)
    leaves = _leaves(node)
    text = " ".join(f"{lf.result} {lf.detail}".lower() for lf in leaves)
    # The chooser should end up associated with the better/best pick somewhere.
    assert "uta" in text
    assert "bett" in text or "best" in text


def test_voided_swap_branches_on_the_protection():
    swap = Swap(
        year=2027, round=1, teams=("UTA", "CLE"), who_chooses="UTA",
        voided_if=("CLE", Protection.top(10)),
    )
    node = resolve_swap(swap)
    # A conditional swap must branch: one path voids, one path swaps.
    assert isinstance(node, Decision), "a voided_if swap should be a Decision"
    assert len(node.branches) == 2
    joined = " ".join(br.condition.lower() for br in node.branches)
    assert "top-10" in joined or "1-10" in joined  # the protection is shown

    leaf_text = " ".join(lf.result.lower() for lf in _leaves(node))
    assert "void" in leaf_text or "keep" in leaf_text, "show the cancelled case"
    assert "swap" in leaf_text
