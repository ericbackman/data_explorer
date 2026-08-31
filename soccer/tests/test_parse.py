"""Parser tests against synthetic ESPN-shaped fixtures.

The fixtures mimic the real scoreboard structure (verified against the 2022 WC
final, Argentina-France) but are tiny and offline, so the suite is fast and
deterministic. cf. pga/tests/test_parse.py.
"""
from __future__ import annotations

import pytest

from soccer import parse


# A miniature two-match scoreboard: one group game, one knockout final that went
# to a penalty shootout (mirrors Argentina 3-3 France, won 4-2 on pens).
FIXTURE = {
    "events": [
        {
            "id": "100001",
            "date": "2022-11-22T13:00Z",
            "season": {"year": 2022, "slug": "group-stage"},
            "competitions": [{
                "neutralSite": True,
                "attendance": 88012,
                "venue": {"fullName": "Lusail Stadium", "address": {"city": "Lusail", "country": "Qatar"}},
                "status": {"type": {"description": "Full Time"}},
                "competitors": [
                    {"homeAway": "home", "score": "1", "winner": False,
                     "team": {"id": "202", "displayName": "Argentina", "abbreviation": "ARG", "location": "Argentina"}},
                    {"homeAway": "away", "score": "2", "winner": True,
                     "team": {"id": "370", "displayName": "Saudi Arabia", "abbreviation": "KSA", "location": "Saudi Arabia"}},
                ],
                "details": [
                    {"type": {"text": "Goal"}, "clock": {"displayValue": "10'"}, "team": {"id": "202"},
                     "scoringPlay": True, "penaltyKick": True, "ownGoal": False, "shootout": False,
                     "athletesInvolved": [{"id": "45843", "displayName": "Lionel Messi"}]},
                    {"type": {"text": "Yellow Card"}, "clock": {"displayValue": "45'+2'"}, "team": {"id": "370"},
                     "scoringPlay": False, "yellowCard": True, "redCard": False,
                     "athletesInvolved": [{"id": "999", "displayName": "Al-Bulayhi"}]},
                ],
            }],
        },
        {
            "id": "100002",
            "date": "2022-12-18T15:00Z",
            "season": {"year": 2022, "slug": "final"},
            "competitions": [{
                "neutralSite": None,
                "attendance": 88966,
                "venue": {"fullName": "Lusail Stadium", "address": {"city": "Lusail", "country": "Qatar"}},
                "status": {"type": {"description": "Full Time"}},
                "competitors": [
                    {"homeAway": "home", "score": "3", "shootoutScore": "4", "winner": True,
                     "team": {"id": "202", "displayName": "Argentina", "abbreviation": "ARG", "location": "Argentina"}},
                    {"homeAway": "away", "score": "3", "shootoutScore": "2", "winner": False,
                     "team": {"id": "478", "displayName": "France", "abbreviation": "FRA", "location": "France"}},
                ],
                "details": [
                    {"type": {"text": "Goal"}, "clock": {"displayValue": "36'"}, "team": {"id": "202"},
                     "scoringPlay": True, "penaltyKick": False, "ownGoal": False, "shootout": False,
                     "athletesInvolved": [{"id": "108223", "displayName": "Angel Di Maria"}]},
                    {"type": {"text": "Penalty - Scored"}, "clock": {"displayValue": "120'"}, "team": {"id": "202"},
                     "scoringPlay": True, "penaltyKick": True, "ownGoal": False, "shootout": True,
                     "athletesInvolved": [{"id": "45843", "displayName": "Lionel Messi"}]},
                ],
            }],
        },
    ]
}

META = parse.COMPETITIONS["fifa.world"]


def test_parse_clock():
    assert parse.parse_clock("23'") == (23, None)
    assert parse.parse_clock("45'+7'") == (45, 7)
    assert parse.parse_clock("120'") == (120, None)
    assert parse.parse_clock(None) == (None, None)
    assert parse.parse_clock("") == (None, None)


def test_classify_event_specific_flags_win():
    # shootout kick must NOT be classified as a match goal
    assert parse.classify_event({"scoringPlay": True, "penaltyKick": True, "shootout": True}) == "Shootout Penalty"
    assert parse.classify_event({"scoringPlay": True, "ownGoal": True}) == "Own Goal"
    assert parse.classify_event({"scoringPlay": True, "penaltyKick": True}) == "Penalty"
    assert parse.classify_event({"scoringPlay": True}) == "Goal"
    assert parse.classify_event({"redCard": True, "yellowCard": True}) == "Red Card"  # 2nd yellow
    assert parse.classify_event({"yellowCard": True}) == "Yellow Card"
    assert parse.classify_event({"type": {"text": "Substitution"}}) == "Substitution"


def test_parse_scoreboard_shape():
    ps = parse.parse_scoreboard(META, 2022, FIXTURE)
    assert ps.competition["slug"] == "fifa.world"
    assert ps.season["season_id"] == parse.season_id_for(1, 2022) == 12022
    assert len(ps.matches) == 2
    assert {t["name"] for t in ps.teams} == {"Argentina", "Saudi Arabia", "France"}


def test_parse_scoreboard_captures_scorer_names():
    # the cheap tier must resolve scorers to NAMES (not bare ids), so "most WC
    # goals" works without the per-match lineup pull.
    ps = parse.parse_scoreboard(META, 2022, FIXTURE)
    by_id = {p["player_id"]: p["name"] for p in ps.players}
    assert by_id[45843] == "Lionel Messi"
    assert by_id[108223] == "Angel Di Maria"


def test_parse_scoreboard_penalty_shootout_recorded():
    ps = parse.parse_scoreboard(META, 2022, FIXTURE)
    final = next(m for m in ps.matches if m["match_id"] == 100002)
    assert (final["home_score"], final["away_score"]) == (3, 3)
    assert (final["home_pens"], final["away_pens"]) == (4, 2)  # the shootout
    assert final["round"] == "final"
    assert final["city"] == "Lusail"


def test_parse_scoreboard_events_exclude_shootout_from_goals():
    ps = parse.parse_scoreboard(META, 2022, FIXTURE)
    final_events = [e for e in ps.events if e["match_id"] == 100002]
    goals = [e for e in final_events if e["type"] == "Goal"]
    shootout = [e for e in final_events if e["type"] == "Shootout Penalty"]
    assert len(goals) == 1 and goals[0]["player_id"] == 108223      # Di Maria, open play
    assert len(shootout) == 1 and shootout[0]["minute"] == 120      # Messi's shootout kick


@pytest.mark.skip(reason="learning-mode TODO: implement parse.match_outcome(), then un-skip")
def test_match_outcome_spec():
    """The spec your match_outcome() should satisfy. Un-skip once implemented.

    The penalty-shootout line encodes the design decision (FIFA: a shootout is a
    draw). If you choose the 'shootout winner wins' convention instead, change
    the last assertion to 'H' and this test with it.
    """
    assert parse.match_outcome(2, 0, None, None) == "H"
    assert parse.match_outcome(0, 2, None, None) == "A"
    assert parse.match_outcome(1, 1, None, None) == "D"
    assert parse.match_outcome(None, None, None, None) is None      # unplayed
    assert parse.match_outcome(3, 3, 4, 2) == "D"                    # shootout = draw (FIFA)
