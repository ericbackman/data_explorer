"""Parse ESPN soccer scoreboard JSON into the rows db.py loads.

A single scoreboard response for a tournament edition carries everything the
Tier-1 broad layer needs: the match list with final scores and penalty
shootouts, plus an embedded `details` event stream (goals, cards, penalties).
We translate ESPN's shape into our normalized rows here and nowhere else, so the
DB schema never has to know ESPN's field names.

Raw-facts discipline (cf. pga/parse.py): we record what happened (a goal at 36',
a shootout that finished 4-2) and leave *interpretation* (who "won", scorer
tables, xG) to query time.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── competition registry ──────────────────────────────────────────────────────
# Static metadata per competition. competition_id is assigned explicitly (not
# hashed) so ids stay stable and human-readable across rebuilds. Only fifa.world
# is scraped today; the rest are wired in so the schema/registry are ready when
# we extend (the user picked Euro, Champions League, and the top-5 leagues).
@dataclass(frozen=True)
class CompetitionMeta:
    competition_id: int
    slug: str
    name: str
    kind: str           # 'international_cup' | 'club_cup' | 'league'
    confederation: str  # 'FIFA' | 'UEFA' | country code for domestic leagues


COMPETITIONS: dict[str, CompetitionMeta] = {
    "fifa.world":     CompetitionMeta(1,  "fifa.world",     "FIFA World Cup",              "international_cup", "FIFA"),
    "uefa.euro":      CompetitionMeta(2,  "uefa.euro",      "UEFA European Championship",  "international_cup", "UEFA"),
    "uefa.champions": CompetitionMeta(3,  "uefa.champions", "UEFA Champions League",       "club_cup",         "UEFA"),
    "eng.1":          CompetitionMeta(10, "eng.1",          "English Premier League",      "league",           "ENG"),
    "esp.1":          CompetitionMeta(11, "esp.1",          "Spanish La Liga",             "league",           "ESP"),
    "ita.1":          CompetitionMeta(12, "ita.1",          "Italian Serie A",             "league",           "ITA"),
    "ger.1":          CompetitionMeta(13, "ger.1",          "German Bundesliga",           "league",           "GER"),
    "fra.1":          CompetitionMeta(14, "fra.1",          "French Ligue 1",              "league",           "FRA"),
}


def season_id_for(competition_id: int, year: int) -> int:
    """Stable surrogate key for a (competition, year) edition."""
    return competition_id * 10000 + year


@dataclass
class ParsedSeason:
    competition: dict
    season: dict | None       # None when the year had no matches (skip the load)
    teams: list[dict]
    matches: list[dict]
    events: list[dict]
    players: list[dict]       # dimension rows captured from event scorers/carded players


# ── small helpers ─────────────────────────────────────────────────────────────
_CLOCK_RE = re.compile(r"(\d+)(?:'\+(\d+))?")


def parse_clock(display: str | None) -> tuple[int | None, int | None]:
    """ "45'+7'" -> (45, 7);  "23'" -> (23, None);  None/"" -> (None, None). """
    if not display:
        return None, None
    m = _CLOCK_RE.match(display.strip())
    if not m:
        return None, None
    base = int(m.group(1))
    extra = int(m.group(2)) if m.group(2) else None
    return base, extra


def _to_int(val) -> int | None:
    """ESPN scores arrive as strings ('3'); unplayed matches may carry '' / None."""
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def classify_event(detail: dict) -> str:
    """Normalize one ESPN `details` entry into our event vocabulary.

    The order matters: a shootout kick and an own goal are both "scoring plays"
    in ESPN's flags, but mean very different things for analysis, so we test the
    specific flags before the generic ones.

      Shootout Penalty  -> a kick in the post-match shootout (NOT a match goal;
                           the shootout result already lives in matches.*_pens)
      Own Goal          -> credited to the conceding player, counts for the
                           opponent on the scoreboard
      Penalty           -> a penalty *scored in normal play* (a real goal)
      Goal              -> open-play goal
      Red/Yellow Card, Substitution, else the raw ESPN text (audit trail)
    """
    if detail.get("shootout"):
        return "Shootout Penalty"
    if detail.get("ownGoal"):
        return "Own Goal"
    if detail.get("scoringPlay") and detail.get("penaltyKick"):
        return "Penalty"
    if detail.get("scoringPlay"):
        return "Goal"
    if detail.get("redCard"):
        return "Red Card"
    if detail.get("yellowCard"):
        return "Yellow Card"
    text = (detail.get("type") or {}).get("text", "")
    if "Substitution" in text:
        return "Substitution"
    return text or "Unknown"


# ─────────────────────────────────────────────────────────────────────────────
# TODO(user) — implement match_outcome().  See the message in chat.
# ─────────────────────────────────────────────────────────────────────────────
def match_outcome(home_score: int | None, away_score: int | None,
                  home_pens: int | None, away_pens: int | None) -> str | None:
    """Derive a match's result: 'H' (home win), 'A' (away win), 'D' (draw), or
    None if the match hasn't been played yet (scores are None).

    The interesting case is a knockout tie level after extra time and decided on
    penalties (home_pens/away_pens are non-None). FIFA officially records that as
    a DRAW — the shootout only decides who advances, not who "won" the match. But
    a fan would say the team that converted more penalties won. Both are valid;
    the choice changes every win/draw/loss tally we ever compute from this DB.

    This is the soccer analogue of pga/'s "did the 54-hole leader convert?" — a
    definition, not a fact, so it lives in code you own.

    Currently returns None for every match (the `outcome` column stays empty and
    the scraper says so loudly). Implement the rule you want, then re-run the
    scrape (it's idempotent) to backfill the column.
    """
    return None  # <-- replace with your rule


# ── the parser ────────────────────────────────────────────────────────────────
def parse_scoreboard(meta: CompetitionMeta, year: int, data: dict) -> ParsedSeason:
    """Translate one calendar year's scoreboard into normalized rows."""
    competition = {
        "competition_id": meta.competition_id,
        "slug": meta.slug,
        "name": meta.name,
        "kind": meta.kind,
        "confederation": meta.confederation,
    }
    events_json = data.get("events", [])
    teams: dict[int, dict] = {}
    players: dict[int, dict] = {}
    matches: list[dict] = []
    events: list[dict] = []
    dates: list[str] = []

    sid = season_id_for(meta.competition_id, year)
    for ev in events_json:
        match, ev_teams, ev_events, ev_players = _parse_match(meta, sid, ev)
        if match is None:
            continue
        matches.append(match)
        events.extend(ev_events)
        for t in ev_teams:
            teams[t["team_id"]] = t
        for p in ev_players:
            players[p["player_id"]] = p
        if match["date"]:
            dates.append(match["date"])

    season = None
    if matches:
        season = {
            "season_id": sid,
            "competition_id": meta.competition_id,
            "year": year,
            "name": str(year),
            "host": None,  # filled by a later enrichment pass; unknown from scoreboard
            "start_date": min(dates) if dates else None,
            "end_date": max(dates) if dates else None,
        }
    return ParsedSeason(competition, season, list(teams.values()), matches, events,
                        list(players.values()))


def _parse_match(meta: CompetitionMeta, season_id: int, ev: dict):
    """Return (match_row, [team_rows], [event_rows], [player_rows]) for one event."""
    comps = ev.get("competitions") or []
    if not comps:
        return None, [], [], []
    comp = comps[0]
    competitors = comp.get("competitors") or []
    if len(competitors) != 2:
        return None, [], [], []  # malformed / placeholder fixture

    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None or away is None:
        return None, [], [], []

    match_id = _to_int(ev.get("id"))
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    home_score = _to_int(home.get("score"))
    away_score = _to_int(away.get("score"))
    home_pens = _to_int(home.get("shootoutScore"))
    away_pens = _to_int(away.get("shootoutScore"))

    match = {
        "match_id": match_id,
        "competition_id": meta.competition_id,
        "season_id": season_id,
        "date": ev.get("date"),
        "round": (ev.get("season") or {}).get("slug"),
        "venue": venue.get("fullName"),
        "city": addr.get("city"),
        "country": addr.get("country"),
        "neutral": _bool_int(comp.get("neutralSite")),
        "status": ((comp.get("status") or {}).get("type") or {}).get("description"),
        "home_team_id": _to_int((home.get("team") or {}).get("id")),
        "away_team_id": _to_int((away.get("team") or {}).get("id")),
        "home_score": home_score,
        "away_score": away_score,
        "home_ht": None,  # halftime not exposed at scoreboard level; summary tier later
        "away_ht": None,
        "home_pens": home_pens,
        "away_pens": away_pens,
        "attendance": _to_int(comp.get("attendance")),
        "outcome": match_outcome(home_score, away_score, home_pens, away_pens),
    }

    teams = [_team_row(home), _team_row(away)]
    events, players = _parse_details(match_id, comp.get("details") or [])
    return match, [t for t in teams if t], events, list(players.values())


def _team_row(competitor: dict) -> dict | None:
    t = competitor.get("team") or {}
    tid = _to_int(t.get("id"))
    if tid is None:
        return None
    return {
        "team_id": tid,
        "name": t.get("displayName"),
        "abbreviation": t.get("abbreviation"),
        "country": t.get("location"),  # for national teams ~= name; for clubs, the city/country
    }


def _parse_details(match_id: int, details: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (event_rows, player_dimension_rows). Capturing the scorer/carded
    player's *name* here lets "most World Cup goals" resolve to names from the
    cheap scoreboard tier alone, without the per-match lineup pull.
    """
    rows: list[dict] = []
    players: dict[int, dict] = {}
    for seq, d in enumerate(details):
        minute, extra = parse_clock((d.get("clock") or {}).get("displayValue"))
        athletes = d.get("athletesInvolved") or []
        for a in athletes:
            aid = _to_int(a.get("id"))
            if aid is not None and aid not in players:
                players[aid] = {"player_id": aid, "name": a.get("displayName"), "position": None}
        player_id = _to_int(athletes[0].get("id")) if athletes else None
        assist_id = _to_int(athletes[1].get("id")) if len(athletes) > 1 else None
        rows.append({
            "match_id": match_id,
            "seq": seq,
            "minute": minute,
            "minute_extra": extra,
            "type": classify_event(d),
            "team_id": _to_int((d.get("team") or {}).get("id")),
            "player_id": player_id,
            "assist_player_id": assist_id,
            "detail": (d.get("type") or {}).get("text"),
        })
    return rows, players


def _bool_int(val) -> int | None:
    if val is None:
        return None
    return 1 if val else 0
