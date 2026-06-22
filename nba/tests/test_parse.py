"""Pure-function tests — no network, no DB. Run: python -m pytest nba/"""

import datetime

import pandas as pd

from nba import parse


def test_season_str_and_range():
    assert parse.season_str(1996) == "1996-97"
    assert parse.season_str(1999) == "1999-00"
    assert parse.season_range(2023, 2025) == ["2023-24", "2024-25", "2025-26"]


def test_current_season_before_october_belongs_to_prior_year():
    assert parse.current_season_str(datetime.date(2026, 6, 21)) == "2025-26"
    assert parse.current_season_str(datetime.date(2025, 11, 1)) == "2025-26"


def test_parse_player_log_normalizes_and_nulls_blanks():
    df = pd.DataFrame([{
        "GAME_ID": "21500001", "PLAYER_ID": 977, "PLAYER_NAME": "Kobe Bryant",
        "TEAM_ID": 1610612747, "TEAM_ABBREVIATION": "LAL", "TEAM_NAME": "Lakers",
        "GAME_DATE": "2015-10-27", "MATCHUP": "LAL vs. MIN", "WL": "L",
        "MIN": 24, "PTS": 24, "FG_PCT": "", "PLUS_MINUS": float("nan"),
    }])
    [row] = parse.parse_player_log(df, "2015-16", "Regular Season")
    assert row["game_id"] == "0021500001"   # zero-padded to 10
    assert row["player_id"] == 977
    assert row["pts"] == 24
    assert row["fg_pct"] is None            # blank -> None
    assert row["plus_minus"] is None        # NaN -> None


def test_derive_games_collapses_two_team_rows():
    team_rows = [
        {"game_id": "0021500001", "team_id": 1, "matchup": "LAL vs. MIN",
         "season": "2015-16", "season_type": "Regular Season",
         "game_date": "2015-10-27", "pts": 111},
        {"game_id": "0021500001", "team_id": 2, "matchup": "MIN @ LAL",
         "season": "2015-16", "season_type": "Regular Season",
         "game_date": "2015-10-27", "pts": 112},
    ]
    [game] = parse.derive_games(team_rows)
    assert game["home_team_id"] == 1 and game["home_pts"] == 111
    assert game["away_team_id"] == 2 and game["away_pts"] == 112


def test_derive_games_skips_incomplete_single_side():
    # An in-progress game with only one team row must not produce a half-game.
    assert parse.derive_games([
        {"game_id": "x", "team_id": 1, "matchup": "LAL vs. MIN",
         "season": "s", "season_type": "t", "game_date": "d", "pts": 50},
    ]) == []
