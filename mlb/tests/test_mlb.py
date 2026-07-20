"""Unit tests for the pure MLB draft-backbone logic — no network, no DB.

Fixtures below are trimmed real-shape excerpts (verified against live
MLB StatsAPI responses for 1965/1988/2009) rather than invented shapes.
"""

from mlb import career_value, draft_api, person_map


# ── draft_api.parse_pick / parse_draft_year ─────────────────────────────────

STRASBURG_PICK = {
    "bisPlayerId": 335115,
    "pickNumber": 1,
    "roundPickNumber": 1,
    "school": {"name": "San Diego State", "schoolClass": "JR"},
    "person": {
        "id": 544931,
        "fullName": "Stephen Strasburg",
        "birthDate": "1988-07-20",
        "primaryPosition": {"abbreviation": "P"},
    },
    "team": {"id": 120, "name": "Washington Nationals"},
    "draftType": {"code": "JR"},
    "isDrafted": True,
    "isPass": False,
}


def test_parse_pick_flattens_nested_fields():
    rec = draft_api.parse_pick(STRASBURG_PICK, "2009", "1", round_sort=1)
    assert rec["year"] == 2009
    assert rec["overall_pick"] == 1
    assert rec["round"] == "1"
    assert rec["round_sort"] == 1
    assert rec["mlbam_id"] == 544931
    assert rec["player_name"] == "Stephen Strasburg"
    assert rec["team_id"] == 120
    assert rec["team_name"] == "Washington Nationals"
    assert rec["position"] == "P"
    assert rec["school_name"] == "San Diego State"
    assert rec["is_pass"] == 0


def test_parse_pick_handles_missing_person_defensively():
    # No year sampled has a pass/no-person pick, but the parser must not
    # crash if a future draft ever has one.
    passed_pick = {"pickNumber": 45, "roundPickNumber": 3, "isPass": True, "isDrafted": False}
    rec = draft_api.parse_pick(passed_pick, "1975", "2", round_sort=2)
    assert rec["mlbam_id"] is None
    assert rec["player_name"] is None
    assert rec["is_pass"] == 1


def test_parse_draft_year_round_sort_interleaves_comp_balance_rounds():
    """round_sort must follow the API's own pick-ordered round-group
    sequence — round '1', then 'C-A' (competitive balance), then '2' — not
    a numeric guess at the label."""
    raw = {
        "drafts": {
            "draftYear": "2009",
            "rounds": [
                {"round": "1", "picks": [dict(STRASBURG_PICK, pickNumber=1, roundPickNumber=1)]},
                {"round": "C-A", "picks": [dict(STRASBURG_PICK, pickNumber=33, roundPickNumber=1,
                                                 person={"id": 1, "fullName": "X", "birthDate": None,
                                                         "primaryPosition": {}})]},
                {"round": "2", "picks": [dict(STRASBURG_PICK, pickNumber=50, roundPickNumber=1,
                                              person={"id": 2, "fullName": "Y", "birthDate": None,
                                                      "primaryPosition": {}})]},
            ],
        }
    }
    records = draft_api.parse_draft_year(raw)
    assert [r["round"] for r in records] == ["1", "C-A", "2"]
    assert [r["round_sort"] for r in records] == [1, 2, 3]
    assert [r["overall_pick"] for r in records] == [1, 33, 50]


# ── career_value.compute_career_value ───────────────────────────────────────

def test_career_value_takes_max_not_sum():
    # A two-way-ish player: 400 batting games, 100 pitching games. v0 takes
    # the max (400), it does not sum to 500 — that would double-count a
    # single career across two disjoint tables.
    batting = [{"playerID": "twoway01", "G": 250}, {"playerID": "twoway01", "G": 150}]
    pitching = [{"playerID": "twoway01", "G": 60}, {"playerID": "twoway01", "G": 40}]
    values = career_value.compute_career_value(batting, pitching)
    assert values["twoway01"] == {"batting_g": 400, "pitching_g": 100, "value_games": 400}


def test_career_value_pure_pitcher_and_pure_hitter():
    batting = [{"playerID": "hitter01", "G": 1912}]
    pitching = [{"playerID": "pitcher01", "G": 807}]
    values = career_value.compute_career_value(batting, pitching)
    assert values["hitter01"]["value_games"] == 1912
    assert values["hitter01"]["pitching_g"] == 0
    assert values["pitcher01"]["value_games"] == 807


