"""NBA draft — nba_api DraftHistory.

One request returns every pick in NBA/BAA history (1947+), so there's no
per-year loop and no network cache to manage; we fetch once and filter. PERSON_ID
is the same id used in nba.db's `players`/`player_game`, so a pick joins straight
to a career.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SOURCE = "nba_api"
SPORT = "NBA"


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _draft_type(raw) -> str:
    s = (raw or "").strip().lower()
    if "territorial" in s:
        return "territorial"
    if "hardship" in s:
        return "hardship"
    if "supplemental" in s:
        return "supplemental"
    return "regular"


def _clean(v) -> str | None:
    s = (v or "").strip() if isinstance(v, str) else (str(v).strip() if v is not None else "")
    return s or None


def _fill_missing_overall(rows: list[dict]) -> list[dict]:
    """Give pre-1966 picks a derived overall_pick when the source has none.

    nba_api returns ROUND=PICK=OVERALL=0 for ~700 picks (1947-1965) — real
    players (Wilt, Russell, Baylor) the feed never numbered. We can't drop them
    and we can't leave them all at 0 (the natural key would collide), so within
    each (year, draft_type) group, in source order (which follows draft order),
    we number the unnumbered picks sequentially starting after the last real
    pick. Deterministic, so re-runs converge. These rows keep round/pick_in_round
    NULL, which flags the overall_pick as derived rather than recorded.
    """
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["draft_year"], r["draft_type"])].append(r)
    for grp in groups.values():
        nxt = max((r["overall_pick"] for r in grp if (r["overall_pick"] or 0) > 0),
                  default=0) + 1
        for r in grp:
            if not r["overall_pick"] or r["overall_pick"] <= 0:
                r["overall_pick"] = nxt
                nxt += 1
    return rows


def fetch(years=None) -> list[dict]:
    """Normalized NBA draft rows. `years` = optional iterable of ints to keep."""
    from nba_api.stats.endpoints import drafthistory  # local import: optional dep

    df = drafthistory.DraftHistory().get_data_frames()[0]
    want = set(years) if years else None
    rows = []
    for r in df.to_dict("records"):
        year = _int(r.get("SEASON"))
        if year is None or (want is not None and year not in want):
            continue
        city, nick = _clean(r.get("TEAM_CITY")), _clean(r.get("TEAM_NAME"))
        team_name = " ".join(p for p in (city, nick) if p) or None
        rows.append({
            "sport": SPORT,
            "draft_year": year,
            "draft_type": _draft_type(r.get("DRAFT_TYPE")),
            "round": _int(r.get("ROUND_NUMBER")) or None,       # 0 == "unrecorded" -> NULL
            "pick_in_round": _int(r.get("ROUND_PICK")) or None,  # (rounds/picks start at 1)
            "overall_pick": _int(r.get("OVERALL_PICK")) or 0,    # 0 -> filled by _fill_missing_overall
            "team_abbr": _clean(r.get("TEAM_ABBREVIATION")),
            "team_name": team_name,
            "native_team_id": _clean(r.get("TEAM_ID")),
            "player_name": _clean(r.get("PLAYER_NAME")),
            "native_player_id": _clean(r.get("PERSON_ID")),
            "position": None,  # DraftHistory carries no position
            "origin": _clean(r.get("ORGANIZATION")),
            "origin_type": _clean(r.get("ORGANIZATION_TYPE")),
            "source": SOURCE,
        })
    rows = _fill_missing_overall(rows)
    log.info("NBA: %d picks%s", len(rows), f" ({min(years)}-{max(years)})" if years else "")
    return rows
