"""Pace, minutes and schedule series for the NBA injury investigation.

The canonical NBA database lives on a separate host (SPORTS_DB_HOST, SPORTS_DB_PATH) and is read-only. Each query runs
remotely (ssh, python3 on stdin, ``?mode=ro&immutable=1``, WAL check before and
after) and comes back as JSON. Everything after that is a pure function over
plain lists of dicts, so it is tested locally on small fixtures.

Run from the repo root::

    python injuries/pace.py                       # all five series
    python injuries/pace.py --cache-dir /tmp/c    # reuse remote JSON between runs

Nothing here runs on import.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import os
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("injuries.pace")

# --- constants ---------------------------------------------------------------

REGULAR = "Regular Season"
PLAYOFFS = "Playoffs"
FTA_POSSESSION_WEIGHT = 0.44      # Possessions = FGA - OREB + TOV + 0.44 * FTA
BBR_FTA_WEIGHT = 0.4              # Basketball-Reference's possession estimate, kept as a cross-check
BBR_ORB_WEIGHT = 1.07
REGULATION_MINUTES = 48.0         # pace is possessions per 48 minutes
PLAYERS_ON_COURT = 5              # team `min` is player-minutes: 240 = 5 x 48
MIN_TOV_COVERAGE = 0.95           # report pace only where inputs cover this share
TOP_N_ROTATION = 8
HEAVY_MINUTES = (2500, 3000)
LEADERS_FROM_SEASON = "1996-97"
LEADERS_PER_SEASON = 3
MIN_MINUTES_COVERAGE = 0.95       # share of player-game rows with min > 0
ROUND_DIGITS = 3

# The database host and path are this machine's business, not the repo's: both
# come from the environment, and run_remote() stops loudly if they are missing.
DB_PATH = os.environ.get("SPORTS_DB_PATH") or ""
SSH_HOST = os.environ.get("SPORTS_DB_HOST") or ""
ENV_HELP = "set SPORTS_DB_HOST (ssh host of the sports database) and SPORTS_DB_PATH (path of nba.db on it)"
SSH_TIMEOUT_S = 600
SSH_RETRIES = 3
SSH_BACKOFF_S = 5.0
SSH_CONNECT_FAILURE = 255         # ssh's own exit code for a dropped connection
EXIT_WAL_BUSY = 75                # remote script: a writer is mid-run
BLACKOUT_START = dt.time(6, 10)   # sports-crons writes the DB 06:10-06:30 local
BLACKOUT_END = dt.time(6, 30)

DATA_DIR = Path(__file__).resolve().parent / "data"

# Runs on the database host. The heredoc is not involved: the text goes to ssh stdin.
REMOTE_TEMPLATE = '''
import json, os, sqlite3, sys
DB = {db!r}
WAL = DB + "-wal"
def check(when):
    if os.path.exists(WAL) and os.path.getsize(WAL) > 0:
        sys.stderr.write(WAL + " is non-empty " + when + ": sports-crons is mid-write. Retry after 06:30.")
        sys.exit({busy})
check("before the query")
con = sqlite3.connect("file:" + DB + "?mode=ro&immutable=1", uri=True)
con.execute("PRAGMA query_only = ON")
cur = con.execute({sql!r})
rows = cur.fetchall()
check("after the query")
sys.stdout.write(json.dumps({{"cols": [d[0] for d in cur.description], "rows": rows}}))
'''

SQL_TEAM_GAMES = """
SELECT season, season_type, game_id, team_id, game_date, min, fgm, fga, fg3a, fta, oreb, dreb, tov, pts
FROM team_game
WHERE season_type IN ('Regular Season', 'Playoffs')
ORDER BY season, game_date, game_id, team_id
"""

SQL_PLAYER_SEASONS = """
SELECT season, season_type, player_id, team_id,
       SUM(min) AS minutes, SUM(CASE WHEN min > 0 THEN 1 ELSE 0 END) AS games_played,
       COUNT(*) AS rows
