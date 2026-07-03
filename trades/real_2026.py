"""Real NBA draft-pick trades from the 2026 offseason, encoded for the tool.

SOURCED — every pick/protection below is from reporting, not invented. If a
term wasn't reported, it isn't modelled here.

Sources:
  * Giannis → Heat (Jun 22 2026):
    https://www.espn.com/nba/story/_/id/49149967/
  * Walker Kessler → Lakers (Jul 1 2026):
    https://www.espn.com/nba/story/_/id/49237403/
  * 2026 first-round protections (Wizards→Knicks, Blazers→Bulls, Sixers→OKC):
    https://www.hoopsrumors.com/2025/08/traded-first-round-picks-for-2026-nba-draft.html

Note: the 2026 first-round *legs* (Wizards, Blazers, Sixers below) have since
conveyed at the June 2026 draft — they're kept as faithful examples of the
conditional *structure* the tool exists to explain. The Giannis/Kessler future
picks (2028-2033) are still unresolved.
"""

from .model import Pick, ProtectedPick, Protection, Swap, Trade

# --- Recent blockbusters: unprotected future firsts + swaps -----------------
GIANNIS = Trade(
    name="Giannis to Miami — future capital Milwaukee now controls",
    teams=("MIA", "MIL"),
    assets=[
        Pick(origin="MIA", year=2031, round=1, to="MIL"),          # unprotected
        Pick(origin="MIA", year=2033, round=1, to="MIL"),          # unprotected
        Swap(year=2030, round=1, teams=("MIL", "MIA"), who_chooses="MIL"),
        Pick(origin="MIA", year=2033, round=2, to="MIL"),
    ],
)

KESSLER = Trade(
    name="Kessler to the Lakers — future capital Utah now controls",
    teams=("LAL", "UTA"),
    assets=[
        Pick(origin="LAL", year=2031, round=1, to="UTA"),          # unprotected
        Pick(origin="LAL", year=2033, round=1, to="UTA"),          # unprotected
        Swap(year=2028, round=1, teams=("UTA", "LAL"), who_chooses="UTA"),
        Swap(year=2030, round=1, teams=("UTA", "LAL"), who_chooses="UTA"),
    ],
)

# --- Conditional structures (protected picks) -------------------------------
WIZARDS_KNICKS = Trade(
    name="Wizards 1st to New York — top-8 protected",
    teams=("WAS", "NYK"),
    assets=[
        ProtectedPick(
            origin="WAS", round=1,
            schedule=((2026, Protection.top(8)),),
            to="NYK",
            fallback="becomes Washington's 2026 + 2027 second-round picks to NYK",
        )
    ],
)

BLAZERS_BULLS = Trade(
    name="Blazers 1st to Chicago — top-14 protected, rolling",
    teams=("POR", "CHI"),
    assets=[
        ProtectedPick(
            origin="POR", round=1,
            schedule=((2026, Protection.top(14)), (2027, Protection.top(14))),
            to="CHI",
            fallback="protection lapses — obligation resolves per the trade terms",
        )
    ],
)

SIXERS_OKC = Trade(
    name="76ers 1st to Oklahoma City — top-4 protected, rolling",
    teams=("PHI", "OKC"),
    assets=[
        ProtectedPick(
            origin="PHI", round=1,
            schedule=((2026, Protection.top(4)), (2027, Protection.top(4))),
            to="OKC",
            fallback="protection lapses — obligation resolves per the trade terms",
        )
    ],
)

JAZZ_OKC = Trade(
    name="Jazz 1st to Oklahoma City — top-8 protected",
    teams=("UTA", "OKC"),
    assets=[
        ProtectedPick(
            origin="UTA", round=1,
            schedule=((2026, Protection.top(8)),),
            to="OKC",
            fallback="Utah retains its pick; Oklahoma City gets swap rights",
        )
    ],
)

# Every 2026 first-round obligation I have sourced terms for (for the board).
BOARD_2026_R1 = [WIZARDS_KNICKS, BLAZERS_BULLS, SIXERS_OKC, JAZZ_OKC]

RECENT_BLOCKBUSTERS = [GIANNIS, KESSLER]
CONDITIONAL_EXAMPLES = [WIZARDS_KNICKS, BLAZERS_BULLS]
ALL = {
    "giannis": GIANNIS,
    "kessler": KESSLER,
    "wizards_knicks": WIZARDS_KNICKS,
    "blazers_bulls": BLAZERS_BULLS,
    "sixers_okc": SIXERS_OKC,
    "jazz_okc": JAZZ_OKC,
}
