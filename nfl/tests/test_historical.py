"""Spreadspoke normalization tests (no network)."""

import pandas as pd

from nfl import historical


def _row(**kw):
    base = dict(schedule_date="09/18/1966", schedule_season=1966, schedule_week="2",
                schedule_playoff=False, team_home="Oakland Raiders", score_home=14,
                score_away=21, team_away="Houston Oilers", over_under_line=None,
                stadium="Oakland Coliseum", stadium_neutral=False,
                weather_temperature=70, weather_wind_mph=5)
    base.update(kw)
    return base


def test_normalize_regular_game_maps_relocated_teams():
    out = historical.normalize(pd.DataFrame([_row()]))
    g = out.iloc[0]
    assert g.home_team == "LV" and g.away_team == "TEN"   # Oakland->LV, Houston Oilers->TEN
    assert g.week == 2 and g.game_type == "REG"
    assert g.gameday == "1966-09-18"
    assert g.result == -7 and g.total == 35               # home 14 - away 21
    assert g.source == "spreadspoke"


def test_normalize_superbowl_round_and_score():
    sb = _row(schedule_date="01/15/1967", schedule_week="Superbowl", schedule_playoff=True,
              team_home="Green Bay Packers", score_home=35, team_away="Kansas City Chiefs",
              score_away=10, stadium_neutral=True)
    g = historical.normalize(pd.DataFrame([sb])).iloc[0]
    assert g.game_type == "SB" and g.home_team == "GB" and g.away_team == "KC"
    assert g.result == 25 and g.location == "Neutral"
    assert g.game_id == "1966_21_KC_GB"


def test_normalize_filters_to_pre_1999():
    rows = pd.DataFrame([_row(schedule_season=1975), _row(schedule_season=2010)])
    out = historical.normalize(rows)
    assert set(out.season) == {1975}                       # 2010 dropped (nflverse covers it)


def test_unmapped_team_fails_loud():
    import pytest
    with pytest.raises(ValueError):
        historical.normalize(pd.DataFrame([_row(team_home="London Monarchs")]))
