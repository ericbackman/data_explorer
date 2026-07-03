"""Data model for an NBA draft-pick trade.

Everything a trade can involve is one of three assets:

* ``Pick``           — an unconditional pick that simply changes hands.
* ``ProtectedPick``  — a pick that only conveys if it lands outside a
                       protected slot range, otherwise it rolls forward a year
                       (possibly with different protection) until a fallback.
* ``Swap``           — the right for one team to exchange its pick for
                       another team's, sometimes voided by a protection.

A ``Trade`` bundles these together with the teams involved. The model carries
no rendering or evaluation logic — see ``expand.py`` and ``render.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Modern NBA: 30 teams, so each round holds 30 slots. A "top-4 protected" pick
# is protected in slots 1-4 and conveys in slots 5-30.
SLOTS_PER_ROUND = 30


@dataclass(frozen=True)
class Protection:
    """The slot range in which a pick is *protected* (does NOT convey).

    ``top(4)`` == protected if it lands 1-4, conveys 5-30. An empty protection
    means the pick always conveys (unprotected).
    """

    slots: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        bad = [s for s in self.slots if not (1 <= s <= SLOTS_PER_ROUND)]
        if bad:
            raise ValueError(f"protection slots out of range 1-{SLOTS_PER_ROUND}: {bad}")

    @classmethod
    def top(cls, n: int) -> "Protection":
        """Top-``n`` protected: protected in slots 1..n."""
        if not (1 <= n <= SLOTS_PER_ROUND):
            raise ValueError(f"top({n}) must be within 1-{SLOTS_PER_ROUND}")
        return cls(frozenset(range(1, n + 1)))

    @classmethod
    def none(cls) -> "Protection":
        """Unprotected — always conveys."""
        return cls(frozenset())

    @property
    def is_unprotected(self) -> bool:
        return not self.slots

    def conveys_slots(self) -> frozenset[int]:
        """Slots in which the pick DOES convey (the complement)."""
        return frozenset(range(1, SLOTS_PER_ROUND + 1)) - self.slots

    def label(self) -> str:
        """Human range label, e.g. 'top-4 protected' or 'lands 5-30'."""
        if self.is_unprotected:
            return "unprotected"
        hi = max(self.slots)
        # Contiguous 1..hi is the overwhelmingly common case ("top-N").
        if self.slots == frozenset(range(1, hi + 1)):
            return f"top-{hi} protected"
        return "protected in " + _fmt_slots(self.slots)

    def conveys_label(self) -> str:
        """Human range label for the slots in which the pick conveys."""
        if self.is_unprotected:
            return "any slot"
        return "lands " + _fmt_slots(self.conveys_slots())


@dataclass(frozen=True)
class Pick:
    """An unconditional pick that changes hands outright."""

    origin: str
    year: int
    round: int
    to: str

    def describe(self) -> str:
        return f"{self.year} {self.origin} R{self.round} → {self.to}"


@dataclass(frozen=True)
class ProtectedPick:
    """A pick with sequential, year-by-year protection.

    ``schedule`` is one ``(year, Protection)`` entry per year the pick can
    convey, in order. If it stays protected through the final scheduled year,
    ``fallback`` describes what the sender owes instead (e.g. two 2nd-rounders).
    """

    origin: str
    round: int
    schedule: tuple[tuple[int, Protection], ...]
    to: str
    fallback: str

    def __post_init__(self) -> None:
        if not self.schedule:
            raise ValueError("ProtectedPick.schedule must have at least one year")
        years = [y for y, _ in self.schedule]
        if years != sorted(years):
            raise ValueError(f"schedule years must be ascending: {years}")
        if len(set(years)) != len(years):
            raise ValueError(f"schedule has duplicate years: {years}")


@dataclass(frozen=True)
class Swap:
    """A pick swap between two teams in one year/round.

    ``who_chooses`` is the team holding the swap right. ``favorable`` is True
    for a normal swap (chooser takes the better pick) or False for a "swap the
    worse pick" arrangement. ``voided_if`` optionally cancels the swap when the
    named team's pick lands in a protected range.
    """

    year: int
    round: int
    teams: tuple[str, str]
    who_chooses: str
    favorable: bool = True
    voided_if: tuple[str, Protection] | None = None

    def __post_init__(self) -> None:
        if self.who_chooses not in self.teams:
            raise ValueError(
                f"who_chooses {self.who_chooses!r} must be one of {self.teams}"
            )
        if self.voided_if and self.voided_if[0] not in self.teams:
            raise ValueError(
                f"voided_if team {self.voided_if[0]!r} must be one of {self.teams}"
            )


Asset = Pick | ProtectedPick | Swap


@dataclass
class Trade:
    """A named trade: the teams involved plus the conditional assets moving."""

    name: str
    teams: tuple[str, ...]
    assets: list[Asset]

    def __post_init__(self) -> None:
        if not self.assets:
            raise ValueError("a Trade must move at least one asset")


def _fmt_slots(slots: frozenset[int]) -> str:
    """Compress a slot set into ranges, e.g. {1,2,3,7} -> '1-3, 7'."""
    xs = sorted(slots)
    out: list[str] = []
    start = prev = xs[0]
    for s in xs[1:]:
        if s == prev + 1:
            prev = s
            continue
        out.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = s
    out.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(out)
