"""
NHL API client + boxscore parsing
==================================
Thin, testable wrapper over the modern NHL endpoints:

  * api.nhle.com/stats/rest  -> bulk game index (one call lists every game)
  * api-web.nhle.com/v1      -> per-game boxscore (player-by-player stats)

Network code (sessions, retry, timeout) is kept separate from the pure
parse_* functions so the parsers can be unit-tested against captured JSON
fixtures without hitting the network.
"""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# ── Endpoints ───────────────────────────────────────────────────────────────
STATS_BASE = "https://api.nhle.com/stats/rest/en"
WEB_BASE = "https://api-web.nhle.com/v1"
GAME_INDEX_URL = f"{STATS_BASE}/game"
BOXSCORE_URL = WEB_BASE + "/gamecenter/{game_id}/boxscore"
PBP_URL = WEB_BASE + "/gamecenter/{game_id}/play-by-play"

USER_AGENT = "data_explorer/nhl (https://github.com/ericbackman/data_explorer)"
HTTP_TIMEOUT = 25  # seconds, per request

# Game types worth keeping in a boxscore DB: 2 = regular season, 3 = playoffs.
KEEP_GAME_TYPES = (2, 3)
# gameStateId 7 == "OFF" (final). Anything else is scheduled / live / postponed.
FINAL_STATE_ID = 7

# Real-Time Scoring System era: first season with full per-player boxscores
# (TOI, hits, blocks, takeaways/giveaways, faceoff%). Probed and confirmed.
RTSS_FIRST_SEASON = 19971998

# First season the play-by-play feed carries x/y coordinates + the full event
# vocabulary (hits, faceoffs, blocks, give/takeaways). Probed: 2008-09 = 0%
# coverage, 2009-10 = ~83%. Before this, plays exist but are goals/penalties
# /shots only, with NULL coordinates.
PBP_FIRST_COORD_SEASON = 20092010


# ── HTTP session ─────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    """A session that retries transient failures (429 + 5xx) with backoff and
    honors Retry-After, per the workspace standard for external calls."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,                       # 0s, 1s, 2s, 4s, 8s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def get_json(session: requests.Session, url: str) -> dict:
    """GET with a hard timeout; raise loudly on a non-2xx that survived retries."""
    resp = session.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── Game index ───────────────────────────────────────────────────────────────

def fetch_game_index(session: requests.Session) -> list[dict]:
    """Every game the NHL has a record of (~74k rows) in a single call.

    Each row has: id, season (int e.g. 19971998), gameType, gameDate,
    gameStateId, homeTeamId, visitingTeamId, homeScore, visitingScore.
    """
    payload = get_json(session, GAME_INDEX_URL)
    rows = payload.get("data", [])
    log.info("Game index returned %d rows", len(rows))
    return rows


def select_games(rows: list[dict], min_season: int) -> list[dict]:
    """Filter the raw index down to final regular-season + playoff games at or
    after ``min_season`` (season is the 8-digit int, e.g. 19971998)."""
    return [
        g for g in rows
        if g.get("gameType") in KEEP_GAME_TYPES
        and g.get("gameStateId") == FINAL_STATE_ID
        and int(g.get("season", 0)) >= min_season
    ]


# ── Boxscore fetch ───────────────────────────────────────────────────────────

def fetch_boxscore(session: requests.Session, game_id: str) -> dict:
    """Raw boxscore JSON for one game id (10-digit string or int)."""
    return get_json(session, BOXSCORE_URL.format(game_id=game_id))


# ── Pure parsers (no network) ────────────────────────────────────────────────

def toi_to_seconds(toi: str | None) -> int | None:
    """'14:01' -> 841. Minutes may exceed 59 in OT ('65:00' -> 3900)."""
    if not toi or ":" not in toi:
        return None
    minutes, _, seconds = toi.partition(":")
    return int(minutes) * 60 + int(seconds)


def _name(player: dict) -> str | None:
    name = player.get("name")
    if isinstance(name, dict):
        return name.get("default")
    return name


def _shots_denom(value: str | None) -> int | None:
    """Strength-split fields look like 'saves/shots' ('21/23'); return shots."""
    if not value or "/" not in value:
        return None
    return int(value.split("/")[1])


def parse_skater(row: dict, game_id: str, team_id: int) -> dict:
    """One forward/defense API row -> a flat skater_boxscores record."""
    return {
        "game_id": game_id,
        "player_id": int(row["playerId"]),
        "team_id": team_id,
        "name": _name(row),
        "position": row.get("position"),
        "sweater": row.get("sweaterNumber"),
        "goals": row.get("goals"),
        "assists": row.get("assists"),
        "points": row.get("points"),
        "plus_minus": row.get("plusMinus"),
        "pim": row.get("pim"),
        "sog": row.get("sog"),
        "hits": row.get("hits"),
        "blocked_shots": row.get("blockedShots"),
        "takeaways": row.get("takeaways"),
        "giveaways": row.get("giveaways"),
        "power_play_goals": row.get("powerPlayGoals"),
        "faceoff_pct": row.get("faceoffWinningPctg"),
        "toi_seconds": toi_to_seconds(row.get("toi")),
        "shifts": row.get("shifts"),
    }


