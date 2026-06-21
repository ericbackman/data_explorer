"""LeagueGameLog dataframes -> normalized row dicts.

Pure functions: dataframe in, list[dict] out. No IO, no network, no clock — so
they're trivially unit-testable against a tiny fixture. Raw facts only; derived
betting metrics (pace, rest, ATS, usage) are computed downstream in SQL/analysis,
never baked into storage.
"""

from __future__ import annotations

import datetime
import math
from typing import Any

import pandas as pd

EARLIEST_SEASON = 1946  # 1946-47 was the first BAA/NBA season


def season_str(start_year: int) -> str:
    """1996 -> '1996-97'."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def season_range(start_year: int, end_year: int) -> list[str]:
    """Inclusive list of season strings, by start year (2023,2025 -> 3 seasons)."""
    return [season_str(y) for y in range(start_year, end_year + 1)]


def current_season_str(today: datetime.date | None = None) -> str:
    """The season in progress. NBA seasons start in October and span two years,
    so anything before October belongs to the season that began last year.
    `today` is injectable so tests don't depend on the wall clock.
    """
    today = today or datetime.date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return season_str(start_year)


def _num(val: Any) -> Any:
    """None for NaN/blank, else the value as-is (sqlite handles int/float/str)."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    return val


def _is_home(matchup: str | None) -> bool:
    # "LAL vs. BOS" => home game; "LAL @ BOS" => away game.
    return "vs." in (matchup or "")


# Box-score stat columns shared by player and team logs (nba_api col -> our col).
_STAT_COLS = {
    "MIN": "min", "FGM": "fgm", "FGA": "fga", "FG_PCT": "fg_pct",
    "FG3M": "fg3m", "FG3A": "fg3a", "FG3_PCT": "fg3_pct",
    "FTM": "ftm", "FTA": "fta", "FT_PCT": "ft_pct",
    "OREB": "oreb", "DREB": "dreb", "REB": "reb", "AST": "ast",
    "STL": "stl", "BLK": "blk", "TOV": "tov", "PF": "pf",
    "PTS": "pts", "PLUS_MINUS": "plus_minus",
}


def _common(r: dict, season: str, season_type: str) -> dict:
    out = {
        "game_id": str(r["GAME_ID"]).zfill(10),
        "team_id": int(r["TEAM_ID"]),
        "team_abbreviation": r.get("TEAM_ABBREVIATION"),
        "team_name": r.get("TEAM_NAME"),
        "season": season,
        "season_type": season_type,
        "game_date": r.get("GAME_DATE"),
        "matchup": r.get("MATCHUP"),
        "wl": r.get("WL"),
    }
    for src, dst in _STAT_COLS.items():
        out[dst] = _num(r.get(src))
    return out


def parse_player_log(df: pd.DataFrame, season: str, season_type: str) -> list[dict]:
    rows = []
    for r in df.to_dict(orient="records"):
        row = _common(r, season, season_type)
        row["player_id"] = int(r["PLAYER_ID"])
        row["player_name"] = r.get("PLAYER_NAME")
        rows.append(row)
    return rows


def parse_team_log(df: pd.DataFrame, season: str, season_type: str) -> list[dict]:
    return [_common(r, season, season_type) for r in df.to_dict(orient="records")]


def derive_games(team_rows: list[dict]) -> list[dict]:
    """Collapse the two team rows of each game into one game row.

    In-progress games can appear with only one team row; we skip those rather
    than write a half-game (they'll be picked up complete on the next refetch).
    """
    by_game: dict[str, list[dict]] = {}
    for r in team_rows:
        by_game.setdefault(r["game_id"], []).append(r)

    games = []
    for game_id, sides in by_game.items():
        home = next((s for s in sides if _is_home(s["matchup"])), None)
        away = next((s for s in sides if not _is_home(s["matchup"])), None)
        if home is None or away is None:
            continue
        games.append({
            "game_id": game_id,
            "season": home["season"],
            "season_type": home["season_type"],
            "game_date": home["game_date"],
            "home_team_id": home["team_id"],
            "away_team_id": away["team_id"],
            "home_pts": home["pts"],
            "away_pts": away["pts"],
        })
    return games
