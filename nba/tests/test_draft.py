"""Pure-function tests for draft parsing — no network, no DB.
Run: python -m pytest nba/tests/test_draft.py
"""

import pandas as pd

from nba import parse

_EXPECTED_COLS = {
    "season", "overall_pick", "round_number", "round_pick", "person_id",
    "player_name", "team_id", "team_city", "team_name", "team_abbreviation",
    "organization", "organization_type", "draft_type",
}


def _raw(**over):
    base = {
        "PERSON_ID": 2544, "PLAYER_NAME": "LeBron James", "SEASON": 2003,
        "ROUND_NUMBER": 1, "ROUND_PICK": 1, "OVERALL_PICK": 1, "DRAFT_TYPE": "Draft",
        "TEAM_ID": 1610612739, "TEAM_CITY": "Cleveland", "TEAM_NAME": "Cavaliers",
        "TEAM_ABBREVIATION": "CLE", "ORGANIZATION": "Saint Vincent-Saint Mary",
        "ORGANIZATION_TYPE": "High School", "PLAYER_PROFILE_FLAG": 1,
    }
    base.update(over)
    return base


def test_parse_draft_maps_a_pick():
    [row] = parse.parse_draft(pd.DataFrame([_raw()]))
    assert row["season"] == 2003
    assert row["overall_pick"] == 1
    assert row["player_name"] == "LeBron James"
    assert row["team_city"] == "Cleveland"
    assert row["team_name"] == "Cavaliers"
    assert row["organization"] == "Saint Vincent-Saint Mary"
    # projected to exactly the storage columns (no stray keys)
    assert set(row) == _EXPECTED_COLS


def test_parse_draft_skips_rows_without_a_pick_slot():
    # A forfeited/placeholder row with no OVERALL_PICK must not become a null-keyed row.
    df = pd.DataFrame([_raw(), _raw(OVERALL_PICK=None, PLAYER_NAME="(forfeited)")])
    rows = parse.parse_draft(df)
    assert len(rows) == 1
    assert rows[0]["player_name"] == "LeBron James"


def test_parse_draft_coerces_string_numerics():
    # nba_api sometimes returns numbers as strings depending on the year.
    [row] = parse.parse_draft(pd.DataFrame([_raw(SEASON="2003", OVERALL_PICK="5")]))
    assert row["season"] == 2003 and row["overall_pick"] == 5
    assert isinstance(row["season"], int) and isinstance(row["overall_pick"], int)


def test_parse_draft_skips_uncoercible_season():
    rows = parse.parse_draft(pd.DataFrame([_raw(SEASON="n/a")]))
    assert rows == []
