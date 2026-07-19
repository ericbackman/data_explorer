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


def parse_draft(df: pd.DataFrame) -> list[dict]:
    """DraftHistory dataframe -> one row dict per pick.

    Skips rows with no usable OVERALL_PICK (forfeited/placeholder entries carry
    no slot and can't key the table) rather than writing a null-keyed row. Season
    and overall_pick are coerced to int; a row that can't be coerced is skipped —
    the caller logs the resulting count so a shrunk pull is visible, not silent.
    """
    rows = []
    for r in df.to_dict(orient="records"):
        overall = _num(r.get("OVERALL_PICK"))
        season = _num(r.get("SEASON"))
        if overall is None or season is None:
            continue
        try:
            season_i, overall_i = int(season), int(overall)
        except (TypeError, ValueError):
            continue
        rows.append({
            "season": season_i,
            "overall_pick": overall_i,
            "round_number": _num(r.get("ROUND_NUMBER")),
            "round_pick": _num(r.get("ROUND_PICK")),
            "person_id": _num(r.get("PERSON_ID")),
            "player_name": r.get("PLAYER_NAME"),
            "team_id": _num(r.get("TEAM_ID")),
            "team_city": r.get("TEAM_CITY"),
            "team_name": r.get("TEAM_NAME"),
            "team_abbreviation": r.get("TEAM_ABBREVIATION"),
            "organization": r.get("ORGANIZATION"),
            "organization_type": r.get("ORGANIZATION_TYPE"),
            "draft_type": r.get("DRAFT_TYPE"),
        })
    return rows


def parse_player_awards(df: pd.DataFrame, person_id: int) -> list[dict]:
    """PlayerAwards dataframe -> one normalized row per award instance for a player.

    Keeps the award (DESCRIPTION), its SEASON, and the All-NBA/All-Defensive team
    number (1/2/3) when present. An empty frame (a player with no awards) yields [].
    """
    rows = []
    for r in df.to_dict(orient="records"):
        desc = r.get("DESCRIPTION")
        if not desc or not str(desc).strip():
            continue
        tn = _num(r.get("ALL_NBA_TEAM_NUMBER"))
        try:
            tn = int(tn) if tn is not None else None
        except (TypeError, ValueError):
            tn = None
        rows.append({
            "person_id": int(person_id),
            "season": _num(r.get("SEASON")),
            "description": str(desc).strip(),
            "team_number": tn,
        })
    return rows


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
