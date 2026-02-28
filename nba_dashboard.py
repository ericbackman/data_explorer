#!/usr/bin/env python3
"""
NBA Player Dashboard — standalone module.

Extracted from nba_player_dashboard.ipynb. All functions are importable,
and the module can be run directly from the CLI.

Usage:
    python nba_dashboard.py "LeBron James"
    python nba_dashboard.py "Nikola Jokic" 2025-26
"""

import sys
import time
import requests
import pandas as pd

from nba_api.stats.static import players
from nba_api.stats.endpoints import (
    playergamelog,
    playercareerstats,
    commonplayerinfo,
    commonteamroster,
    playerdashboardbylastngames,
    playerdashboardbygamesplits,
)

SLEEP        = 0.6   # seconds between NBA.com API calls
THRESHOLD    = 3.0   # pt diff (1H vs 2H) needed to label hot/cold pattern
DEFAULT_SEASON = "2025-26"


# ── Helpers ───────────────────────────────────────────────────────────────────

_COUNT_STATS = ["MIN", "PTS", "REB", "AST", "STL", "BLK",
                "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "PLUS_MINUS"]

_RENAME_MAP = {
    "MIN": "MPG", "PTS": "PPG", "REB": "RPG", "AST": "APG",
    "STL": "SPG", "BLK": "BPG", "FGM": "FGM/G", "FGA": "FGA/G",
    "FG3M": "3PM/G", "FG3A": "3PA/G", "FTM": "FTM/G", "FTA": "FTA/G",
    "PLUS_MINUS": "+/-",
}

def _to_per_game(df: pd.DataFrame) -> pd.DataFrame:
    """Divide counting stats by GP and rename columns to per-game labels."""
    out = df.copy()
    gp  = max(out["GP"].iloc[0], 1) if "GP" in out.columns and not out.empty else 1
    for col in _COUNT_STATS:
        if col in out.columns:
            out[col] = (out[col] / gp).round(1)
    for col in ["FG_PCT", "FG3_PCT", "FT_PCT"]:
        if col in out.columns:
            out[col] = out[col].round(3)
    return out.rename(columns=_RENAME_MAP)


# ── 1. Player lookup ──────────────────────────────────────────────────────────

def find_player(name: str) -> dict:
    """
    Find a player by full name (case-insensitive substring match).
    Returns the first active match, then any match.
    Raises ValueError if not found.
    """
    matches = players.find_players_by_full_name(name)
    if not matches:
        raise ValueError(f"No player found matching '{name}'.")
    # Prefer active players
    active = [p for p in matches if p["is_active"]]
    return active[0] if active else matches[0]


# ── 2. Game log ───────────────────────────────────────────────────────────────

def get_game_log(player_id: int, season: str) -> pd.DataFrame:
    """
    Return full-season game log (newest first).
    MIN column is normalised from "MM:SS" to float minutes.
    """
    gl = playergamelog.PlayerGameLog(player_id=player_id, season=season)
    time.sleep(SLEEP)
    df = gl.get_data_frames()[0]
    if df["MIN"].dtype == object:
        df["MIN"] = df["MIN"].apply(
            lambda x: float(x.split(":")[0]) + float(x.split(":")[1]) / 60
            if ":" in str(x) else float(x)
        ).round(1)
    return df


# ── 3. Rolling averages (last N games) ───────────────────────────────────────

# PlayerDashboardByLastNGames returns 6 DataFrames in actual API response order
# (numerical by N), not in the alphabetical order of the source's expected_data:
#   Index 0 → GameNumberPlayerDashboard
#   Index 1 → Last5PlayerDashboard
#   Index 2 → Last10PlayerDashboard
#   Index 3 → Last15PlayerDashboard
#   Index 4 → Last20PlayerDashboard
#   Index 5 → OverallPlayerDashboard
_LAST_N_IDX = {5: 1, 10: 2, 15: 3, 20: 4}


def get_last_n_avgs(player_id: int, season: str, last_n: int) -> pd.DataFrame:
    """
    Return per-game averages for the last N games using
    PlayerDashboardByLastNGames. Reads the correct fixed DataFrame index
    for each span — the last_n_games param does NOT control which DF is returned.
    Counting stats are divided by GP.
    """
    dash = playerdashboardbylastngames.PlayerDashboardByLastNGames(
        player_id=player_id,
        season=season,
    )
    time.sleep(SLEEP)
    idx = _LAST_N_IDX.get(last_n, 4)
    return _to_per_game(dash.get_data_frames()[idx])


# ── 4. Season averages ────────────────────────────────────────────────────────

def get_season_averages(player_id: int, season: str) -> pd.Series:
    """
    Return per-game averages for the given season from PlayerCareerStats.
    Falls back to the most recent season if no data found for `season`.
    """
    career = playercareerstats.PlayerCareerStats(player_id=player_id)
    time.sleep(SLEEP)
    totals = career.get_data_frames()[0]

    row_df = totals[totals["SEASON_ID"] == season]
    if row_df.empty:
        row_df = totals.tail(1)

    row = row_df.iloc[0]
    gp  = max(row["GP"], 1)

    return pd.Series({
        "Season": row["SEASON_ID"],
        "Team"  : row.get("TEAM_ABBREVIATION", ""),
        "GP"    : int(row["GP"]),
        "MPG"   : round(row["MIN"]      / gp, 1),
        "PPG"   : round(row["PTS"]      / gp, 1),
        "RPG"   : round(row["REB"]      / gp, 1),
        "APG"   : round(row["AST"]      / gp, 1),
        "SPG"   : round(row["STL"]      / gp, 1),
        "BPG"   : round(row["BLK"]      / gp, 1),
        "FG%"   : round(row["FG_PCT"]   * 100, 1),
        "3P%"   : round(row["FG3_PCT"]  * 100, 1),
        "FT%"   : round(row["FT_PCT"]   * 100, 1),
    })


# ── 5. Team info & injuries ───────────────────────────────────────────────────

def get_team_info(player_id: int) -> dict:
    """Return the player's current team id, name, and abbreviation."""
    info = commonplayerinfo.CommonPlayerInfo(player_id=player_id)
    time.sleep(SLEEP)
    row = info.get_data_frames()[0].iloc[0]
    return {
        "team_id"  : int(row["TEAM_ID"]),
        "team_name": row["TEAM_NAME"],
        "team_abbr": row["TEAM_ABBREVIATION"],
    }


def get_team_roster(team_id: int, season: str) -> pd.DataFrame:
    """Return the current team roster."""
    roster = commonteamroster.CommonTeamRoster(team_id=team_id, season=season)
    time.sleep(SLEEP)
    df   = roster.get_data_frames()[0]
    keep = [c for c in ["PLAYER", "NUM", "POSITION", "HEIGHT", "WEIGHT", "AGE", "EXP"]
            if c in df.columns]
    return df[keep].reset_index(drop=True)


def get_injuries(team_abbr: str) -> pd.DataFrame:
    """
    Fetch team injury report from the ESPN public API.
    Returns an empty DataFrame if the team has no listed injuries or the
    request fails.
    """
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
        f"/teams/{team_abbr.lower()}/injuries"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rows = []
        for item in data.get("injuries", []):
            athlete = item.get("athlete", {})
            rows.append({
                "Player"  : athlete.get("displayName", "Unknown"),
                "Position": athlete.get("position", {}).get("abbreviation", ""),
                "Status"  : item.get("status", "Unknown"),
                "Comment" : item.get("longComment") or item.get("shortComment", ""),
                "Date"    : (item.get("date") or "")[:10],
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["Player", "Position", "Status", "Comment", "Date"]
        )
    except Exception as e:
        return pd.DataFrame({"Error": [str(e)]})


# ── 6. Quarter-by-quarter averages ───────────────────────────────────────────

def get_quarter_avgs(player_id: int, season: str, last_n: int) -> pd.DataFrame:
    """
    Return per-game averages broken down by quarter (Q1–Q4) for the last N
    games, using PlayerDashboardByGameSplits (ByPeriodPlayerDashboard, index 2).

    With per_mode_detailed="PerGame" the endpoint returns stats already
    divided by GP — no further calculation needed.

    Returns a tidy DataFrame with one row per quarter and columns:
        Quarter, GP, PTS, FGM, FGA, FG_PCT, FG3M, FG3A, FG3_PCT,
        FTM, FTA, FT_PCT, REB, AST, STL, BLK, PLUS_MINUS
    """
    dash = playerdashboardbygamesplits.PlayerDashboardByGameSplits(
        player_id=player_id,
        season=season,
        last_n_games=last_n,
        per_mode_detailed="PerGame",
    )
    time.sleep(SLEEP)
    df = dash.get_data_frames()[2]  # ByPeriodPlayerDashboard

    # GROUP_VALUE is "1" / "2" / "3" / "4" for Q1–Q4; drop OT rows if present
    df = df[df["GROUP_VALUE"].astype(str).isin(["1", "2", "3", "4"])].copy()
    df["Quarter"] = "Q" + df["GROUP_VALUE"].astype(str)

    keep = [c for c in [
        "Quarter", "GP", "PTS", "FGM", "FGA", "FG_PCT",
        "FG3M", "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT",
        "REB", "AST", "STL", "BLK", "PLUS_MINUS",
    ] if c in df.columns]

    return df[keep].reset_index(drop=True)


def detect_pattern(quarter_df: pd.DataFrame) -> dict:
    """
    Analyse a quarter-averages DataFrame (from get_quarter_avgs) and return
    a pattern dict with keys:
        label, detail, avg_q1/2/3/4, avg_1h, avg_2h, best_q, worst_q
    """
    avgs = {}
    for _, row in quarter_df.iterrows():
        avgs[row["Quarter"]] = round(row["PTS"], 1)

    avg_q1 = avgs.get("Q1", 0)
    avg_q2 = avgs.get("Q2", 0)
    avg_q3 = avgs.get("Q3", 0)
    avg_q4 = avgs.get("Q4", 0)
    avg_1h = avg_q1 + avg_q2
    avg_2h = avg_q3 + avg_q4
    diff   = avg_1h - avg_2h

    if diff >= THRESHOLD:
        label  = "HOT START / COLD FINISH"
        detail = f"Scores {diff:.1f} more pts per game in the 1st half — fades late."
    elif diff <= -THRESHOLD:
        label  = "COLD START / HOT FINISH"
        detail = f"Scores {abs(diff):.1f} more pts per game in the 2nd half — heats up late."
    else:
        label  = "CONSISTENT"
        detail = "Scoring is fairly balanced across all four quarters."

    return {
        "label"  : label,
        "detail" : detail,
        "avg_1h" : avg_1h,
        "avg_2h" : avg_2h,
        "avg_q1" : avg_q1,
        "avg_q2" : avg_q2,
        "avg_q3" : avg_q3,
        "avg_q4" : avg_q4,
        "best_q" : max(avgs, key=avgs.get),
        "worst_q": min(avgs, key=avgs.get),
    }


# ── 7. Full dashboard ─────────────────────────────────────────────────────────

def get_player_dashboard(player_name: str, season: str = DEFAULT_SEASON) -> dict:
    """
    Fetch all dashboard data for a player. Returns a dict with keys:
        player_info, team_info, season_avgs, last5, last10,
        game_log, qbq_last5, qbq_last10, pattern, injuries
    """
    print(f"\nLooking up '{player_name}' ...")
    player_info = find_player(player_name)
    player_id   = player_info["id"]
    print(f"  Found: {player_info['full_name']} (id={player_id}, active={player_info['is_active']})")

    print("Fetching season averages ...")
    season_avgs = get_season_averages(player_id, season)

    print("Fetching last-N averages (single call) ...")
    _dash_dfs = playerdashboardbylastngames.PlayerDashboardByLastNGames(
        player_id=player_id, season=season,
    ).get_data_frames()
    time.sleep(SLEEP)
    last5  = _to_per_game(_dash_dfs[_LAST_N_IDX[5]])
    last10 = _to_per_game(_dash_dfs[_LAST_N_IDX[10]])

    print("Fetching game log ...")
    game_log = get_game_log(player_id, season)

    print("Fetching team info ...")
    team_info = get_team_info(player_id)

    print("Fetching injury report ...")
    injuries = get_injuries(team_info["team_abbr"])

    print("Fetching quarter averages (last 5 games) ...")
    qbq_last5 = get_quarter_avgs(player_id, season, 5)

    print("Fetching quarter averages (last 10 games) ...")
    qbq_last10 = get_quarter_avgs(player_id, season, 10)

    pattern = detect_pattern(qbq_last5)

    return {
        "player_info": player_info,
        "team_info"  : team_info,
        "season_avgs": season_avgs,
        "last5"      : last5,
        "last10"     : last10,
        "game_log"   : game_log,
        "qbq_last5"  : qbq_last5,
        "qbq_last10" : qbq_last10,
        "pattern"    : pattern,
        "injuries"   : injuries,
    }


def print_dashboard(player_name: str, season: str = DEFAULT_SEASON) -> None:
    """Fetch and print a full text summary to stdout."""
    data = get_player_dashboard(player_name, season)

    p      = data["player_info"]
    t      = data["team_info"]
    sa     = data["season_avgs"]
    l5     = data["last5"].iloc[0]
    l10    = data["last10"].iloc[0]
    pat    = data["pattern"]
    gl     = data["game_log"]
    inj    = data["injuries"]

    SEP  = "=" * 62
    SEP2 = "─" * 62

    def _row(label, vals):
        return f"  {label:<10}" + "".join(f"{v:>8}" for v in vals)

    print(f"\n{SEP}")
    print(f"  NBA PLAYER DASHBOARD")
    print(f"  {p['full_name'].upper()}")
    print(f"  {t['team_name']}  |  Season: {season}")
    print(SEP)

    # ── Per-game averages comparison ─────────────────────────────────────────
    print("\n[ PER-GAME AVERAGES ]")
    print(SEP2)
    headers = ["GP", "MPG", "PPG", "RPG", "APG", "SPG", "BPG", "FG%", "3P%", "FT%"]
    print(_row("Span", headers))
    print(f"  {SEP2[2:]}")

    def _avgs_row(label, src, pct_scale=1.0):
        vals = [
            src.get("GP"),
            src.get("MPG"),
            src.get("PPG"),
            src.get("RPG"),
            src.get("APG"),
            src.get("SPG"),
            src.get("BPG"),
            f"{src.get('FG%' if pct_scale == 1 else 'FG_PCT', 0) * pct_scale:.1f}",
            f"{src.get('3P%' if pct_scale == 1 else 'FG3_PCT', 0) * pct_scale:.1f}",
            f"{src.get('FT%' if pct_scale == 1 else 'FT_PCT', 0) * pct_scale:.1f}",
        ]
        return _row(label, vals)

    def _rolling_vals(s):
        return {
            "GP" : s.get("GP"),  "MPG": s.get("MPG"),
            "PPG": s.get("PPG"), "RPG": s.get("RPG"),
            "APG": s.get("APG"), "SPG": s.get("SPG"),
            "BPG": s.get("BPG"),
            "FG%": round(s.get("FG_PCT",  0) * 100, 1),
            "3P%": round(s.get("FG3_PCT", 0) * 100, 1),
            "FT%": round(s.get("FT_PCT",  0) * 100, 1),
        }

    for label, src in [("Last 5", _rolling_vals(l5)),
                        ("Last 10", _rolling_vals(l10)),
                        (f"Season", {**sa})]:
        vals = [src.get(h, "—") for h in headers]
        print(_row(label, vals))

    # ── Quarter breakdown ─────────────────────────────────────────────────────
    pat = data["pattern"]
    print(f"\n[ QUARTER SCORING AVERAGES  (PTS/G) ]")
    print(SEP2)

    def _qbq_row(label, qdf):
        pts = {r["Quarter"]: round(r["PTS"], 1) for _, r in qdf.iterrows()}
        q1, q2, q3, q4 = pts.get("Q1",0), pts.get("Q2",0), pts.get("Q3",0), pts.get("Q4",0)
        vals = [q1, q2, round(q1+q2,1), q3, q4, round(q3+q4,1), round(q1+q2+q3+q4,1)]
        return _row(label, vals)

    print(_row("Span", ["Q1", "Q2", "1H", "Q3", "Q4", "2H", "Total"]))
    print(f"  {SEP2[2:]}")
    print(_qbq_row("Last 5",  data["qbq_last5"]))
    print(_qbq_row("Last 10", data["qbq_last10"]))
    print(f"\n  Pattern (L5)  →  {pat['label']}")
    print(f"  {pat['detail']}")

    # ── Recent game log ───────────────────────────────────────────────────────
    print(f"\n[ RECENT GAME LOG  (Last 5) ]")
    print(SEP2)
    log_cols = ["GAME_DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST",
                "STL", "BLK", "FG_PCT", "FG3_PCT", "FT_PCT", "PLUS_MINUS"]
    log5 = gl[[c for c in log_cols if c in gl.columns]].head(5)
    print(log5.to_string(index=False))

    # ── Injury report ─────────────────────────────────────────────────────────
    print(f"\n[ {t['team_name'].upper()} INJURY REPORT ]")
    print(SEP2)
    if inj.empty or "Error" in inj.columns:
        msg = inj["Error"].iloc[0] if "Error" in inj.columns else "None reported."
        print(f"  {msg}")
    else:
        print(inj[["Player", "Position", "Status", "Comment"]].to_string(index=False))

    print(f"\n{SEP}\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python nba_dashboard.py \"<Player Name>\" [season]")
        print('       python nba_dashboard.py "LeBron James" 2025-26')
        sys.exit(1)

    _name   = sys.argv[1]
    _season = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SEASON
    print_dashboard(_name, _season)
