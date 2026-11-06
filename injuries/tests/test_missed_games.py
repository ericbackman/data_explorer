import pytest

from injuries.missed_games import compute_player_rows, games_between, next_season, prev_season, season_summary

DATES = [f"2024-11-{d:02d}" for d in range(1, 11)]  # ten team games
DATES_12 = [f"2024-11-{d:02d}" for d in range(1, 13)]
TEAM_DATES = {(1, "2024-25"): DATES, (1, "2025-26"): DATES, (1, "2023-24"): DATES}


def _tenure(player_id, season, first, last, gp, min_total=600.0, min_null=0):
    return {"player_id": player_id, "team_id": 1, "season": season, "first_date": first, "last_date": last, "gp": gp, "min_total": min_total, "min_null": min_null}


def test_games_between_inclusive():
    assert games_between(DATES, "2024-11-02", "2024-11-05") == 4
    assert games_between(DATES, "2024-10-01", "2024-12-01") == 10
    assert games_between(DATES, "2024-11-05", "2024-11-05") == 1


def test_season_arithmetic():
    assert next_season("2024-25") == "2025-26"
    assert prev_season("2000-01") == "1999-00"


def test_gap_only_when_no_adjacent_season():
    rows = compute_player_rows([_tenure(7, "2024-25", "2024-11-02", "2024-11-08", 5, min_total=150.0)], TEAM_DATES, {7: "A"})
    r = rows[0]
    assert r["window_games"] == 7 and r["gap_missed"] == 2
    assert r["tail_missed"] == 0 and r["head_missed"] == 0
    assert r["mpg"] == 30.0


def test_tail_and_head_count_only_for_returning_players():
    tenure = [
        _tenure(7, "2023-24", "2024-11-01", "2024-11-10", 10),
        _tenure(7, "2024-25", "2024-11-03", "2024-11-06", 4, min_total=100.0),
        _tenure(7, "2025-26", "2024-11-01", "2024-11-10", 10),
    ]
    rows = {r["season"]: r for r in compute_player_rows(tenure, TEAM_DATES, {})}
    mid = rows["2024-25"]
    assert mid["head_missed"] == 2  # games on the 1st and 2nd
    assert mid["tail_missed"] == 4  # 7th to 10th
    assert mid["gap_missed"] == 0
    assert rows["2023-24"]["head_missed"] == 0  # no 2022-23 row


def test_rotation_flag_needs_minutes_and_games():
    rows = compute_player_rows(
        [
            _tenure(1, "2024-25", "2024-11-01", "2024-11-10", 10, min_total=250.0),  # 25 mpg -> rotation
            _tenure(2, "2024-25", "2024-11-01", "2024-11-10", 10, min_total=100.0),  # 10 mpg
            _tenure(3, "2024-25", "2024-11-01", "2024-11-10", 5, min_total=200.0),  # 40 mpg but 5 gp
            _tenure(4, "2024-25", "2024-11-01", "2024-11-10", 10, min_total=0.0, min_null=10),  # no minutes
        ],
        TEAM_DATES,
        {},
    )
    assert [r["rotation"] for r in rows] == [1, 0, 0, 0]
    assert rows[3]["mpg"] == ""


def test_negative_gap_is_an_error():
    with pytest.raises(ValueError):
        compute_player_rows([_tenure(1, "2024-25", "2024-11-01", "2024-11-02", 5)], TEAM_DATES, {})


def test_missing_team_schedule_is_an_error():
    with pytest.raises(KeyError):
        compute_player_rows([_tenure(1, "1999-00", "2024-11-01", "2024-11-02", 1)], TEAM_DATES, {})


def test_season_summary_rates():
    rows = compute_player_rows(
        [
            _tenure(1, "2024-25", "2024-11-01", "2024-11-12", 10, min_total=300.0),  # rotation, 2 gap
            _tenure(2, "2024-25", "2024-11-01", "2024-11-12", 12, min_total=60.0),  # bench
        ],
        {(1, "2024-25"): DATES_12},
        {},
    )
    s = season_summary(rows, {(1, "2024-25"): DATES_12})[0]
    assert s["team_games"] == 12 and s["teams"] == 1
    assert s["rotation_players"] == 1 and s["rotation_missed"] == 2
    assert s["rotation_missed_per_team_game"] == round(2 / 12, 4)
    assert s["rotation_missed_share"] == round(2 / 12, 4)  # 2 / (2 + 10)
    assert s["all_missed"] == 2


def test_pre_minutes_seasons_have_no_rotation_series():
    rows = compute_player_rows([_tenure(1, "1949-50", "2024-11-01", "2024-11-10", 8, min_total=0.0, min_null=8)], {(1, "1949-50"): DATES}, {})
    s = season_summary(rows, {(1, "1949-50"): DATES})[0]
    assert s["rotation_missed"] == "" and "1951-52" in s["note"]
