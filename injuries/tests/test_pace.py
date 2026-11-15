"""Tests for injuries/pace.py: pure functions on tiny fixtures, remote call mocked."""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pace  # noqa: E402

D = dt.date


def tg(season="2024-25", stype="Regular Season", gid="g1", team=1, date="2024-10-22", minutes=240.0,
       fgm=40, fga=90, fg3a=35, fta=20, oreb=10, dreb=33, tov=14, pts=110):
    return dict(season=season, season_type=stype, game_id=gid, team_id=team, game_date=date, min=minutes,
                fgm=fgm, fga=fga, fg3a=fg3a, fta=fta, oreb=oreb, dreb=dreb, tov=tov, pts=pts)


def test_possessions_formula():
    assert pace.possessions(fga=90, oreb=10, tov=14, fta=20) == pytest.approx(90 - 10 + 14 + 0.44 * 20)


def test_pace_regulation_and_overtime_scaling():
    assert pace.pace_per_48(100.0, 240.0) == pytest.approx(100.0)
    # one overtime: 265 team minutes = 53 game minutes, so 100 possessions is a slower 90.57 per 48
    assert pace.pace_per_48(100.0, 265.0) == pytest.approx(48 * 100 / 53)


def test_pace_rejects_zero_minutes():
    with pytest.raises(ValueError):
        pace.pace_per_48(100.0, 0.0)


def test_back_to_backs_and_rest():
    dates = [D(2025, 1, 1), D(2025, 1, 2), D(2025, 1, 4), D(2025, 1, 5), D(2025, 1, 6)]
    assert pace.count_back_to_backs(dates) == 3          # 1-2, 4-5, 5-6
    assert pace.rest_gaps(dates) == [0, 1, 0, 0]
    assert pace.count_back_to_backs(reversed(dates)) == 3   # order-independent


def test_same_date_games_are_not_back_to_backs_and_rest_is_not_negative():
    dates = [D(1956, 1, 1), D(1956, 1, 1), D(1956, 1, 2)]
    assert pace.rest_gaps(dates) == [0, 0]
    assert pace.count_back_to_backs(dates) == 1


def test_summarize_schedule_tiny_season():
    rows = []
    for gid, date, home, away in [("a", "2025-01-01", 1, 2), ("b", "2025-01-02", 1, 3), ("c", "2025-01-05", 2, 3)]:
        rows += [tg(gid=gid, team=home, date=date), tg(gid=gid, team=away, date=date)]
    rows += [tg(stype="Playoffs", gid="p1", team=1, date="2025-04-20"), tg(stype="Playoffs", gid="p1", team=2, date="2025-04-20"),
             tg(stype="Playoffs", gid="p2", team=1, date="2025-04-22"), tg(stype="Playoffs", gid="p2", team=2, date="2025-04-22")]
    (s,) = pace.summarize_schedule(rows)
    assert s["games_per_team"] == 2
    assert s["season_span_days"] == 4
    # team1: 1/1,1/2 (b2b); team2: 1/1,1/5; team3: 1/2,1/5 -> 1 b2b over 3 teams
    assert s["back_to_backs_per_team"] == pytest.approx(1 / 3)
    assert s["mean_rest_days"] == pytest.approx((0 + 3 + 2) / 3)
    assert s["playoff_games_total"] == 2
    assert s["playoff_games_max_team"] == 2


def test_summarize_pace_reports_and_blanks_on_missing_tov():
    modern = [tg(gid=f"m{i}", team=t) for i in range(4) for t in (1, 2)]
    old = [tg(season="1970-71", gid=f"o{i}", team=t, tov=None, minutes=240.0) for i in range(4) for t in (1, 2)]
    by = {r["season"]: r for r in pace.summarize_pace(modern + old)}
    assert by["2024-25"]["pace"] == pytest.approx(90 - 10 + 14 + 0.44 * 20)
    assert by["2024-25"]["fg3a_share_of_fga"] == pytest.approx(35 / 90)
    assert by["1970-71"]["pace"] is None
    assert "TOV" in by["1970-71"]["pace_note"]
    assert by["1970-71"]["team_games"] == 8 and by["1970-71"]["pace_team_games"] == 0


