"""MLB draft — MLB Stats API (1965+).

The richest but messiest feed: deeply nested (drafts.rounds[].picks[].person{})
and full of slots that aren't real selections — forfeited picks and "passes"
(isPass). Those are dropped; only picks with an actual person are kept. Round
labels include non-numeric competitive-balance rounds ("CBA"), so `round` is
NULL when it isn't a plain integer (the overall pick number still orders them).
"""
from __future__ import annotations

import datetime
import logging

from ._http import get_json
from ..teams import mlb_abbr

log = logging.getLogger(__name__)

SOURCE = "mlb_statsapi"
SPORT = "MLB"
FIRST_YEAR = 1965  # first MLB amateur draft
_URL = "https://statsapi.mlb.com/api/v1/draft/{year}"


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clean(v) -> str | None:
    s = (v or "").strip() if isinstance(v, str) else (str(v).strip() if v is not None else "")
    return s or None


def _year_rows(year: int) -> list[dict]:
    payload = get_json(_URL.format(year=year))
    rounds = payload.get("drafts", {}).get("rounds", []) or []
    rows, passed, dup = [], 0, 0
    seen: set[tuple] = set()
    for rnd in rounds:
        for p in rnd.get("picks", []) or []:
            person = p.get("person") or {}
            if p.get("isPass") or not person.get("id"):
                passed += 1
                continue  # forfeited slot / pass — not a drafted player
            # The feed occasionally repeats a pick verbatim (same overall + same
            # player, e.g. 2008 #127). Drop the exact repeat; two *different*
            # players at one pick keep distinct keys and would trip the load guard.
            dedup_key = (_int(p.get("pickNumber")) or 0, str(person.get("id")))
            if dedup_key in seen:
                dup += 1
                continue
            seen.add(dedup_key)
            team = p.get("team") or {}
            school = p.get("school") or {}
            pos = (person.get("primaryPosition") or {}).get("abbreviation")
            team_id = _int(team.get("id"))
            rows.append({
                "sport": SPORT,
                "draft_year": _int(p.get("year")) or year,
                "draft_type": "regular",
                "round": _int(rnd.get("round")),  # NULL for "CBA"/"CBB" etc.
                "pick_in_round": _int(p.get("roundPickNumber")),
                "overall_pick": _int(p.get("pickNumber")) or 0,
                "team_abbr": mlb_abbr(team_id),
                "team_name": _clean(team.get("name")),
                "native_team_id": _clean(team_id),
                "player_name": _clean(person.get("fullName")),
                "native_player_id": _clean(person.get("id")),
                "position": _clean(pos),
                "origin": _clean(school.get("name")),
                "origin_type": _clean(school.get("schoolClass")),
                "source": SOURCE,
            })
    if passed or dup:
        log.info("MLB %d: skipped %d pass/forfeited, %d duplicate slot(s)", year, passed, dup)
    return rows


def fetch(years=None) -> list[dict]:
    """Normalized MLB draft rows. `years` = optional iterable; default 1965..now."""
    if years is None:
        years = range(FIRST_YEAR, datetime.date.today().year + 1)
    rows, failed = [], []
    for year in years:
        try:
            yr = _year_rows(year)
        except Exception as e:  # one bad year must not abort the whole pull
            log.error("MLB %s failed: %s — skipping (re-run to retry)", year, e)
            failed.append(year)
            continue
        if not yr:
            continue
        rows.extend(yr)
        log.info("MLB %d: %d picks", year, len(yr))
    if failed:
        log.warning("MLB: %d year(s) failed: %s", len(failed), failed)
    return rows
