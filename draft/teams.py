"""Team identity helpers for draft data.

Two jobs:

1. `mlb_abbr(team_id)` — MLB's draft feed gives a team *name* but no code, so we
   map its stable franchise id to an abbreviation. Relocations keep the same id
   (Expos id 120 -> WSH), so this doubles as franchise normalization for MLB.

2. `current_franchise(sport, code)` — an OPT-IN analysis helper that rolls a
   historical code up to the present-day franchise for the handful of clean,
   unambiguous relocations. It is deliberately NOT applied at load time: the
   stored `team_abbr` stays faithful to what the source said on draft day.

   Why opt-in and conservative? Team codes are era-ambiguous. NFL `STL` was the
   Rams (1995-2015 -> LAR) AND, earlier, the Cardinals (-> ARI); NBA history is
   worse. A blanket code->franchise map would be silently wrong for old picks, so
   we only encode moves that are unambiguous from the code alone, and pass
   everything else through unchanged. `team_name` always preserves the truth.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# MLB statsapi franchise id -> current abbreviation (the 30 live franchises; old
# clubs share their successor's id, e.g. Seattle Pilots == Brewers == 158).
MLB_TEAM_ABBR = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC", 113: "CIN",
    114: "CLE", 115: "COL", 116: "DET", 117: "HOU", 118: "KC", 119: "LAD",
    120: "WSH", 121: "NYM", 133: "ATH", 134: "PIT", 135: "SD", 136: "SEA",
    137: "SF", 138: "STL", 139: "TB", 140: "TEX", 141: "TOR", 142: "MIN",
    143: "PHI", 144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}

# Unambiguous, recent relocations/renames only — safe to roll up from the code.
# (sport, as-drafted code) -> current code. Anything not here passes through.
_CURRENT_FRANCHISE = {
    ("NBA", "SEA"): "OKC",   # Seattle SuperSonics -> Oklahoma City Thunder
    ("NBA", "NJN"): "BKN",   # New Jersey Nets -> Brooklyn
    ("NBA", "VAN"): "MEM",   # Vancouver -> Memphis Grizzlies
    ("NBA", "NOH"): "NOP",   # New Orleans Hornets -> Pelicans
    ("NBA", "NOK"): "NOP",   # New Orleans/Oklahoma City Hornets -> Pelicans
    ("NBA", "WSB"): "WAS",   # Washington Bullets -> Wizards
    ("NBA", "SDC"): "LAC",   # San Diego Clippers -> LA Clippers
    ("NBA", "KCK"): "SAC",   # Kansas City Kings -> Sacramento
    ("NFL", "OAK"): "LV",    # Oakland Raiders -> Las Vegas
    ("NFL", "SD"):  "LAC",   # San Diego Chargers -> LA
    ("NFL", "SDG"): "LAC",
    ("NHL", "ATL"): "WPG",   # Atlanta Thrashers -> Winnipeg Jets (2.0)
    ("NHL", "PHX"): "UTA",   # Phoenix/Arizona Coyotes -> Utah
    ("NHL", "ARI"): "UTA",
}


def mlb_abbr(team_id: int | None) -> str | None:
    """Current abbreviation for an MLB franchise id, or None (logged) if unknown."""
    if team_id is None:
        return None
    abbr = MLB_TEAM_ABBR.get(int(team_id))
    if abbr is None:
        log.warning("MLB team id %s not in MLB_TEAM_ABBR — team_abbr left null", team_id)
    return abbr


def current_franchise(sport: str, code: str | None) -> str | None:
    """Roll a historical code up to today's franchise (opt-in, analysis-time).

    Only rewrites unambiguous relocations; unknown/unmapped codes pass through.
    Intentionally NOT used by the loaders — `team_abbr` stays as-drafted.
    """
    if code is None:
        return None
    return _CURRENT_FRANCHISE.get((sport, code), code)