def test_career_value_missing_games_treated_as_zero_not_dropped():
    batting = [{"playerID": "p1", "G": ""}]  # empty CSV cell, not a missing row
    values = career_value.compute_career_value(batting, [])
    assert values["p1"]["batting_g"] == 0


# ── person_map: register join ───────────────────────────────────────────────

def test_register_join_prefers_bbref_falls_back_to_retro():
    people = [
        {"playerID": "piazzmi01", "bbrefID": "piazzmi01", "retroID": "piazm001"},
        {"playerID": "monday01", "bbrefID": "mondar01", "retroID": None},
    ]
    bbref_to_id, retro_to_id = person_map.index_people_by_bbref_retro(people)

    register_rows = [
        {"key_mlbam": "120536", "key_bbref": "piazzmi01", "key_retro": "piazm001"},  # bbref match
        {"key_mlbam": "119246", "key_bbref": "", "key_retro": None},  # no retro id either -> unmapped
        {"key_mlbam": "", "key_bbref": "someoneelse", "key_retro": ""},  # no mlbam -> skipped
    ]
    mapping = person_map.map_register_to_lahman(register_rows, bbref_to_id, retro_to_id)

    assert mapping[120536] == {"player_id": "piazzmi01", "match_method": "register", "matched_via": "bbref"}
    assert 119246 not in mapping  # neither key resolved -> correctly left unmapped, not guessed
    assert len(mapping) == 1


def test_register_join_falls_back_to_retro_when_bbref_missing():
    people = [{"playerID": "monday01", "bbrefID": None, "retroID": "mondr001"}]
    bbref_to_id, retro_to_id = person_map.index_people_by_bbref_retro(people)
    register_rows = [{"key_mlbam": "119246", "key_bbref": "", "key_retro": "mondr001"}]
    mapping = person_map.map_register_to_lahman(register_rows, bbref_to_id, retro_to_id)
    assert mapping[119246] == {"player_id": "monday01", "match_method": "register", "matched_via": "retro"}


# ── person_map: name + birth-year fallback ──────────────────────────────────

def test_name_birthyear_fallback_matches_unambiguous_case():
    people = [{"playerID": "monday01", "nameFirst": "Rick", "nameLast": "Monday", "birthYear": "1945"}]
    index = person_map.index_people_by_name_birthyear(people)
    unmapped = [{"mlbam_id": 119246, "player_name": "Rick Monday", "birth_date": "1945-11-20"}]
    mapping = person_map.fallback_name_birthyear_match(unmapped, index)
    assert mapping[119246]["player_id"] == "monday01"
    assert mapping[119246]["match_method"] == "name_birthyear"


def test_name_birthyear_fallback_misses_multiword_first_names():
    # Known limitation, documented rather than papered over: a naive
    # first-token/last-token split can't reconcile "J. D." (Lahman) against
    # "J.D." or "J. D." (MLBAM fullName) — this is exactly why the fallback
    # is conservative (skip, don't guess) rather than attempting fuzzy
    # tokenization.
    people = [{"playerID": "drewjd01", "nameFirst": "J. D.", "nameLast": "Drew", "birthYear": "1973"}]
    index = person_map.index_people_by_name_birthyear(people)
    unmapped = [{"mlbam_id": 136770, "player_name": "J. D. Drew", "birth_date": "1973-11-16"}]
    mapping = person_map.fallback_name_birthyear_match(unmapped, index)
    assert 136770 not in mapping


def test_name_birthyear_fallback_skips_ambiguous_matches():
    # Two different real players sharing a first/last/birth-year key —
    # the fallback must refuse to guess between them.
    people = [
        {"playerID": "smithch01", "nameFirst": "Chris", "nameLast": "Smith", "birthYear": "1985"},
        {"playerID": "smithch02", "nameFirst": "Chris", "nameLast": "Smith", "birthYear": "1985"},
    ]
    index = person_map.index_people_by_name_birthyear(people)
    unmapped = [{"mlbam_id": 999, "player_name": "Chris Smith", "birth_date": "1985-04-01"}]
    mapping = person_map.fallback_name_birthyear_match(unmapped, index)
    assert 999 not in mapping


def test_name_birthyear_fallback_skips_missing_birth_date():
    index = person_map.index_people_by_name_birthyear(
        [{"playerID": "x", "nameFirst": "A", "nameLast": "B", "birthYear": "1990"}]
    )
    unmapped = [{"mlbam_id": 1, "player_name": "A B", "birth_date": None}]
    mapping = person_map.fallback_name_birthyear_match(unmapped, index)
    assert mapping == {}
