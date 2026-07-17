"""Worked example trades for demoing and testing the flowchart pipeline.

Illustrative structures (not authoritative cap-sheet data) — they exercise the
common real-world shapes: a rolling top-N protected pick, an unconditional
pick, and a conditional swap.
"""

from .model import Pick, ProtectedPick, Protection, Swap, Trade

# A classic "protection rolls forward, tightening each year, else two 2nds".
PHX_TOP4_ROLLING = Trade(
    name="Example: PHX 1st, top-4 protected and rolling",
    teams=("PHX", "BKN"),
    assets=[
        ProtectedPick(
            origin="PHX",
            round=1,
            schedule=(
                (2026, Protection.top(4)),
                (2027, Protection.top(4)),
                (2028, Protection.top(2)),
            ),
            to="BKN",
            fallback="becomes 2028 + 2029 second-round picks to BKN",
        )
    ],
)

# A multi-asset package: an outright pick plus a protection-voided swap.
SWAP_PACKAGE = Trade(
    name="Example: outright 2nd + conditional 1st-round swap",
    teams=("UTA", "CLE"),
    assets=[
        Pick(origin="CLE", year=2027, round=2, to="UTA"),
        Swap(
            year=2027,
            round=1,
            teams=("UTA", "CLE"),
            who_chooses="UTA",
            favorable=True,
            voided_if=("CLE", Protection.top(10)),
        ),
    ],
)

ALL = {"phx_top4_rolling": PHX_TOP4_ROLLING, "swap_package": SWAP_PACKAGE}