def parse_goalie(row: dict, game_id: str, team_id: int) -> dict:
    """One goalie API row -> a flat goalie_boxscores record."""
    return {
        "game_id": game_id,
        "player_id": int(row["playerId"]),
        "team_id": team_id,
        "name": _name(row),
        "sweater": row.get("sweaterNumber"),
        "starter": 1 if row.get("starter") else 0,
        "decision": row.get("decision"),          # W / L / T / O / None
        "saves": row.get("saves"),
        "shots_against": row.get("shotsAgainst"),
        "goals_against": row.get("goalsAgainst"),
        "save_pct": row.get("savePctg"),
        "pim": row.get("pim"),
        "toi_seconds": toi_to_seconds(row.get("toi")),
        "es_shots_against": _shots_denom(row.get("evenStrengthShotsAgainst")),
        "es_goals_against": row.get("evenStrengthGoalsAgainst"),
        "pp_shots_against": _shots_denom(row.get("powerPlayShotsAgainst")),
        "pp_goals_against": row.get("powerPlayGoalsAgainst"),
        "sh_shots_against": _shots_denom(row.get("shorthandedShotsAgainst")),
        "sh_goals_against": row.get("shorthandedGoalsAgainst"),
    }


def parse_boxscore(raw: dict) -> dict:
    """Normalize a raw boxscore into flat records ready for SQLite insertion.

    Returns ``{teams, skaters, goalies}``. ``skaters`` merges forwards +
    defense (distinguished by the ``position`` column); ``teams`` carries the
    abbrev + per-team shots/score from the top-level team objects.
    """
    game_id = str(raw["id"])
    pbgs = raw.get("playerByGameStats", {})

    teams, skaters, goalies = [], [], []
    for side in ("homeTeam", "awayTeam"):
        team_obj = raw.get(side, {})
        team_id = team_obj.get("id")
        teams.append({
            "team_id": team_id,
            "abbrev": team_obj.get("abbrev"),
            "game_id": game_id,
            "is_home": 1 if side == "homeTeam" else 0,
            "score": team_obj.get("score"),
            "sog": team_obj.get("sog"),
        })

        side_stats = pbgs.get(side, {})
        for row in side_stats.get("forwards", []) + side_stats.get("defense", []):
            skaters.append(parse_skater(row, game_id, team_id))
        for row in side_stats.get("goalies", []):
            goalies.append(parse_goalie(row, game_id, team_id))

    return {"teams": teams, "skaters": skaters, "goalies": goalies}


# ── Play-by-play (Step 2) ────────────────────────────────────────────────────

def fetch_pbp(session: requests.Session, game_id: str) -> dict:
    """Raw play-by-play JSON for one game id."""
    return get_json(session, PBP_URL.format(game_id=game_id))


def parse_play(play: dict, game_id: str) -> dict:
    """One event from the plays array -> a flat wide-table record.

    The feed is polymorphic: each event type fills a different subset of the
    player-role columns (a faceoff sets winner/loser, a hit sets hitter/hittee,
    a goal sets scorer/assists), so every role column is nullable. Coordinates
    and situation_code are NULL for pre-2009-10 games. Video/replay URLs are
    intentionally dropped.
    """
    d = play.get("details") or {}
    pd_ = play.get("periodDescriptor") or {}
    return {
        "game_id": game_id,
        "sort_order": play.get("sortOrder"),
        "event_id": play.get("eventId"),
        "period": pd_.get("number"),
        "period_type": pd_.get("periodType"),
        "time_in_period": play.get("timeInPeriod"),
        "event_type": play.get("typeDescKey"),
        "event_team_id": d.get("eventOwnerTeamId"),
        "x_coord": d.get("xCoord"),
        "y_coord": d.get("yCoord"),
        "zone_code": d.get("zoneCode"),
        "shot_type": d.get("shotType"),
        "shooter_id": d.get("shootingPlayerId"),
        "goalie_id": d.get("goalieInNetId"),
        "scorer_id": d.get("scoringPlayerId"),
        "assist1_id": d.get("assist1PlayerId"),
        "assist2_id": d.get("assist2PlayerId"),
        "faceoff_winner_id": d.get("winningPlayerId"),
        "faceoff_loser_id": d.get("losingPlayerId"),
        "hitter_id": d.get("hittingPlayerId"),
        "hittee_id": d.get("hitteePlayerId"),
        "blocker_id": d.get("blockingPlayerId"),
        "penalty_on_id": d.get("committedByPlayerId"),
        "penalty_drawn_id": d.get("drawnByPlayerId"),
        "penalty_type": d.get("descKey"),
        "penalty_minutes": d.get("duration"),
        "player_id": d.get("playerId"),          # give/takeaway actor
        "situation_code": play.get("situationCode"),
    }


def parse_pbp(raw: dict) -> list[dict]:
    """All events for one game as flat records ready for SQLite insertion."""
    game_id = str(raw["id"])
    return [parse_play(p, game_id) for p in raw.get("plays", [])]
