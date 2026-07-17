"""OSRS Hiscores JSON -> normalized rows, plus the XP/level math.

Pure functions: data in, data out. No network, no DB, no clock — so every rule
here (the exponential XP curve, unranked clamping, snapshot diffing) is unit-
tested against fixtures. Derived competition scoring lives in scoring.py.
"""

from __future__ import annotations

# The 24 trainable skills + the "Overall" total, in Hiscores order (Sailing was
# added in 2025). We read skill names straight from the API — this tuple is only
# a reference/ordering aid, so a future new skill flows through parsing untouched.
SKILLS = (
    "Overall", "Attack", "Defence", "Strength", "Hitpoints", "Ranged",
    "Prayer", "Magic", "Cooking", "Woodcutting", "Fletching", "Fishing",
    "Firemaking", "Crafting", "Smithing", "Mining", "Herblore", "Agility",
    "Thieving", "Slayer", "Farming", "Runecraft", "Hunter", "Construction",
    "Sailing",
)
MAX_LEVEL = 99  # in-game skill cap (virtual levels beyond 99 are out of scope)


def _build_xp_table() -> tuple[int, ...]:
    """XP required to *reach* each level 1..99, indexed by level.

    OSRS' exponential curve:
        XP(L) = floor( 1/4 * sum_{n=1}^{L-1} floor(n + 300 * 2^(n/7)) )
    Famously, level 92 is ~half the XP of level 99 — which is exactly why the
    choice of competition metric (scoring.py) matters so much.
    """
    table = [0, 0]   # index 0 unused; level 1 = 0 xp
    total = 0
    for n in range(1, MAX_LEVEL):
        total += int(n + 300 * 2 ** (n / 7.0))  # int() floors each term
        table.append(total // 4)
    return tuple(table)


_XP_AT_LEVEL = _build_xp_table()


def xp_for_level(level: int) -> int:
    if level <= 1:
        return 0
    if level > MAX_LEVEL:
        raise ValueError(f"level {level} > {MAX_LEVEL} (virtual levels unsupported)")
    return _XP_AT_LEVEL[level]


def level_for_xp(xp: int, cap: int = MAX_LEVEL) -> int:
    """Highest level whose XP threshold is <= xp (1..cap)."""
    xp = max(int(xp), 0)
    level = 1
    while level < cap and _XP_AT_LEVEL[level + 1] <= xp:
        level += 1
    return level


def canonical_rsn(name: str) -> str:
    """Case/separator-insensitive key for a RuneScape name.

    OSRS treats 'Lynx_Titan', 'lynx titan' and 'Lynx Titan' as the same account,
    so we key on a normalized form and store the display spelling separately.
    """
    return " ".join(name.strip().lower().replace("_", " ").split())


def _clamp_rank(rank) -> int | None:
    # Hiscores returns rank -1 for "not ranked"; store that as unknown (None).
    rank = int(rank) if rank is not None else -1
    return rank if rank > 0 else None


def parse_hiscores(payload: dict) -> list[dict]:
    """Normalize the index_lite.json 'skills' array into our row dicts.

    Unranked entries come back as -1; XP is floored at 0 (a real account always
    has >= 0 XP, and -1 only means 'outside the ranked Hiscores').
    """
    skills = []
    for s in payload.get("skills", []):
        skills.append({
            "skill": s["name"],
            "rank": _clamp_rank(s.get("rank")),
            "level": max(int(s.get("level", 1)), 1),
            "xp": max(int(s.get("xp", 0)), 0),
        })
    if not skills:
        raise ValueError("hiscores payload contained no skills")
    return skills


def overall(skills: list[dict]) -> dict:
    for s in skills:
        if s["skill"] == "Overall":
            return s
    raise ValueError("no 'Overall' row in skills")


def diff_snapshots(
    before: list[dict],
    after: list[dict],
    include_overall: bool = False,
) -> list[dict]:
    """Per-skill gains between two snapshots (XP and whole levels).

    'Overall' is a derived total (sum of the others), so it's excluded by default
    to avoid double-counting in scoring. Negative deltas (name swaps, Jagex data
    corrections) are floored at 0.
    """
    prev = {s["skill"]: s for s in before}
    out = []
    for s in after:
        name = s["skill"]
        if name == "Overall" and not include_overall:
            continue
        was = prev.get(name)
        if was is None:
            continue
        out.append({
            "skill": name,
            "before_xp": was["xp"], "after_xp": s["xp"],
            "xp_gained": max(s["xp"] - was["xp"], 0),
            "before_level": was["level"], "after_level": s["level"],
            "levels_gained": max(s["level"] - was["level"], 0),
        })
    return out