FROM player_game
WHERE season_type IN ('Regular Season', 'Playoffs')
GROUP BY season, season_type, player_id, team_id
"""

SQL_PLAYOFF_GAMES = """
SELECT season, game_id, game_date, home_team_id, away_team_id
FROM games WHERE season_type = 'Playoffs'
"""

SQL_PLAYERS = "SELECT player_id, player_name FROM players"
SQL_TEAMS = "SELECT team_id, abbreviation FROM teams"

SQL_ZERO_MINUTES = """
SELECT season, season_type,
  COUNT(*) AS rows,
  SUM(min = 0) AS zero_rows,
  SUM(min = 0 AND (COALESCE(fga,0) + COALESCE(fta,0) + COALESCE(pts,0) + COALESCE(reb,0)
        + COALESCE(ast,0) + COALESCE(stl,0) + COALESCE(blk,0) + COALESCE(tov,0)
        + COALESCE(pf,0)) > 0) AS zero_with_stats,
  SUM(min = 0 AND COALESCE(plus_minus, 0) <> 0) AS zero_with_plus_minus,
  SUM(min = 0 AND plus_minus IS NULL) AS zero_plus_minus_null,
  SUM(min = 0 AND (COALESCE(fga,0) + COALESCE(fta,0) + COALESCE(pts,0) + COALESCE(reb,0)
        + COALESCE(ast,0) + COALESCE(stl,0) + COALESCE(blk,0) + COALESCE(tov,0)
        + COALESCE(pf,0)) = 0 AND COALESCE(plus_minus, 0) = 0) AS zero_all_blank
FROM player_game
GROUP BY season, season_type
"""

# --- remote access -----------------------------------------------------------


def in_blackout(now: dt.datetime) -> bool:
    """True inside the 06:10-06:30 window when sports-crons writes the DB."""
    return BLACKOUT_START <= now.time() < BLACKOUT_END


def build_remote_script(sql: str, db: str | None = None) -> str:
    db = db or DB_PATH
    return REMOTE_TEMPLATE.format(db=db, busy=EXIT_WAL_BUSY, sql=sql.strip())


def rows_to_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cols = payload["cols"]
    return [dict(zip(cols, row)) for row in payload["rows"]]


def run_remote(sql: str, host: str | None = None) -> list[dict[str, Any]]:
    """Run one read-only query on the database host and return rows as dicts.

    Retries only when ssh itself drops (exit 255) or times out. A busy WAL
    (exit 75) or a SQL error is raised at once: retrying does not fix either.
    """
    if in_blackout(dt.datetime.now()):
        raise RuntimeError("06:10-06:30 local: sports-crons is writing the NBA DB. Retry after 06:30.")
    host = host or SSH_HOST
    if not host or not DB_PATH:
        raise RuntimeError(ENV_HELP)
    script = build_remote_script(sql)
    last: Exception | None = None
    for attempt in range(1, SSH_RETRIES + 1):
        try:
            proc = subprocess.run(
                ["ssh", "-C", host, "python3", "-"],
                input=script, capture_output=True, text=True, encoding="utf-8",
                timeout=SSH_TIMEOUT_S, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            last = exc
            log.warning("ssh timed out after %ss (attempt %d/%d)", SSH_TIMEOUT_S, attempt, SSH_RETRIES)
        else:
            if proc.returncode == 0:
                return rows_to_dicts(json.loads(proc.stdout))
            tail = proc.stderr.strip()[-500:]
            if proc.returncode != SSH_CONNECT_FAILURE:
                raise RuntimeError(f"remote query failed (exit {proc.returncode}): {tail}")
            last = RuntimeError(f"ssh connection failed: {tail}")
            log.warning("%s (attempt %d/%d)", last, attempt, SSH_RETRIES)
        if attempt < SSH_RETRIES:
            time.sleep(SSH_BACKOFF_S * attempt)
    raise RuntimeError(f"remote query failed after {SSH_RETRIES} attempts") from last


def fetch(name: str, sql: str, cache_dir: Path | None) -> list[dict[str, Any]]:
    cache = cache_dir / f"{name}.json" if cache_dir else None
    if cache is not None and cache.exists():
        log.info("%s: cached %s", name, cache)
        return json.loads(cache.read_text(encoding="utf-8"))
    t0 = time.time()
    rows = run_remote(sql)
    log.info("%s: %d rows in %.0fs", name, len(rows), time.time() - t0)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows), encoding="utf-8")
    return rows


# --- pure functions: pace ----------------------------------------------------


def possessions(fga: float, oreb: float, tov: float, fta: float) -> float:
    return fga - oreb + tov + FTA_POSSESSION_WEIGHT * fta


def bbr_possessions(fga: float, fta: float, oreb: float, fgm: float, tov: float,
                    opp_dreb: float) -> float:
    """Basketball-Reference's team possession estimate (one side of their pace formula)."""
    orb_rate = oreb / (oreb + opp_dreb)
    return fga + BBR_FTA_WEIGHT * fta - BBR_ORB_WEIGHT * orb_rate * (fga - fgm) + tov


