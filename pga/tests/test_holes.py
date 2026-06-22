"""Unit tests for the per-hole scoreboard parser."""
from pga.parse import parse_event_holes


def _hole(period, value, score_type):
    return {"period": period, "value": value, "scoreType": {"displayValue": score_type}}


def _event():
    """One event, 2 players, 1 round, 3 holes. Par derives as strokes - to_par:
    h1 par 4, h2 par 5 (birdie), h3 par 4 (bogey)."""
    holes = [_hole(1, 4, "E"), _hole(2, 4, "-1"), _hole(3, 5, "+1")]
    competitor = lambda pid: {"athlete": {"id": pid},
                              "linescores": [{"period": 1, "value": 13, "linescores": holes}]}
    return {"id": "555", "competitions": [{"competitors": [competitor("1"), competitor("2")]}]}


def test_parse_event_holes_par_derivation():
    event_holes, hole_scores = parse_event_holes(_event())
    pars = {h["hole_num"]: h["par"] for h in event_holes}
    assert pars == {1: 4, 2: 5, 3: 4}
    # 2 players x 3 holes
    assert len(hole_scores) == 6
    h2 = next(h for h in hole_scores if h["player_id"] == 1 and h["hole_num"] == 2)
    assert h2["strokes"] == 4 and h2["to_par"] == -1


def test_parse_event_holes_skips_unplayed_and_teams():
    # a 0-stroke (unplayed) hole is dropped
    ev = {"id": "1", "competitions": [{"competitors": [
        {"athlete": {"id": "9"}, "linescores": [{"period": 1, "value": 0,
         "linescores": [{"period": 1, "value": 0, "scoreType": {"displayValue": "E"}}]}]}]}]}
    _, scores = parse_event_holes(ev)
    assert scores == []
    # nested-list competitions (team/match-play) -> empty, no crash
    assert parse_event_holes({"id": "2", "competitions": [[{"x": 1}]]}) == ([], [])