def test_summarize_pace_treats_tov_zero_and_zero_minutes_as_missing():
    rows = [tg(gid=f"g{i}", team=t) for i in range(20) for t in (1, 2)]
    rows.append(tg(gid="bad1", team=1, tov=0))
    rows.append(tg(gid="bad2", team=1, minutes=0.0))
    (s,) = pace.summarize_pace(rows)
    assert s["team_games"] == 42 and s["pace_team_games"] == 40      # 95.2% coverage, still reported
    assert s["pace"] == pytest.approx(90 - 10 + 14 + 0.44 * 20)


def test_summarize_pace_excludes_playoffs():
    rows = [tg(gid=f"g{i}", team=t) for i in range(3) for t in (1, 2)] + [tg(stype="Playoffs", gid="p", fga=200)]
    (s,) = pace.summarize_pace(rows)
    assert s["team_games"] == 6 and s["fga_per_game"] == 90


def test_bbr_formula_matches_hand_calculation():
    a = tg(gid="g", team=1)
    b = tg(gid="g", team=2, fgm=38, fga=88, fta=24, oreb=9, dreb=30, tov=12)
    poss_a = 90 + 0.4 * 20 - 1.07 * (10 / (10 + 30)) * (90 - 40) + 14
    poss_b = 88 + 0.4 * 24 - 1.07 * (9 / (9 + 33)) * (88 - 38) + 12
    assert pace.bbr_possessions(90, 20, 10, 40, 14, 30) == pytest.approx(poss_a)
    got = pace._bbr_paces([a, b])
    assert got == [pytest.approx((poss_a + poss_b) / 2)] * 2


def ps(season="2024-25", stype="Regular Season", player=1, team=10, minutes=1000.0, gp=50, rows=50):
    return dict(season=season, season_type=stype, player_id=player, team_id=team, minutes=minutes,
                games_played=gp, rows=rows)


def test_summarize_minutes_top_n_and_thresholds():
    rows = [ps(player=p, team=10, minutes=3000.0 - 100 * p) for p in range(10)]   # 3000 ... 2100
    rows += [ps(player=p, team=11, minutes=500.0) for p in range(20, 30)]
    rows += [ps(stype="Playoffs", player=0, minutes=999.0)]
    (s,) = pace.summarize_minutes(rows)
    top8_team10 = sum(3000 - 100 * p for p in range(8))
    assert s["top8_mean_minutes"] == pytest.approx((top8_team10 + 8 * 500) / 2)
    assert s["top1_mean_minutes"] == pytest.approx((3000 + 500) / 2)
    assert s["players_2500_plus"] == 6 and s["players_3000_plus"] == 1   # 3000, 2900 ... 2500
    assert s["mean_minutes_per_player_game"] == pytest.approx((sum(3000 - 100 * p for p in range(10)) + 5000) / (20 * 50))
    assert s["players_appeared"] == 20


def test_summarize_minutes_blank_when_minutes_unrecorded():
    rows = [ps(minutes=0.0, gp=0, rows=40)]
    (s,) = pace.summarize_minutes(rows)
    assert s["top8_mean_minutes"] is None and "recorded for only 0%" in s["minutes_note"]
    assert s["players_appeared"] == 1


def test_finals_teams_take_last_playoff_game():
    games = [dict(season="2024-25", game_id="p1", game_date="2025-05-01", home_team_id=1, away_team_id=2),
             dict(season="2024-25", game_id="p9", game_date="2025-06-22", home_team_id=7, away_team_id=8),
             dict(season="2024-25", game_id="p8", game_date="2025-06-19", home_team_id=8, away_team_id=7)]
    assert pace.finals_teams(games) == {"2024-25": (7, 8)}


