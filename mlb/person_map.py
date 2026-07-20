"""
Draft (MLBAM id) <-> career (Lahman playerID) id bridge
========================================================
Draft picks come from MLB StatsAPI keyed by MLBAM person id. Career stats
(batting/pitching/awards/HOF) come from Lahman, keyed by the Lahman
``playerID`` string (e.g. ``piazzmi01``). Two independent, pure passes
build the bridge, in preference order:

  1. **Chadwick register** (primary). The register keys everyone by
     ``key_mlbam`` and also carries ``key_bbref`` / ``key_retro``; Lahman's
     own People.csv carries ``bbrefID`` / ``retroID``. Join
     mlbam -> (bbref or retro) -> Lahman playerID. This is an exact-key
     join, no fuzzy matching, so it's the trustworthy path.
  2. **Name + birth-year fallback** (documented, lower-confidence). For any
     drafted player the register pass didn't resolve, try an exact
     (last name, first name, birth year) match against Lahman People. Only
     accepted when exactly one Lahman playerID matches — an ambiguous
     match (e.g. two "Chris Smith, b.1985") is left unmapped rather than
     guessed, per the no-silent-wrong-answer rule.

Both passes are pure functions over already-loaded rows (no I/O), so they're
directly unit-testable against small fixture lists.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


# ── Pass 1: Chadwick register join ──────────────────────────────────────────

def index_people_by_bbref_retro(people_rows: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Lahman People rows -> ({bbrefID: playerID}, {retroID: playerID})."""
    bbref_to_id: dict[str, str] = {}
    retro_to_id: dict[str, str] = {}
    for row in people_rows:
        player_id = row.get("playerID")
        if not player_id:
            continue
        bbref_id = row.get("bbrefID")
        if bbref_id:
            bbref_to_id[bbref_id] = player_id
        retro_id = row.get("retroID")
        if retro_id:
            retro_to_id[retro_id] = player_id
    return bbref_to_id, retro_to_id


def map_register_to_lahman(
    register_rows: list[dict],
    bbref_to_id: dict[str, str],
    retro_to_id: dict[str, str],
) -> dict[int, dict]:
    """Register rows -> {mlbam_id: {"player_id": ..., "match_method": "register", "matched_via": "bbref"|"retro"}}."""
    mapping: dict[int, dict] = {}
    for row in register_rows:
        mlbam_raw = row.get("key_mlbam")
        if not mlbam_raw:
            continue
        try:
            mlbam_id = int(mlbam_raw)
        except ValueError:
            continue

        bbref_id = row.get("key_bbref")
        retro_id = row.get("key_retro")
        player_id = bbref_to_id.get(bbref_id) if bbref_id else None
        matched_via = "bbref"
        if not player_id and retro_id:
            player_id = retro_to_id.get(retro_id)
            matched_via = "retro"

        if player_id:
            mapping[mlbam_id] = {
                "player_id": player_id,
                "match_method": "register",
                "matched_via": matched_via,
            }
    return mapping


# ── Pass 2: name + birth-year fallback (lower confidence, documented) ──────

def _name_key(last: str | None, first: str | None, birth_year) -> tuple[str, str, int] | None:
    if not last or not first or not birth_year:
        return None
    try:
        year = int(birth_year)
    except (TypeError, ValueError):
        return None
    return (last.strip().lower(), first.strip().lower(), year)


def index_people_by_name_birthyear(people_rows: list[dict]) -> dict[tuple[str, str, int], list[str]]:
    """Lahman People rows -> {(last, first, birth_year): [playerID, ...]}.
    A list (not a single id) because collisions must be detectable —
    ambiguous keys are dropped by the matcher, not silently resolved."""
    index: dict[tuple[str, str, int], list[str]] = {}
    for row in people_rows:
        key = _name_key(row.get("nameLast"), row.get("nameFirst"), row.get("birthYear"))
        if key is None:
            continue
        index.setdefault(key, []).append(row["playerID"])
    return index


def _split_full_name(full_name: str) -> tuple[str, str] | None:
    """"Stephen Strasburg" -> ("Stephen", "Strasburg"). Best-effort: first
    token as given name, last token as surname. Good enough for a fallback
    pass that only accepts unambiguous single matches anyway."""
    parts = full_name.split()
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def fallback_name_birthyear_match(
    unmapped_picks: list[dict],
    name_birthyear_index: dict[tuple[str, str, int], list[str]],
) -> dict[int, dict]:
    """``unmapped_picks``: draft rows (mlbam_id, player_name, birth_date) not
    already resolved by the register pass. Returns the same mapping shape
    as ``map_register_to_lahman``, ``match_method="name_birthyear"``.
    Skips ambiguous (>1 candidate) and unparseable names/dates."""
    mapping: dict[int, dict] = {}
    for pick in unmapped_picks:
        mlbam_id = pick.get("mlbam_id")
        player_name = pick.get("player_name")
        birth_date = pick.get("birth_date")
        if not mlbam_id or not player_name or not birth_date:
            continue

        split = _split_full_name(player_name)
        if split is None:
            continue
        first, last = split
        birth_year = str(birth_date)[:4]
        key = _name_key(last, first, birth_year)
        if key is None:
            continue

        candidates = name_birthyear_index.get(key)
        if not candidates or len(candidates) != 1:
            continue  # no match, or ambiguous — don't guess

        mapping[mlbam_id] = {
            "player_id": candidates[0],
            "match_method": "name_birthyear",
            "matched_via": "name_birthyear",
        }
    return mapping