def pace_per_48(poss: float, team_minutes: float) -> float:
    """Possessions per 48 minutes. Team minutes are player-minutes (240 regulation)."""
    if team_minutes <= 0:
        raise ValueError(f"team minutes must be positive, got {team_minutes}")
    return REGULATION_MINUTES * poss / (team_minutes / PLAYERS_ON_COURT)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pace_inputs_ok(r: dict[str, Any]) -> bool:
    """TOV counts as missing when NULL or 0: no team plays a game with none."""
    return (all(r.get(k) is not None for k in ("fga", "oreb", "tov", "fta", "min"))
            and r["tov"] > 0 and r["min"] > 0)


def _bbr_paces(rows: list[dict[str, Any]]) -> list[float]:
    """Per team-game pace with Basketball-Reference's formula, where both sides are complete."""
    by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_game[r["game_id"]].append(r)
    keys = ("fgm", "fga", "fta", "oreb", "dreb", "tov")
    out = []
    for pair in by_game.values():
        if len(pair) != 2 or not all(_pace_inputs_ok(r) and all(r.get(k) is not None for k in keys)
                                     for r in pair):
            continue
        for a, b in (pair, pair[::-1]):
            poss_a = bbr_possessions(a["fga"], a["fta"], a["oreb"], a["fgm"], a["tov"], b["dreb"])
            poss_b = bbr_possessions(b["fga"], b["fta"], b["oreb"], b["fgm"], b["tov"], a["dreb"])
            out.append(REGULATION_MINUTES * (poss_a + poss_b) / (2 * (a["min"] / PLAYERS_ON_COURT)))
    return out