def test_build_leaders_top3_and_finals_leader():
    reg = [ps(player=1, team=7, minutes=3000), ps(player=2, team=7, minutes=2000), ps(player=3, team=8, minutes=2900),
           ps(player=4, team=8, minutes=2800), ps(player=5, team=9, minutes=2950),
           ps(player=3, team=9, minutes=100)]          # player 3 traded: 3000 total, 2900 with team 8
    po = [ps(stype="Playoffs", player=1, team=7, minutes=800, gp=20), ps(stype="Playoffs", player=3, team=8, minutes=600, gp=15)]
    games = [dict(season="2024-25", game_id="p9", game_date="2025-06-22", home_team_id=7, away_team_id=8)]
    out = pace.build_leaders(reg + po, games, {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}, {7: "OKC", 8: "IND", 9: "ZZZ"})
    top = [r for r in out if r["group"] == "league_top3"]
    assert [r["player_id"] for r in top] == [1, 3, 5]          # 3000, 3000 (tie, lower id first), 2950
    assert top[1]["team"] == "IND/ZZZ" and top[1]["regular_minutes"] == 3000 and top[1]["playoff_minutes"] == 600
    fin = {r["team"]: r for r in out if r["group"] == "finals_team_leader"}
    assert fin["OKC"]["player_id"] == 1 and fin["OKC"]["playoff_minutes"] == 800
    assert fin["IND"]["player_id"] == 3 and fin["IND"]["regular_minutes"] == 2900


def test_build_leaders_respects_from_season_and_exclude():
    rows = [ps(season="1995-96", player=1), ps(season="2026-27", player=2)]
    assert pace.build_leaders(rows, [], {}, {}, exclude={"2026-27"}) == []


def test_partial_seasons_only_latest_without_playoffs():
    rows = [tg(season="2025-26"), tg(season="2025-26", stype="Playoffs"), tg(season="2026-27")]
    assert pace.partial_seasons(rows) == {"2026-27"}
    assert pace.partial_seasons(rows[:2]) == set()


def test_first_plus_minus_season_skips_seasons_without_zero_rows():
    def z(s, n, null):
        return dict(season=s, season_type="Regular Season", zero_minute_rows=n, zero_plus_minus_null=null)
    rows = [z("1994-95", 1, 1), z("1995-96", 0, 0), z("1996-97", 170, 0), z("1997-98", 136, 0)]
    assert pace.first_plus_minus_season(rows) == "1996-97"


def test_blackout_window():
    assert pace.in_blackout(dt.datetime(2026, 11, 5, 6, 10))
    assert pace.in_blackout(dt.datetime(2026, 11, 5, 6, 29))
    assert not pace.in_blackout(dt.datetime(2026, 11, 5, 6, 30))
    assert not pace.in_blackout(dt.datetime(2026, 11, 5, 11, 0))


def test_remote_script_is_read_only_and_checks_wal_twice():
    script = pace.build_remote_script("SELECT 1")
    assert "mode=ro&immutable=1" in script and "query_only" in script
    assert script.count('check("') == 2
    compile(script, "<remote>", "exec")


def _proc(code, out="", err=""):
    return subprocess.CompletedProcess([], code, stdout=out, stderr=err)


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(pace, "in_blackout", lambda now: False)
    monkeypatch.setattr(pace.time, "sleep", lambda s: None)
    monkeypatch.setattr(pace, "SSH_HOST", "dbhost")
    monkeypatch.setattr(pace, "DB_PATH", "/data/nba.db")


def test_run_remote_parses_rows(monkeypatch, quiet):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0, '{"cols": ["a", "b"], "rows": [[1, 2]]}'))
    assert pace.run_remote("SELECT 1") == [{"a": 1, "b": 2}]


def test_run_remote_raises_at_once_on_busy_wal(monkeypatch, quiet):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(1) or _proc(pace.EXIT_WAL_BUSY, err="mid-write"))
    with pytest.raises(RuntimeError, match="mid-write"):
        pace.run_remote("SELECT 1")
    assert len(calls) == 1


def test_run_remote_retries_dropped_connection_then_raises(monkeypatch, quiet):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(1) or _proc(pace.SSH_CONNECT_FAILURE, err="reset"))
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        pace.run_remote("SELECT 1")
    assert len(calls) == pace.SSH_RETRIES


def test_run_remote_refuses_in_blackout(monkeypatch):
    monkeypatch.setattr(pace, "in_blackout", lambda now: True)
    with pytest.raises(RuntimeError, match="06:30"):
        pace.run_remote("SELECT 1")
