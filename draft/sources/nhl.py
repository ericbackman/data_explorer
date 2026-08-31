"""NHL draft — records.nhl.com draft records (1963+).

Fetched one year at a time (the API filters with a cayenne expression). NHL is
the only league here with a *supplemental* draft (1986-1994) and with picks that
were later voided (`removedOutright`), so both get explicit handling: supplemental
picks are tagged `draft_type='supplemental'` (they reuse the regular overall
numbers, and the draft_type partition keeps the key unique), and voided picks are
dropped — they aren't players who were actually drafted and kept.
"""
from __future__ import annotations

import datetime
import logging

from ._http import get_json

log = logging.getLogger(__name__)

SOURCE = "nhl_records"
SPORT = "NHL"
FIRST_YEAR = 1963  # first NHL Amateur Draft
_URL = "https://records.nhl.com/site/api/draft?cayenneExp=draftYear={year}"


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
    data = payload.get("data", []) or []
    total = payload.get("total")
    if isinstance(total, int) and len(data) < total:  # defend against a server-side cap
        payload = get_json(_URL.format(year=year) + f"&start=0&limit={total}")
        data = payload.get("data", []) or []

    rows, dropped = [], 0
    for r in data:
        if (r.get("removedOutright") or "N").strip().upper() == "Y":
            dropped += 1
            continue
        supplemental = (r.get("supplementalDraft") or "N").strip().upper() == "Y"
        rows.append({
            "sport": SPORT,
            "draft_year": _int(r.get("draftYear")) or year,
            "draft_type": "supplemental" if supplemental else "regular",
            "round": _int(r.get("roundNumber")),
            "pick_in_round": _int(r.get("pickInRound")),
            "overall_pick": _int(r.get("overallPickNumber")) or 0,
            "team_abbr": _clean(r.get("triCode")),
            "team_name": None,  # feed gives only the tricode
            "native_team_id": _clean(r.get("draftedByTeamId")),
            "player_name": _clean(r.get("playerName")),
            "native_player_id": _clean(r.get("playerId")),
            "position": _clean(r.get("position")),
            "origin": _clean(r.get("amateurClubName")),
            "origin_type": _clean(r.get("amateurLeague")),
            "source": SOURCE,
        })
    if dropped:
        log.info("NHL %d: dropped %d voided (removedOutright) pick(s)", year, dropped)
    return rows


def fetch(years=None) -> list[dict]:
    """Normalized NHL draft rows. `years` = optional iterable; default 1963..now."""
    if years is None:
        years = range(FIRST_YEAR, datetime.date.today().year + 1)
    rows, failed = [], []
    for year in years:
        try:
            yr = _year_rows(year)
        except Exception as e:  # one bad year must not abort the whole pull
            log.error("NHL %s failed: %s — skipping (re-run to retry)", year, e)
            failed.append(year)
            continue
        if not yr:
            continue  # year not drafted yet / no data
        rows.extend(yr)
        log.info("NHL %d: %d picks", year, len(yr))
    if failed:
        log.warning("NHL: %d year(s) failed: %s", len(failed), failed)
    return rows
