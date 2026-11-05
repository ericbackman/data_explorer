"""Tests for the page builder's pure functions (nba_site/investigations/injury-era/build_data.py)."""

import importlib.util
import sys
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[2] / "nba_site" / "investigations" / "injury-era" / "build_data.py"
spec = importlib.util.spec_from_file_location("injury_era_build_data", BUILD)
bd = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bd
spec.loader.exec_module(bd)


def _row(player, location, date, status="Out", season="2024-25", category="injury", nature=""):
    return {"player": player, "location": location, "report_date": date, "status": status, "season": season, "category": category, "nature": nature}


def test_episodes_split_on_gap():
    rows = [
        _row("A", "ankle", "2024-11-01"),
        _row("A", "ankle", "2024-11-03"),
        _row("A", "ankle", "2024-11-30"),  # 27 days later: new episode
        _row("A", "knee", "2024-11-03", status="Questionable"),
        _row("B", "ankle", "2024-11-03", category="rest"),  # ignored
    ]
    eps = bd.episodes(rows)
    keys = sorted((e["player"], e["location"], e["first"]) for e in eps)
    assert keys == [("A", "ankle", "2024-11-01"), ("A", "ankle", "2024-11-30"), ("A", "knee", "2024-11-03")]
    first = next(e for e in eps if e["first"] == "2024-11-01")
    assert first["report_days"] == 2 and first["out_days"] == 2 and first["last"] == "2024-11-03"
    knee = next(e for e in eps if e["location"] == "knee")
    assert knee["out_days"] == 0


def test_season_anchor_skips_the_previous_seasons_tail():
    import datetime as dt

    bubble_tail = [dt.date(2020, 10, 1), dt.date(2020, 10, 3), dt.date(2020, 10, 11)]
    own_run = [dt.date(2020, 12, 11), dt.date(2020, 12, 12), dt.date(2021, 1, 5)]
    assert bd.season_anchor(bubble_tail + own_run) == dt.date(2020, 12, 11)
    assert bd.season_anchor(own_run) == dt.date(2020, 12, 11)
    with pytest.raises(ValueError):
        bd.season_anchor([])


def test_location_table_shares_and_below_knee():
    from collections import Counter

    tbl = bd.location_table(Counter({"ankle": 3, "knee": 1, "foot": 1}))
    assert tbl["n"] == 5
    assert tbl["shares"]["ankle"] == 0.6
    assert tbl["below_knee_share"] == 0.8
    with pytest.raises(ValueError):
        bd.location_table(Counter())


def test_era_means():
    series = [{"season": "2000-01", "x": 1.0}, {"season": "2001-02", "x": 3.0}, {"season": "2002-03", "x": None}]
    out = bd.era_means(series, "x", [("a", "2000-01", "2002-03")])
    assert out[0]["mean"] == 2.0 and out[0]["seasons"] == 2
    with pytest.raises(ValueError):
        bd.era_means(series, "x", [("b", "2010-11", "2011-12")])


def test_build_missed_skips_partial_and_early():
    missed = [
        {"season": "1950-51", "team_games": "100", "rotation_players": "", "rotation_missed": "", "rotation_missed_per_team_game": "", "rotation_missed_share": "", "rotation_tail_missed": "", "rotation_head_missed": "", "rotation_gap_missed": "", "rotation_missed_10plus": "", "rotation_missed_20plus": "", "rotation_missed_0": "", "all_missed_per_team_game": "1.0"},
        {"season": "1980-81", "team_games": "1886", "rotation_players": "177", "rotation_missed": "1139", "rotation_missed_per_team_game": "0.6039", "rotation_missed_share": "0.0834", "rotation_tail_missed": "295", "rotation_head_missed": "16", "rotation_gap_missed": "828", "rotation_missed_10plus": "33", "rotation_missed_20plus": "15", "rotation_missed_0": "63", "all_missed_per_team_game": "1.6787"},
        {"season": "2026-27", "team_games": "242", "rotation_players": "5", "rotation_missed": "1", "rotation_missed_per_team_game": "0.004", "rotation_missed_share": "0.001", "rotation_tail_missed": "0", "rotation_head_missed": "0", "rotation_gap_missed": "1", "rotation_missed_10plus": "0", "rotation_missed_20plus": "0", "rotation_missed_0": "4", "all_missed_per_team_game": "0.1"},
    ]
    minutes = [{"season": s, "minutes_coverage": "0.99"} for s in ("1950-51", "1980-81", "2026-27")]
    schedule = [{"season": "1950-51", "partial": "0"}, {"season": "1980-81", "partial": "0"}, {"season": "2026-27", "partial": "1"}]
    out = bd.build_missed(missed, minutes, schedule)
    assert [o["season"] for o in out] == ["1980-81"]
    assert out[0]["per_team_game"] == 0.604
