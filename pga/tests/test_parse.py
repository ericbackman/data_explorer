"""Unit tests for the pure parsing helpers -- the bits most likely to silently
mis-handle an edge case (cuts, ties, to-par strings, majors)."""
import pytest

from pga.parse import (
    UnsupportedEventError,
    is_major,
    parse_athlete,
    parse_leaderboard,
    parse_position,
    parse_to_par,
)


def test_parse_athlete():
    raw = {"athlete": {
        "id": "9478", "fullName": "Scottie Scheffler", "age": 29,
        "displayDOB": "6/21/1996", "turnedPro": 2018, "gender": "Male",
        "birthPlace": {"city": "Dallas", "state": "Texas        ", "country": "USA"},
        "citizenship": "USA", "hand": {"displayValue": "Right"},
        "college": {"name": "Texas"}, "displayHeight": "6' 3\"", "displayWeight": "200 lbs",
    }}
    bio = parse_athlete(raw)
    assert bio["player_id"] == 9478
    assert bio["turned_pro"] == 2018
    assert bio["birth_state"] == "Texas"  # trailing spaces stripped
    assert bio["hand"] == "Right" and bio["college"] == "Texas"
    assert parse_athlete({"athlete": {"fullName": "No Id"}}) is None


def test_parse_to_par():
    assert parse_to_par("E") == 0
    assert parse_to_par("-7") == -7
    assert parse_to_par("+1") == 1
    assert parse_to_par(None) is None
    assert parse_to_par("garbage") is None


def test_parse_position():
    assert parse_position({"displayName": "1", "isTie": False}) == ("1", 1, False)
    assert parse_position({"displayName": "T6", "isTie": True}) == ("T6", 6, True)
    disp, num, tie = parse_position({"displayName": "-", "isTie": True})
    assert disp == "-" and num is None
    assert parse_position(None) == (None, None, None)


def test_is_major():
    assert is_major("Masters Tournament")
    assert is_major("PGA Championship")
    assert is_major("U.S. Open")
    assert is_major("The Open Championship")
    assert not is_major("TOUR Championship")
    assert not is_major("The American Express")


def _mini_payload():
    """A 2-player event: a finisher (won) and a cut player, exercising both shapes."""
    return {
        "events": [{
            "id": "999",
            "name": "Test Open",
            "date": "2024-01-04T00:00Z",
            "endDate": "2024-01-07T00:00Z",
            "season": {"year": 2024},
            "purse": 8000000,
            "playoffType": {"type": "aggregate"},
            "courses": [{"isPrimary": True, "name": "Test GC", "shotsToPar": 72,
                         "address": {"city": "Town", "state": "ST"}}],
            "competitions": [{"competitors": [
                {
                    "athlete": {"id": "1", "displayName": "Win Ner", "flag": {"alt": "USA"}},
                    "status": {"type": {"name": "STATUS_FINISH"},
                               "position": {"displayName": "1", "isTie": False}},
                    "score": {"value": 270, "displayValue": "-18"},
                    "earnings": 1440000,
                    "linescores": [
                        {"period": 1, "value": 65, "displayValue": "-7", "outScore": 33, "inScore": 32},
                        {"period": 2, "value": 68, "displayValue": "-4"},
                        {"period": 3, "value": 69, "displayValue": "-3"},
                        {"period": 4, "value": 68, "displayValue": "-4"},
                    ],
                },
                {
                    "athlete": {"id": "2", "displayName": "Cut Player"},
                    "status": {"type": {"name": "STATUS_CUT"},
                               "position": {"displayName": "-", "isTie": True}},
                    "score": {"value": 150, "displayValue": "+6"},
                    "earnings": 0,
                    "linescores": [
                        {"period": 1, "value": 75, "displayValue": "+3"},
                        {"period": 2, "value": 75, "displayValue": "+3"},
                    ],
                },
            ]}],
        }]
    }


def test_parse_leaderboard_shapes():
    parsed = parse_leaderboard(_mini_payload())
    t = parsed.tournament
    assert t["event_id"] == 999
    assert t["season"] == 2024
    assert t["par"] == 72 and t["city"] == "Town"
    assert t["field_size"] == 2
    assert t["winner_player_id"] == 1
    assert t["num_rounds"] == 4

    # finisher has 4 rounds, cut player 2
    by_player = {}
    for r in parsed.rounds:
        by_player.setdefault(r["player_id"], []).append(r)
    assert len(by_player[1]) == 4
    assert len(by_player[2]) == 2
    assert by_player[1][0]["out_score"] == 33

    results = {r["player_id"]: r for r in parsed.results}
    assert results[1]["made_cut"] == 1 and results[1]["position_numeric"] == 1
    assert results[2]["status"] == "cut" and results[2]["made_cut"] == 0


def test_team_event_skipped():
    """Nested list-of-sessions competitions (Presidents Cup) -> skip, not crash."""
    payload = {"events": [{"id": "1", "name": "Presidents Cup",
                           "competitions": [[{"foo": "bar"}]]}]}
    with pytest.raises(UnsupportedEventError):
        parse_leaderboard(payload)


def test_no_competition_block_skipped():
    """Old match-play events carry no competition block at all -> skip."""
    payload = {"events": [{"id": "280", "name": "WGC Match Play", "competitions": []}]}
    with pytest.raises(UnsupportedEventError):
        parse_leaderboard(payload)


def test_withdrawal_round_nulled():
    """A round with value 0 (player withdrew, didn't play) must not count as a
    real score -- regression for the Lee Hodges / 2024 Masters bug."""
    payload = _mini_payload()
    payload["events"][0]["competitions"][0]["competitors"][1]["linescores"] = [
        {"period": 1, "value": 74, "displayValue": "+2"},
        {"period": 2, "value": 77, "displayValue": "+5"},
        {"period": 3, "value": 0, "displayValue": None},  # WD placeholder
    ]
    parsed = parse_leaderboard(payload)
    wd_rounds = {r["round_num"]: r for r in parsed.rounds if r["player_id"] == 2}
    assert wd_rounds[3]["strokes"] is None
    assert wd_rounds[3]["to_par"] is None
    assert wd_rounds[1]["strokes"] == 74


def test_partial_round_nulled():
    """A mid-round WD logged as a low partial (e.g. 50 with an 11-stroke front
    nine) must be nulled -- regression for the sub-58 'phantom round' bug."""
    payload = _mini_payload()
    payload["events"][0]["competitions"][0]["competitors"][1]["linescores"] = [
        {"period": 1, "value": 69, "displayValue": "-3", "outScore": 32, "inScore": 37},
        {"period": 2, "value": 74, "displayValue": "+2", "outScore": 37, "inScore": 37},
        {"period": 3, "value": 50, "displayValue": "+2", "outScore": 11, "inScore": 39},  # partial
    ]
    parsed = parse_leaderboard(payload)
    by_round = {r["round_num"]: r for r in parsed.rounds if r["player_id"] == 2}
    assert by_round[3]["strokes"] is None      # nulled by both threshold and nine-check
    assert by_round[1]["strokes"] == 69        # complete round untouched
