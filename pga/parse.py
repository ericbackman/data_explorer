"""Turn one ESPN leaderboard JSON blob into normalized, DB-ready rows.

The shapes here were reverse-engineered from live responses (see the probe
history in git). The tricky bits this module handles explicitly:

  * cut players carry 2 round-linescores, finishers 4, WD/DQ players anywhere
    from 0-4 -- so "number of rounds" is per-player, never assumed.
  * round to-par arrives as a display string ("E", "-7", "+1"); strokes arrive
    as a float ("value": 65.0).
  * the winner is the competitor whose final position renders as solo "1".
  * majors are flagged by name match, validated against the real schedule.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Status names ESPN uses, mapped to our compact vocabulary.
_STATUS_MAP = {
    "STATUS_FINISH": "finished",
    "STATUS_CUT": "cut",
    "STATUS_WD": "wd",
    "STATUS_WITHDRAWN": "wd",
    "STATUS_DQ": "dq",
    "STATUS_DISQUALIFIED": "dq",
}

# Substrings that identify the four men's majors. Validated per-season during the
# 2024 smoke test; "tour championship" is explicitly excluded so the FedEx Cup
# finale is never mistaken for a major.
_MAJOR_PATTERNS = (
    "masters tournament",
    "the masters",       # ESPN used "The Masters" in 2009-2011 and COVID years
    "pga championship",
    "u.s. open",
    "us open",
    "the open",          # ESPN labels The Open Championship simply "The Open"
    "open championship", # also covers the older "British Open Championship"
)


class UnsupportedEventError(Exception):
    """Raised for events that aren't individual stroke-play (team/match-play
    formats like the Presidents Cup or exhibitions). The caller skips these."""


@dataclass
class ParsedEvent:
    tournament: dict
    players: list[dict] = field(default_factory=list)
    rounds: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)


def is_major(name: str) -> bool:
    n = (name or "").strip().lower()
    if "tour championship" in n:
        return False
    return any(p in n for p in _MAJOR_PATTERNS)


def parse_to_par(display: str | None) -> int | None:
    """'E'->0, '-7'->-7, '+1'->1, junk/None->None."""
    if display is None:
        return None
    d = display.strip()
    if d in ("E", "e"):
        return 0
    try:
        return int(d.replace("+", ""))
    except ValueError:
        return None


def parse_position(pos: dict | None) -> tuple[str | None, int | None, bool]:
    """Return (display, numeric, is_tie). 'T6'->('T6',6,True); '-'->('-',None,_)."""
    if not pos:
        return (None, None, None)
    disp = pos.get("displayName")
    is_tie = bool(pos.get("isTie"))
    if not disp or disp == "-":
        return (disp, None, is_tie)
    try:
        return (disp, int(disp.lstrip("T")), is_tie)
    except ValueError:
        return (disp, None, is_tie)


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


# The lowest 18-hole round in PGA Tour history is 58 (Jim Furyk, 2016). ESPN
# records unplayed rounds as value 0 and *partial* rounds (mid-round withdrawals)
# as a low partial total -- e.g. a "50" with an 11-stroke front nine. Both are
# placeholders that, left in, silently corrupt leader math, so we null them.
_MIN_PLAUSIBLE_ROUND = 58
# A completed nine is never under ~26 strokes; a positive value below this means
# the player walked off mid-round and only part of a nine is recorded.
_MIN_PLAUSIBLE_NINE = 26


def _valid_round_strokes(value, out_score=None, in_score=None) -> int | None:
    strokes = _int_or_none(value)
    if strokes is None or strokes < _MIN_PLAUSIBLE_ROUND:
        return None
    for nine in (out_score, in_score):
        n = _int_or_none(nine)
        if n is not None and 0 < n < _MIN_PLAUSIBLE_NINE:
            return None  # partial round: a played nine can't be this low
    return strokes


def _venue(event: dict) -> dict:
    courses = event.get("courses") or []
    primary = next((c for c in courses if c.get("isPrimary")), courses[0] if courses else {})
    address = primary.get("address", {}) if isinstance(primary, dict) else {}
    return {
        "venue": primary.get("name") if isinstance(primary, dict) else None,
        "city": address.get("city"),
        "state": address.get("state"),
        "par": _int_or_none(primary.get("shotsToPar")) if isinstance(primary, dict) else None,
    }


def parse_leaderboard(raw: dict) -> ParsedEvent:
    """Normalize one ``leaderboard?event=`` response into ParsedEvent."""
    events = raw.get("events") or []
    if not events:
        raise ValueError("leaderboard payload has no events")
    event = events[0]
    competitions = event.get("competitions") or []
    if not competitions:
        # Older match-play events (e.g. WGC Match Play) carry no stroke-play
        # competition block at all -- an expected skip, not a failure.
        raise UnsupportedEventError(
            f"event {event.get('id')} '{event.get('name')}' has no competition block"
        )
    competition = competitions[0]
    # Team/match-play events (Presidents Cup, exhibitions) nest competitions as a
    # list-of-sessions rather than a single competition dict -- skip them.
    if not isinstance(competition, dict):
        raise UnsupportedEventError(
            f"event {event.get('id')} '{event.get('name')}' is not individual stroke-play"
        )
    competitors = competition.get("competitors") or []
    if not competitors:
        raise UnsupportedEventError(
            f"event {event.get('id')} '{event.get('name')}' has no competitors"
        )

    event_id = _int_or_none(event.get("id"))
    season = (event.get("season") or {}).get("year")
    venue = _venue(event)

    players: list[dict] = []
    rounds: list[dict] = []
    results: list[dict] = []
    winner_id: int | None = None
    max_round = 0

    for comp in competitors:
        athlete = comp.get("athlete") or {}
        pid = _int_or_none(athlete.get("id"))
        if pid is None:
            logger.debug("skipping competitor with no athlete id in event %s", event_id)
            continue

        players.append({
            "player_id": pid,
            "name": athlete.get("displayName"),
            "country": (athlete.get("flag") or {}).get("alt"),
        })

        status_type = (comp.get("status") or {}).get("type") or {}
        status = _STATUS_MAP.get(status_type.get("name"), "other")
        disp, num, is_tie = parse_position((comp.get("status") or {}).get("position"))
        if disp == "1" and not is_tie:
            winner_id = pid

        score = comp.get("score") or {}
        results.append({
            "event_id": event_id,
            "player_id": pid,
            "position": disp,
            "position_numeric": num,
            "is_tie": int(bool(is_tie)) if is_tie is not None else None,
            "total_strokes": _int_or_none(score.get("value")),
            "total_to_par": parse_to_par(score.get("displayValue")),
            "status": status,
            "made_cut": int(status != "cut"),
            "earnings": comp.get("earnings"),
            "amateur": int(bool(comp.get("amateur"))),
        })

        seen_rounds: set[int] = set()
        for ls in comp.get("linescores") or []:
            rnd = _int_or_none(ls.get("period"))
            if rnd is None:
                continue
            if rnd in seen_rounds:
                # Defensive: an 18-hole playoff can repeat a period. Keep the
                # first, log the rest rather than silently colliding on the PK.
                logger.warning("event %s player %s duplicate round %s -- keeping first",
                               event_id, pid, rnd)
                continue
            seen_rounds.add(rnd)
            strokes = _valid_round_strokes(ls.get("value"), ls.get("outScore"), ls.get("inScore"))
            # If the round wasn't really played, drop its to-par too so nothing
            # downstream mistakes a placeholder for a completed round.
            to_par = parse_to_par(ls.get("displayValue")) if strokes is not None else None
            if strokes is not None:
                max_round = max(max_round, rnd)
            rounds.append({
                "event_id": event_id,
                "player_id": pid,
                "round_num": rnd,
                "strokes": strokes,
                "to_par": to_par,
                "out_score": _int_or_none(ls.get("outScore")),
                "in_score": _int_or_none(ls.get("inScore")),
                "is_playoff": int(bool(ls.get("isPlayoff"))),
            })

    name = event.get("name") or event.get("shortName") or ""
    start_date = event.get("date")
    # ESPN tags fall/COVID-shifted events to the next tour-season; for major-year
    # queries the actual calendar year of the start date is what users expect.
    calendar_year = int(start_date[:4]) if start_date and start_date[:4].isdigit() else season
    tournament = {
        "event_id": event_id,
        "season": season,
        "calendar_year": calendar_year,
        "name": name,
        "short_name": event.get("shortName"),
        "start_date": event.get("date"),
        "end_date": event.get("endDate"),
        "venue": venue["venue"],
        "city": venue["city"],
        "state": venue["state"],
        "par": venue["par"],
        "purse": event.get("purse"),
        "playoff_type": (event.get("playoffType") or {}).get("type"),
        "num_rounds": max_round,
        "field_size": len(players),
        "is_major": int(is_major(name)),
        "winner_player_id": winner_id,
    }
    return ParsedEvent(tournament=tournament, players=players, rounds=rounds, results=results)
