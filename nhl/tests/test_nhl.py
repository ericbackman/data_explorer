"""Unit tests for the pure NHL logic — no network, no DB.

The safety-critical piece is the playoff-series derivation (``series.py``): the
blown-lead detector feeds an essay's factual claims, so its edge cases (a blown
3-1 lead vs. a tight Game-7 loss vs. a comeback win) must be pinned down.
"""

from nhl import api, series


# ── api.toi_to_seconds ────────────────────────────────────────────────────────

def test_toi_to_seconds():
    assert api.toi_to_seconds("14:01") == 841
    assert api.toi_to_seconds("65:00") == 3900   # OT can push minutes past 59
    assert api.toi_to_seconds("0:00") == 0
    assert api.toi_to_seconds(None) is None
    assert api.toi_to_seconds("") is None


# ── series.group_series ───────────────────────────────────────────────────────

def test_group_series_segments_by_opponent_and_season():
    rows = [
        ("20222023", 14, 1), ("20222023", 14, 0),   # vs 14, round 1
        ("20222023", 13, 0), ("20222023", 13, 1),   # vs 13, round 2 (opponent changed)
        ("20232024", 6, 1),                          # new season resets
    ]
    grouped = series.group_series(rows)
    assert [g["opponent_id"] for g in grouped] == [14, 13, 6]
    assert grouped[0]["results"] == [1, 0]


# ── series.summarize: the four heartbreak shapes ──────────────────────────────

def _one(results, opponent_id=99, season="20202021"):
    grouped = series.group_series([(season, opponent_id, w) for w in results])
    return series.summarize(grouped, team_id=10)[0]


def test_blown_3_1_lead_is_flagged():
    # up 3-1, then lost three straight (the 2021 Leafs vs Montreal shape).
    s = _one([1, 0, 1, 1, 0, 0, 0])
    assert (s["team_wins"], s["opp_wins"]) == (3, 4)
    assert s["series_won"] == 0
    assert s["went_to_game7"] == 1
    assert s["max_series_lead"] == 2      # was up 3-1
    assert s["blew_lead"] == 1


def test_tight_game7_loss_is_not_a_blown_lead():
    # traded blows the whole way, lost Game 7 — never led by two.
    s = _one([0, 1, 0, 1, 0, 1, 0])
    assert (s["team_wins"], s["opp_wins"]) == (3, 4)
    assert s["went_to_game7"] == 1
    assert s["max_series_lead"] == 0
    assert s["blew_lead"] == 0            # a close loss is not a blown lead


def test_sweep_win():
    s = _one([1, 1, 1, 1])
    assert s["series_won"] == 1
    assert s["went_to_game7"] == 0
    assert s["max_series_lead"] == 4
    assert s["blew_lead"] == 0


def test_comeback_win_is_never_a_blown_lead():
    # down 0-3, won four straight — a winner is never flagged, even trailing badly.
    s = _one([0, 0, 0, 1, 1, 1, 1])
    assert s["series_won"] == 1
    assert s["max_series_lead"] == 1
    assert s["blew_lead"] == 0


def test_round_numbering_and_names_within_a_season():
    rows = [("20222023", 14, w) for w in (1, 1, 1, 0, 1)]     # win R1
    rows += [("20222023", 13, w) for w in (0, 0, 1, 0)]       # lose R2
    out = series.summarize(series.group_series(rows), team_id=10)
    assert [(o["round_num"], o["round_name"]) for o in out] == [
        (1, "First Round"), (2, "Second Round")]
