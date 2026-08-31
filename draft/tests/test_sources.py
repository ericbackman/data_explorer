"""Adapter normalization for the gnarly feeds (NHL, MLB), with HTTP stubbed.

These lock in the league-specific rules: NHL drops voided picks and tags the
supplemental draft; MLB skips passes/forfeits and NULLs non-numeric round labels.
No network — `get_json` is monkeypatched.
"""
from __future__ import annotations

from draft.sources import mlb, nba, nhl


def test_nba_fills_unnumbered_picks_deterministically():
    # Pre-1966 picks the feed left at overall_pick=0 get numbered after the last
    # real pick, in source order; each (year, draft_type) group restarts.
    rows = [
        {"draft_year": 1956, "draft_type": "regular", "overall_pick": 1, "player_name": "Real1"},
        {"draft_year": 1956, "draft_type": "regular", "overall_pick": 2, "player_name": "Real2"},
        {"draft_year": 1956, "draft_type": "regular", "overall_pick": 0, "player_name": "Zero1"},
        {"draft_year": 1956, "draft_type": "regular", "overall_pick": 0, "player_name": "Zero2"},
        {"draft_year": 1956, "draft_type": "territorial", "overall_pick": 0, "player_name": "TerrA"},
    ]
    out = nba._fill_missing_overall([dict(r) for r in rows])
    by = {r["player_name"]: r["overall_pick"] for r in out}
    assert (by["Real1"], by["Real2"]) == (1, 2)       # real numbers preserved
    assert (by["Zero1"], by["Zero2"]) == (3, 4)       # filled after max real, in order
    assert by["TerrA"] == 1                           # separate group restarts
    reg = [r["overall_pick"] for r in out if r["draft_type"] == "regular"]
    assert len(reg) == len(set(reg))                  # unique within the group


def test_nhl_drops_voided_and_tags_supplemental(monkeypatch):
    fake = {"total": 3, "data": [
        {"draftYear": 2023, "roundNumber": 1, "pickInRound": 1, "overallPickNumber": 1,
         "triCode": "CHI", "draftedByTeamId": 16, "playerName": "Connor Bedard",
         "playerId": 8484144, "position": "C", "amateurClubName": "Regina",
         "amateurLeague": "WHL", "supplementalDraft": "N", "removedOutright": "N"},
        {"draftYear": 2023, "roundNumber": 2, "pickInRound": 1, "overallPickNumber": 33,
         "triCode": "XYZ", "playerName": "Voided Guy", "playerId": 1,
         "supplementalDraft": "N", "removedOutright": "Y"},
        {"draftYear": 1990, "roundNumber": 1, "pickInRound": 1, "overallPickNumber": 1,
         "triCode": "NYR", "playerName": "Supp Guy", "playerId": 2,
         "supplementalDraft": "Y", "removedOutright": "N"},
    ]}
    monkeypatch.setattr(nhl, "get_json", lambda url, **k: fake)
    rows = nhl.fetch(years=[2023])
    by_name = {r["player_name"]: r for r in rows}
    assert "Voided Guy" not in by_name                       # removedOutright dropped
    assert by_name["Connor Bedard"]["draft_type"] == "regular"
    assert by_name["Supp Guy"]["draft_type"] == "supplemental"
    assert by_name["Connor Bedard"]["native_player_id"] == "8484144"
    assert by_name["Connor Bedard"]["team_abbr"] == "CHI"


def test_mlb_skips_passes_and_flattens(monkeypatch):
    fake = {"drafts": {"rounds": [
        {"round": "1", "picks": [
            {"pickNumber": 1, "roundPickNumber": 1, "year": 2023, "isPass": False,
             "person": {"id": 5010764, "fullName": "Paul Skenes",
                        "primaryPosition": {"abbreviation": "P"}},
             "team": {"id": 134, "name": "Pittsburgh Pirates"},
             "school": {"name": "LSU", "schoolClass": "4YR JR"}},
            {"pickNumber": 2, "roundPickNumber": 2, "year": 2023, "isPass": True,
             "person": {}},
        ]},
        {"round": "CBA", "picks": [
            {"pickNumber": 40, "roundPickNumber": 1, "year": 2023,
             "person": {"id": 999, "fullName": "Comp Pick"},
             "team": {"id": 120, "name": "Washington Nationals"}},
        ]},
    ]}}
    monkeypatch.setattr(mlb, "get_json", lambda url, **k: fake)
    rows = mlb.fetch(years=[2023])
    by_name = {r["player_name"]: r for r in rows}
    assert len(rows) == 2 and "Comp Pick" in by_name        # the isPass slot is skipped
    assert by_name["Paul Skenes"]["team_abbr"] == "PIT"
    assert by_name["Paul Skenes"]["native_player_id"] == "5010764"
    assert by_name["Paul Skenes"]["position"] == "P"
    assert by_name["Comp Pick"]["round"] is None            # non-numeric round -> NULL
