"""NBA team reference: the 30 abbreviations and primary brand colors.

Background colors are the teams' primary brand color (reference data, not
statistics). The text color is *computed* from the background's luminance so
contrast is always legible — no hand-picked accent color can end up dark-on-dark.
"""

# abbr -> primary brand background hex
TEAM_BG: dict[str, str] = {
    "ATL": "#E03A3E", "BOS": "#007A33", "BKN": "#000000", "CHA": "#1D1160",
    "CHI": "#CE1141", "CLE": "#860038", "DAL": "#00538C", "DEN": "#0E2240",
    "DET": "#1D428A", "GSW": "#1D428A", "HOU": "#CE1141", "IND": "#002D62",
    "LAC": "#C8102E", "LAL": "#552583", "MEM": "#5D76A9", "MIA": "#98002E",
    "MIL": "#00471B", "MIN": "#0C2340", "NOP": "#0C2340", "NYK": "#006BB6",
    "OKC": "#007AC1", "ORL": "#0077C0", "PHI": "#006BB6", "PHX": "#1D1160",
    "POR": "#E03A3E", "SAC": "#5A2D81", "SAS": "#C4CED4", "TOR": "#CE1141",
    "UTA": "#002B5C", "WAS": "#002B5C",
}

# Stable display order (alphabetical) for boards.
TEAMS: tuple[str, ...] = tuple(sorted(TEAM_BG))

_DARK_TEXT = "#1a2233"
_LIGHT_TEXT = "#ffffff"


def _contrast_fg(bg: str) -> str:
    """Pick dark or light text for a background by perceived luminance."""
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    # Rec. 601 luma; > ~150 reads as a light background.
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    return _DARK_TEXT if luma > 150 else _LIGHT_TEXT


def color(team: str) -> tuple[str, str]:
    """(background, foreground) for a team; grey fallback for unknowns."""
    bg = TEAM_BG.get(team)
    if bg is None:
        return ("#e5e7eb", _DARK_TEXT)
    return (bg, _contrast_fg(bg))