def summarize_pace(team_games: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per regular season. Pace is blank where inputs cover < 95% of team-games."""
    by_season: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in team_games:
        if r["season_type"] == REGULAR:
            by_season[r["season"]].append(r)
    out = []
    for season in sorted(by_season):
        rows = by_season[season]
        ok = [r for r in rows if _pace_inputs_ok(r)]
        coverage = len(ok) / len(rows)
        pace = None
        pace_bbr = None
        note = ""
        if coverage >= MIN_TOV_COVERAGE:
            pace = _mean([pace_per_48(possessions(r["fga"], r["oreb"], r["tov"], r["fta"]), r["min"])
                          for r in ok])
            pace_bbr = _mean(_bbr_paces(rows))
        else:
            note = (f"pace needs FGA, OREB, TOV, FTA and team minutes; complete for only "
                    f"{coverage:.0%} of team-games (TOV is NULL or 0 before the league recorded it)")
        pairs = [(r["fg3a"], r["fga"]) for r in rows if r.get("fg3a") is not None and r.get("fga")]
        share = (sum(a for a, _ in pairs) / sum(b for _, b in pairs)) if pairs else None
        out.append({
            "season": season,
            "pace": pace,
            "pace_bbr_formula": pace_bbr,
            "pts_per_game": _mean([r["pts"] for r in rows if r.get("pts") is not None]),
            "fga_per_game": _mean([r["fga"] for r in rows if r.get("fga") is not None]),
            "fg3a_per_game": _mean([r["fg3a"] for r in rows if r.get("fg3a") is not None]),
            "fta_per_game": _mean([r["fta"] for r in rows if r.get("fta") is not None]),
            "fg3a_share_of_fga": share,
            "team_games": len(rows),
            "pace_team_games": len(ok),
            "pace_note": note,
        })
    return out


# --- pure functions: schedule ------------------------------------------------


def count_back_to_backs(dates: Iterable[dt.date]) -> int:
    """Consecutive-calendar-date pairs in one team's schedule."""
    d = sorted(dates)
    return sum(1 for a, b in zip(d, d[1:]) if (b - a).days == 1)


def rest_gaps(dates: Iterable[dt.date]) -> list[int]:
    """Days off between consecutive games: a back-to-back is 0.

    Two games on one date (a few 1950s doubleheaders) also count as 0 days off.
    """
    d = sorted(dates)
    return [max((b - a).days - 1, 0) for a, b in zip(d, d[1:])]


def summarize_schedule(team_games: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    reg: dict[str, dict[int, list[dt.date]]] = defaultdict(lambda: defaultdict(list))
    playoff_games: dict[str, set[str]] = defaultdict(set)
    playoff_by_team: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in team_games:
        if r["season_type"] == REGULAR:
            reg[r["season"]][r["team_id"]].append(dt.date.fromisoformat(r["game_date"][:10]))
        elif r["season_type"] == PLAYOFFS:
            playoff_games[r["season"]].add(r["game_id"])
            playoff_by_team[r["season"]][r["team_id"]].add(r["game_id"])
    out = []
    for season in sorted(reg):
        teams = reg[season]
        all_dates = [d for ds in teams.values() for d in ds]
        gaps = [g for ds in teams.values() for g in rest_gaps(ds)]
        b2b = [count_back_to_backs(ds) for ds in teams.values()]
        pt = playoff_by_team.get(season, {})
        out.append({
            "season": season,
            "teams": len(teams),
            "games_per_team": max(len(ds) for ds in teams.values()),
            "season_span_days": (max(all_dates) - min(all_dates)).days,
            "mean_rest_days": _mean(gaps),
            "back_to_backs_per_team": _mean(b2b),
            "playoff_games_total": len(playoff_games.get(season, ())),
            "playoff_games_max_team": max((len(g) for g in pt.values()), default=0),
        })
    return out


# --- pure functions: minutes -------------------------------------------------


def partial_seasons(team_games: Iterable[dict[str, Any]]) -> set[str]:
    """The latest season, if no playoff game has been played in it yet."""
    seasons: set[str] = set()
    with_playoffs: set[str] = set()
    for r in team_games:
        seasons.add(r["season"])
        if r["season_type"] == PLAYOFFS:
            with_playoffs.add(r["season"])
    if not seasons:
        return set()
    latest = max(seasons)
    return set() if latest in with_playoffs else {latest}


def _reg(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["season_type"] == REGULAR]


def summarize_minutes(player_seasons: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Regular-season minutes concentration, from (season, player, team) aggregates."""
    rows = _reg(player_seasons)
    seasons = sorted({r["season"] for r in rows})
    out = []
    for season in seasons:
        sr = [r for r in rows if r["season"] == season]
        by_team: dict[int, list[float]] = defaultdict(list)
        by_player: dict[int, float] = defaultdict(float)
        for r in sr:
            m = r["minutes"] or 0.0
            by_team[r["team_id"]].append(m)
            by_player[r["player_id"]] += m
        played = sum(r["games_played"] for r in sr)
        total_min = sum(r["minutes"] or 0.0 for r in sr)
        total_rows = sum(r["rows"] for r in sr)
        coverage = played / total_rows
        top8 = [sum(sorted(ms, reverse=True)[:TOP_N_ROTATION]) for ms in by_team.values()]
        top1 = [max(ms) for ms in by_team.values()]
        reliable = coverage >= MIN_MINUTES_COVERAGE
        note = "" if reliable else (
            f"minutes recorded for only {coverage:.0%} of player-game rows; "
            "minute-based columns left blank")
        out.append({
            "season": season,
            "top8_mean_minutes": _mean(top8) if reliable else None,
            "top1_mean_minutes": _mean(top1) if reliable else None,
            "players_2500_plus": sum(1 for m in by_player.values() if m >= HEAVY_MINUTES[0]) if reliable else None,
            "players_3000_plus": sum(1 for m in by_player.values() if m >= HEAVY_MINUTES[1]) if reliable else None,
            "mean_minutes_per_player_game": (total_min / played) if reliable and played else None,
            # any row counts: a zero-minute row is a real appearance and the DB has no DNP rows
            "players_appeared": len({r["player_id"] for r in sr}),
            "minutes_coverage": coverage,
            "minutes_note": note,
        })
    return out


# --- pure functions: leaders -------------------------------------------------


def finals_teams(playoff_games: Iterable[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Per season, the two teams in the last playoff game (date, then game_id)."""
    last: dict[str, dict[str, Any]] = {}
    for g in playoff_games:
        key = (g["game_date"], g["game_id"])
        cur = last.get(g["season"])
        if cur is None or key > (cur["game_date"], cur["game_id"]):
            last[g["season"]] = g
    return {s: (g["home_team_id"], g["away_team_id"]) for s, g in last.items()}


def build_leaders(player_seasons: Iterable[dict[str, Any]],
                  playoff_games: Iterable[dict[str, Any]],
                  names: dict[int, str], abbrs: dict[int, str],
                  from_season: str = LEADERS_FROM_SEASON,
                  exclude: set[str] = frozenset()) -> list[dict[str, Any]]:
    ps = [r for r in player_seasons if r["season"] >= from_season and r["season"] not in exclude]
    finals = finals_teams(playoff_games)
    seasons = sorted({r["season"] for r in ps if r["season_type"] == REGULAR})

    def label(pid: int) -> str:
        return names.get(pid, f"player {pid}")

    out = []
    for season in seasons:
        reg_p: dict[int, float] = defaultdict(float)
        reg_g: dict[int, int] = defaultdict(int)
        reg_pt: dict[int, dict[int, float]] = defaultdict(dict)
        po_p: dict[int, float] = defaultdict(float)
        po_g: dict[int, int] = defaultdict(int)
        po_pt: dict[tuple[int, int], tuple[float, int]] = {}
        reg_pt_g: dict[tuple[int, int], int] = {}
        for r in ps:
            if r["season"] != season:
                continue
            m = r["minutes"] or 0.0
            if r["season_type"] == REGULAR:
                reg_p[r["player_id"]] += m
                reg_g[r["player_id"]] += r["games_played"]
                reg_pt[r["team_id"]][r["player_id"]] = m
                reg_pt_g[(r["team_id"], r["player_id"])] = r["games_played"]
            else:
                po_p[r["player_id"]] += m
                po_g[r["player_id"]] += r["games_played"]
                po_pt[(r["team_id"], r["player_id"])] = (m, r["games_played"])
        top = sorted(reg_p, key=lambda p: (-reg_p[p], p))[:LEADERS_PER_SEASON]
        for rank, pid in enumerate(top, 1):
            teams_for = sorted((t for t in reg_pt if pid in reg_pt[t]), key=lambda t: -reg_pt[t][pid])
            out.append({
                "season": season, "group": "league_top3", "rank": rank,
                "player_id": pid, "player_name": label(pid),
                "team": "/".join(abbrs.get(t, str(t)) for t in teams_for),
                "regular_minutes": reg_p[pid], "regular_games": reg_g[pid],
                "playoff_minutes": po_p.get(pid, 0.0), "playoff_games": po_g.get(pid, 0),
            })
        for team in finals.get(season, ()):
            roster = reg_pt.get(team, {})
            if not roster:
                raise ValueError(f"{season}: Finals team {team} has no regular-season player rows")
            pid = sorted(roster, key=lambda p: (-roster[p], p))[0]
            pm, pg = po_pt.get((team, pid), (0.0, 0))
            out.append({
                "season": season, "group": "finals_team_leader", "rank": 1,
                "player_id": pid, "player_name": label(pid), "team": abbrs.get(team, str(team)),
                "regular_minutes": roster[pid], "regular_games": reg_pt_g[(team, pid)],
                "playoff_minutes": pm, "playoff_games": pg,
            })
    return out


# --- pure functions: zero-minute rows ---------------------------------------


def summarize_zero(rows: Iterable[dict[str, Any]], partial: set[str]) -> list[dict[str, Any]]:
    out = []
    for r in sorted(rows, key=lambda r: (r["season"], r["season_type"])):
        out.append({
            "season": r["season"], "season_type": r["season_type"], "rows": r["rows"],
            "zero_minute_rows": r["zero_rows"],
            "zero_share": r["zero_rows"] / r["rows"] if r["rows"] else None,
            "zero_with_box_stats": r["zero_with_stats"],
            "zero_with_plus_minus": r["zero_with_plus_minus"],
            "zero_plus_minus_null": r["zero_plus_minus_null"],
            "zero_all_blank": r["zero_all_blank"],
            "partial": int(r["season"] in partial),
        })
    return out


def render_zero_finding(zero: list[dict[str, Any]], boundary: str) -> str:
    """Markdown paragraph with every number computed from the per-season rows."""
    def tot(rows, key):
        return sum(r[key] for r in rows)
    reg = [r for r in zero if r["season_type"] == REGULAR]
    allz = tot(zero, "zero_minute_rows")
    early = [r for r in reg if r["season"] < boundary]
    late = [r for r in reg if r["season"] >= boundary]
    late_games_est = tot(late, "rows")
    return (
        "# Zero-minute rows in `player_game`\n\n"
        f"`player_game` holds {allz:,} rows with `min = 0` across all season types and none NULL. "
        "They are not did-not-play rows. They are two different things split by the era in which the "
        f"league's source started recording `plus_minus` ({boundary}). "
        f"Before {boundary} ({tot(early, 'zero_minute_rows'):,} regular-season rows, "
        f"{tot(early, 'zero_minute_rows') / max(tot(early, 'rows'), 1):.1%} of the rows in those seasons) "
        f"`min = 0` means minutes were not recorded: {tot(early, 'zero_with_box_stats'):,} of those rows "
        "carry real box-score stats (points, rebounds, assists, fouls) and all of them have `plus_minus` NULL; "
        "the share is highest in the 1950s and 1960s and falls to a few rows a season by the late 1980s. "
        f"From {boundary} on ({tot(late, 'zero_minute_rows'):,} regular-season rows, "
        f"{tot(late, 'zero_minute_rows') / max(late_games_est, 1):.2%} of the rows) they are genuine "
        f"sub-minute appearances: {tot(late, 'zero_with_plus_minus'):,} have a non-zero `plus_minus`, so the "
        f"player was on the court while points were scored, and {tot(late, 'zero_with_box_stats'):,} carry "
        f"box-score stats; the other {tot(late, 'zero_all_blank'):,} are all zeros, which fits a few "
        "seconds on the floor rounded down to 0 minutes. "
        f"The database therefore carries no did-not-play rows: the modern seasons average "
        f"{tot(late, 'zero_minute_rows') / max(len(late), 1):.0f} zero-minute rows a season out of about "
        f"{late_games_est / max(len(late), 1):,.0f} player-game rows, while DNP rows would add several per "
        "team-game. A player's games played in this database means games in which he appeared, so any "
        "missed-games count has to be derived by comparing a player's rows with his team's schedule.\n"
    )


# --- output ------------------------------------------------------------------

PACE_COLS = ["season", "partial", "pace", "pace_bbr_formula", "pts_per_game", "fga_per_game", "fg3a_per_game", "fta_per_game",
             "fg3a_share_of_fga", "team_games", "pace_team_games", "pace_note"]
MINUTES_COLS = ["season", "partial", "top8_mean_minutes", "top1_mean_minutes", "players_2500_plus",
                "players_3000_plus", "mean_minutes_per_player_game", "players_appeared",
                "minutes_coverage", "minutes_note"]
SCHEDULE_COLS = ["season", "partial", "teams", "games_per_team", "season_span_days", "mean_rest_days",
                 "back_to_backs_per_team", "playoff_games_total", "playoff_games_max_team"]
LEADER_COLS = ["season", "group", "rank", "player_id", "player_name", "team", "regular_minutes",
               "regular_games", "playoff_minutes", "playoff_games"]
ZERO_COLS = ["season", "season_type", "partial", "rows", "zero_minute_rows", "zero_share",
             "zero_with_box_stats", "zero_with_plus_minus", "zero_plus_minus_null", "zero_all_blank"]


def mark_partial(rows: list[dict[str, Any]], partial: set[str]) -> list[dict[str, Any]]:
    return [{**r, "partial": int(r["season"] in partial)} for r in rows]


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, float):
        return round(v, ROUND_DIGITS)
    return v


def write_csv(path: Path, cols: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([_cell(r[c]) for c in cols])
            n += 1
    log.info("wrote %s (%d rows)", path, n)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="store/reuse each remote result as JSON (for iterating offline)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    team_games = fetch("team_games", SQL_TEAM_GAMES, args.cache_dir)
    partial = partial_seasons(team_games)
    log.info("partial seasons: %s", sorted(partial) or "none")
    out = args.out_dir
    write_csv(out / "pace_by_season.csv", PACE_COLS, mark_partial(summarize_pace(team_games), partial))
    write_csv(out / "schedule_by_season.csv", SCHEDULE_COLS, mark_partial(summarize_schedule(team_games), partial))

    player_seasons = fetch("player_seasons", SQL_PLAYER_SEASONS, args.cache_dir)
    write_csv(out / "minutes_by_season.csv", MINUTES_COLS, mark_partial(summarize_minutes(player_seasons), partial))

    playoff_games = fetch("playoff_games", SQL_PLAYOFF_GAMES, args.cache_dir)
    names = {r["player_id"]: r["player_name"] for r in fetch("players", SQL_PLAYERS, args.cache_dir)}
    abbrs = {r["team_id"]: r["abbreviation"] for r in fetch("teams", SQL_TEAMS, args.cache_dir)}
    write_csv(out / "player_minutes_leaders.csv", LEADER_COLS,
              build_leaders(player_seasons, playoff_games, names, abbrs, exclude=partial))

    zero = summarize_zero(fetch("zero_minutes", SQL_ZERO_MINUTES, args.cache_dir), partial)
    write_csv(out / "zero_minute_rows.csv", ZERO_COLS, zero)
    boundary = first_plus_minus_season(zero)
    (out / "zero_minute_rows.md").write_text(render_zero_finding(zero, boundary), encoding="utf-8")
    log.info("wrote %s", out / "zero_minute_rows.md")
    return 0


def first_plus_minus_season(zero: list[dict[str, Any]]) -> str:
    """First regular season (with zero-minute rows) from which none has a NULL plus_minus."""
    reg = sorted((r for r in zero if r["season_type"] == REGULAR and r["zero_minute_rows"] > 0),
                 key=lambda r: r["season"])
    first = None
    for r in reg:
        if r["zero_plus_minus_null"] > 0:
            first = None
        elif first is None:
            first = r["season"]
    if first is None:
        raise ValueError("no season found where plus_minus is always recorded")
    return first


if __name__ == "__main__":
    raise SystemExit(main())
