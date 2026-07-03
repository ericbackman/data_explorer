"""Roll a set of trades up into a 'who owns what' ledger.

Where ``expand.py`` answers "how does this ONE pick resolve?", this answers
"after all these trades, which picks does each team now control?" — grouping
acquired assets by the receiving team.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import Pick, ProtectedPick, Swap, Trade


@dataclass(frozen=True)
class OwnedAsset:
    """One asset a team controls after the trades."""

    team: str        # who controls it now
    kind: str        # "pick" | "conditional" | "swap"
    year: int
    round: int
    source: str      # whose draft slot it draws from
    detail: str      # human description


def ownership(trades: Iterable[Trade]) -> dict[str, list[OwnedAsset]]:
    """Group every acquired asset by the team that now controls it.

    Returned dict is sorted by team, and each team's list is sorted by
    (year, round) so the ledger reads chronologically.
    """
    ledger: dict[str, list[OwnedAsset]] = {}
    for trade in trades:
        for asset in trade.assets:
            owned = _to_owned(asset)
            ledger.setdefault(owned.team, []).append(owned)
    for team in ledger:
        ledger[team].sort(key=lambda a: (a.year, a.round))
    return dict(sorted(ledger.items()))


def _to_owned(asset) -> OwnedAsset:
    if isinstance(asset, Pick):
        return OwnedAsset(
            team=asset.to, kind="pick", year=asset.year, round=asset.round,
            source=asset.origin,
            detail=f"{asset.origin} {asset.year} R{asset.round} (unconditional)",
        )
    if isinstance(asset, ProtectedPick):
        first_year, first_prot = asset.schedule[0]
        last_year = asset.schedule[-1][0]
        span = f"{first_year}" if first_year == last_year else f"{first_year}–{last_year}"
        return OwnedAsset(
            team=asset.to, kind="conditional", year=first_year, round=asset.round,
            source=asset.origin,
            detail=f"{asset.origin} {span} R{asset.round} ({first_prot.label()}, "
                   f"else {asset.fallback})",
        )
    if isinstance(asset, Swap):
        a, b = asset.teams
        other = b if asset.who_chooses == a else a
        edge = "more" if asset.favorable else "less"
        return OwnedAsset(
            team=asset.who_chooses, kind="swap", year=asset.year, round=asset.round,
            source=other,
            detail=f"{asset.year} R{asset.round} swap vs {other} "
                   f"(take the {edge} favorable pick)",
        )
    raise TypeError(f"unknown asset type: {type(asset).__name__}")


def to_markdown(ledger: dict[str, list[OwnedAsset]]) -> str:
    """Render the ledger as a grouped markdown list."""
    lines: list[str] = []
    for team, assets in ledger.items():
        lines.append(f"**{team}** controls:")
        for a in assets:
            tag = {"pick": "🟢", "conditional": "🟡", "swap": "🔵"}[a.kind]
            lines.append(f"- {tag} {a.detail}")
        lines.append("")
    return "\n".join(lines).strip()
