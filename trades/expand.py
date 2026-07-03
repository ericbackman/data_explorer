"""Expand a Trade into an OutcomeTree — the renderer-agnostic flowchart IR.

The tree has two node kinds:

* ``Decision`` — an internal node: a draft result splits into labelled branches.
* ``Outcome``  — a leaf: a final disposition ("conveys to BKN").

``expand(trade)`` returns one subtree per asset so a single trade with several
picks/swaps renders as several parallel flows.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Pick, ProtectedPick, Protection, Swap, Trade, Asset


# ---------------------------------------------------------------------------
# Intermediate representation
# ---------------------------------------------------------------------------
@dataclass
class Outcome:
    """A leaf: what finally happens down this branch.

    ``tone`` drives colour: "convey" (a pick moves / swap happens) or "fallback"
    (protection never cleared, or swap voided). Set at construction so renderers
    never have to guess from the wording.
    """

    result: str
    detail: str = ""
    tone: str = "convey"


@dataclass
class Branch:
    """A labelled edge out of a Decision (the draft condition) to a subtree."""

    condition: str
    node: "Node"


@dataclass
class Decision:
    """An internal node: a draft result that fans out into branches."""

    prompt: str
    branches: list[Branch]


Node = Decision | Outcome


@dataclass
class OutcomeTree:
    """A whole trade's flowchart: one (caption, subtree) per asset."""

    title: str
    roots: list[tuple[str, Node]]


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------
def expand(trade: Trade) -> OutcomeTree:
    """Expand every asset in the trade into its own outcome subtree."""
    roots: list[tuple[str, Node]] = []
    for asset in trade.assets:
        roots.append((_caption(asset), expand_asset(asset)))
    return OutcomeTree(title=trade.name, roots=roots)


def expand_asset(asset: Asset) -> Node:
    if isinstance(asset, Pick):
        return expand_pick(asset)
    if isinstance(asset, ProtectedPick):
        return expand_protected_pick(asset)
    if isinstance(asset, Swap):
        return expand_swap(asset)
    raise TypeError(f"unknown asset type: {type(asset).__name__}")


def expand_pick(pick: Pick) -> Node:
    """An unconditional pick is a single terminal outcome."""
    return Outcome(result=f"conveys to {pick.to}", detail=pick.describe())


def expand_protected_pick(pp: ProtectedPick) -> Node:
    """Walk the protection schedule into a chain of Decisions.

    Each scheduled year splits into 'conveys' (→ terminal outcome) and
    'protected' (→ next year, or the fallback if this was the last year).
    """
    return _expand_schedule(pp, index=0)


def _expand_schedule(pp: ProtectedPick, index: int) -> Node:
    year, prot = pp.schedule[index]
    is_last = index == len(pp.schedule) - 1

    # Unprotected in this year → it simply conveys, no branching needed.
    if prot.is_unprotected:
        return Outcome(result=f"conveys to {pp.to}", detail=f"{year} {pp.origin} R{pp.round}")

    conveys = Branch(
        condition=f"{prot.conveys_label()} — conveys",
        node=Outcome(result=f"conveys to {pp.to}", detail=f"{year} {pp.origin} R{pp.round}"),
    )
    if is_last:
        protected_node: Node = Outcome(
            result=pp.fallback, detail="protection never cleared", tone="fallback")
    else:
        protected_node = _expand_schedule(pp, index + 1)
    protected = Branch(condition=f"{prot.label()} — rolls over", node=protected_node)

    return Decision(prompt=f"{year} {pp.origin} R{pp.round} pick", branches=[conveys, protected])


def expand_swap(swap: Swap) -> Node:
    """Expand a swap into its outcome branches.

    Delegates the swap *semantics* to ``resolve_swap`` (see below).
    """
    return resolve_swap(swap)


def resolve_swap(swap: Swap) -> Node:
    """Turn a Swap into its outcome tree.

    Two layers, each modelled as a Decision because the whole point of the tool
    is to make the *branches* explicit rather than assert a resolved winner:

    * The exchange itself splits on which team's pick lands higher, so both
      concrete pick assignments are shown (see ``_swap_exchange``).
    * A ``voided_if`` protection wraps that in an outer split: one branch
      cancels the swap (each team keeps its own pick), the other lets it occur.
    """
    a, b = swap.teams
    chooser = swap.who_chooses
    other = b if chooser == a else a
    exchange = _swap_exchange(swap, chooser, other)

    if swap.voided_if is None:
        return exchange

    prot_team, prot = swap.voided_if
    voided = Branch(
        condition=f"{prot_team} {prot.label()} — swap voided",
        node=Outcome(
            result="swap cancelled — each team keeps its own pick",
            detail=f"{prot_team}'s pick fell inside {prot.label()}",
            tone="fallback",
        ),
    )
    occurs = Branch(condition=f"{prot_team} {prot.conveys_label()} — swap occurs", node=exchange)
    return Decision(prompt=f"{swap.year} R{swap.round} {a}/{b} swap", branches=[voided, occurs])


def _swap_exchange(swap: Swap, chooser: str, other: str) -> Node:
    """The exchange itself: which team ends up with which pick.

    ``favorable`` (the normal case) sends the better pick to the chooser; an
    unfavorable swap (an obligation) sends the chooser the worse pick.
    """
    prompt = f"{swap.year} R{swap.round} swap — which pick lands higher?"
    edge = "better" if swap.favorable else "worse"
    verb = "swaps up to" if swap.favorable else "swaps down to"

    keep = Branch(
        condition=f"{chooser}'s own pick is {edge}",
        node=Outcome(
            result=f"no exchange — {chooser} keeps its pick",
            detail=f"{chooser} already holds the {edge} pick",
        ),
    )
    take = Branch(
        condition=f"{other}'s pick is {edge}",
        node=Outcome(
            result=f"{chooser} {verb} {other}'s pick; {other} takes {chooser}'s",
            detail=f"{chooser} exercises the {'favorable' if swap.favorable else 'obligated'} swap",
        ),
    )
    return Decision(prompt=prompt, branches=[keep, take])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _caption(asset: Asset) -> str:
    if isinstance(asset, Pick):
        return f"{asset.year} {asset.origin} R{asset.round} (unconditional)"
    if isinstance(asset, ProtectedPick):
        first_year = asset.schedule[0][0]
        last_year = asset.schedule[-1][0]
        span = f"{first_year}" if first_year == last_year else f"{first_year}-{last_year}"
        return f"{span} {asset.origin} R{asset.round} (protected)"
    if isinstance(asset, Swap):
        a, b = asset.teams
        return f"{asset.year} {a}/{b} R{asset.round} swap"
    raise TypeError(f"unknown asset type: {type(asset).__name__}")
