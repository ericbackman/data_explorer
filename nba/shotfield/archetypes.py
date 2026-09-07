"""Map NBA play-by-play shot metadata onto animation archetypes.

Pure: no bpy, no sqlite. This is the whole shot-type dispatch, so it is testable
without a 25-minute render or a 3.6 GB database.

Three independent signals come out of the data, and they are deliberately kept
separate because they have different coverage:

  archetype(sub_type)  -- what the body does. Available for every shot.
  motion(sub_type)     -- which way the player moved into it. LABEL ONLY.
  entry(assisted)      -- caught it vs created it. MADE SHOTS ONLY.

Nothing here infers beyond what the label says. A plain "Jump Shot" gets the
neutral archetype rather than a guess, because a guess would be indistinguishable
from a fact in the finished render.
"""
from __future__ import annotations

JUMPER, LAYUP, DUNK, HOOK, TIP = "jumper", "layup", "dunk", "hook", "tip"
ARCHETYPES = (JUMPER, LAYUP, DUNK, HOOK, TIP)

TOWARD, AWAY, SCRAMBLE, NO_LABEL = "toward", "away", "scramble", "no_label"
CATCH, DRIBBLE, UNKNOWN = "catch", "dribble", "unknown"

# The NBA did not record these sub_types from the start. A game before a label's
# first-seen date contains none of it, which is a COVERAGE gap, not a fact about
# how anyone played. Measured off play_by_play joined to games.
LABEL_FIRST_SEEN = {
    "Jump Shot": "1996-11-01",
    "Driving Layup Shot": "1996-11-01",
    "Fadeaway Jump Shot": "2001-10-30",
    "Step Back Jump shot": "2007-10-30",
    "Pullup Jump shot": "2007-10-31",
}


def archetype(sub_type: str | None) -> str:
    """Which body motion to animate. Order matters: 'Tip Layup Shot' and
    'Putback Dunk Shot' each match two families, and the more specific finish
    wins."""
    s = (sub_type or "").lower()
    if "dunk" in s:
        return DUNK
    if "layup" in s or "finger roll" in s:
        return LAYUP
    if "hook" in s:
        return HOOK
    if "tip" in s or "putback" in s:
        return TIP
    return JUMPER


def motion(sub_type: str | None) -> str:
    """Direction the shooter moved into the shot, as far as the LABEL says.

    Returns NO_LABEL for a plain jump shot rather than guessing 'stationary':
    the shooter may well have moved, the data simply does not say.
    """
    s = (sub_type or "").lower()
    if s.startswith("driving") or s.startswith("cutting") or s.startswith("running"):
        return TOWARD
    if "step back" in s or "fadeaway" in s or "turnaround" in s:
        return AWAY
    if "tip" in s or "putback" in s:
        return SCRAMBLE
    return NO_LABEL


def entry(assisted: bool | None) -> str:
    """How the shooter got the ball.

    ⚠ Assists are recorded ONLY on made shots, so a miss carries no signal
    either way and gets UNKNOWN. Treating a miss as unassisted would invent a
    self-created shot for every miss in the game.
    """
    if assisted is True:
        return CATCH
    if assisted is False:
        return DRIBBLE
    return UNKNOWN


def missing_labels(game_date: str) -> list[str]:
    """Labels that did not exist yet on ``game_date`` (ISO yyyy-mm-dd).

    Call this per game and SAY SO in the output. Otherwise a 2006 game renders
    with no pull-ups and no step-backs, looks flat next to a 2024 one, and
    nothing anywhere explains why.
    """
    return sorted(name for name, since in LABEL_FIRST_SEEN.items() if game_date < since)


def classify(shot: dict) -> dict:
    """Attach archetype/motion/entry to one exported shot row."""
    return {
        **shot,
        "archetype": archetype(shot.get("sub_type")),
        "motion": motion(shot.get("sub_type")),
        "entry": entry(shot.get("assisted")),
    }


def summarise(shots: list[dict]) -> dict[str, dict[str, int]]:
    """Counts per signal, for the check pass. Coverage should be visible before
    a render is spent on it."""
    out: dict[str, dict[str, int]] = {"archetype": {}, "motion": {}, "entry": {}}
    for shot in shots:
        for key in out:
            value = shot.get(key) or classify(shot)[key]
            out[key][value] = out[key].get(value, 0) + 1
    return out
