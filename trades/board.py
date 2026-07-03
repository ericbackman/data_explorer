"""Derive a full-draft ownership board from a set of trades.

One cell per team's own pick for a given year+round. By default each team
controls its own pick; each matching traded asset overrides the controller and
records the condition. This is the deterministic "who's owed each pick" view —
it needs no lottery result, unlike a slot-numbered board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import Pick, ProtectedPick, Protection, Swap, SLOTS_PER_ROUND, Trade
from .teams import TEAMS


@dataclass
class PickCell:
    """Who controls one team's pick, and under what condition."""

    origin: str                 # whose pick slot this is
    round: int
    controller: str             # who currently controls it (== origin if untraded)
    condition: str | None = None  # short human note if conditional / swap
    conditional: bool = False   # True for protected picks (may not convey)
    swap: bool = False          # True if a swap right touches this pick

    @property
    def traded(self) -> bool:
        return self.controller != self.origin or self.swap


# ---------------------------------------------------------------------------
# Slot view: one pick across all 30 landing slots
# ---------------------------------------------------------------------------
@dataclass
class SlotCell:
    """What happens to a pick if it lands in this exact slot."""

    slot: int
    kind: str          # "convey" | "roll" | "fallback"
    controller: str    # who gets it (convey) or the origin (protected)
    label: str         # short cell text, e.g. "→ CHI" or "protected"


@dataclass
class SlotStrip:
    """One draft year's worth of slot outcomes for a single pick."""

    year: int
    origin: str
    round: int
    protection_label: str
    to: str
    fallback: str
    cells: list[SlotCell]

    @property
    def convey_slots(self) -> list[int]:
        return [c.slot for c in self.cells if c.kind == "convey"]

    @property
    def protected_slots(self) -> list[int]:
        return [c.slot for c in self.cells if c.kind != "convey"]


def slot_strips(pp: ProtectedPick) -> list[SlotStrip]:
    """Expand a protected pick into one 1..30 outcome strip per scheduled year.

    Each slot is either 'convey' (outside the protection → goes to ``pp.to``) or
    protected. A protected slot 'roll's to next year, or is the 'fallback' on the
    final scheduled year.
    """
    strips: list[SlotStrip] = []
    for i, (year, prot) in enumerate(pp.schedule):
        is_last = i == len(pp.schedule) - 1
        next_year = None if is_last else pp.schedule[i + 1][0]
        cells: list[SlotCell] = []
        for slot in range(1, SLOTS_PER_ROUND + 1):
            if slot in prot.slots:
                if is_last:
                    cells.append(SlotCell(slot, "fallback", pp.origin, "does not convey"))
                else:
                    cells.append(SlotCell(slot, "roll", pp.origin, f"rolls to {next_year}"))
            else:
                cells.append(SlotCell(slot, "convey", pp.to, f"→ {pp.to}"))
        strips.append(SlotStrip(year, pp.origin, pp.round, prot.label(),
                                pp.to, pp.fallback, cells))
    return strips


def draft_board(year: int, rnd: int, trades: Iterable[Trade],
                teams: Iterable[str] = TEAMS) -> dict[str, PickCell]:
    """Return {team: PickCell} for `year` round `rnd` after applying `trades`."""
    cells = {t: PickCell(origin=t, round=rnd, controller=t) for t in teams}
    for trade in trades:
        for asset in trade.assets:
            _apply(asset, year, rnd, cells)
    return cells


def _apply(asset, year: int, rnd: int, cells: dict[str, PickCell]) -> None:
    if isinstance(asset, Pick):
        if asset.year == year and asset.round == rnd and asset.origin in cells:
            cells[asset.origin].controller = asset.to

    elif isinstance(asset, ProtectedPick):
        years = [y for y, _ in asset.schedule]
        if year in years and asset.round == rnd and asset.origin in cells:
            prot = dict(asset.schedule)[year]
            cell = cells[asset.origin]
            cell.controller = asset.to
            cell.conditional = True
            cell.condition = f"{prot.label()} → else {asset.fallback}"

    elif isinstance(asset, Swap):
        if asset.year == year and asset.round == rnd:
            a, b = asset.teams
            note = f"swap: {asset.who_chooses} may take the better of {a}/{b}"
            for t in (a, b):
                if t in cells:
                    cells[t].swap = True
                    cells[t].condition = note
