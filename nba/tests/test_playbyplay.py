"""Play-by-play parse + resumability tests (no network)."""

import pandas as pd

from nba import db, playbyplay


def test_seasons_newest_first_and_clamped_to_1996():
    assert playbyplay.parse_seasons_arg("2024-2026") == ["2025-26", "2024-25"]
    out = playbyplay.parse_seasons_arg("1990-1998")   # PBP floor is 1996-97
    assert out[0] == "1997-98" and out[-1] == "1996-97"


def test_parse_pbp_maps_v3_fields_and_nulls():
    df = pd.DataFrame([{
        "gameId": "0042400407", "actionNumber": 7, "period": 1, "clock": "PT11M44.00S",
        "teamId": 1610612754, "teamTricode": "IND", "personId": 1629614,
        "playerName": "Nembhard", "actionType": "Made Shot", "subType": "Jump Shot",
        "description": "Nembhard 14' Jump Shot", "shotResult": "Made", "isFieldGoal": 1,
        "shotValue": 2, "shotDistance": 14, "xLegacy": 91, "yLegacy": 106,
        "scoreHome": 0, "scoreAway": 2, "pointsTotal": 2, "location": "v",
    }, {
        "gameId": "0042400407", "actionNumber": 2, "period": 1, "clock": "PT12M00.00S",
        "teamId": 0, "teamTricode": "", "personId": 0, "playerName": "",
        "actionType": "period", "subType": "", "description": "Period Start",
        "shotResult": "", "isFieldGoal": 0, "shotValue": 0, "shotDistance": 0,
        "xLegacy": 0, "yLegacy": 0, "scoreHome": 0, "scoreAway": 0, "pointsTotal": 0,
        "location": "",
    }])
    shot, nonplay = playbyplay.parse_pbp(df, "42400407")
    assert shot["game_id"] == "0042400407" and shot["action_number"] == 7
    assert shot["player_name"] == "Nembhard" and shot["shot_result"] == "Made"
    assert shot["shot_distance"] == 14 and shot["shot_x"] == 91
    assert nonplay["team_tricode"] is None     # "" -> None
    assert nonplay["player_name"] is None and nonplay["sub_type"] is None


def test_games_to_fetch_skips_loaded_and_orders_newest_first():
    conn = db.connect(":memory:")
    conn.executescript(playbyplay.SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO games (game_id, season, game_date) VALUES (?,?,?)",
        [("G1", "2024-25", "2024-10-22"), ("G2", "2024-25", "2025-01-15"),
         ("G3", "2024-25", "2025-03-01")])
    conn.execute("INSERT INTO play_by_play (game_id, action_number) VALUES ('G2', 1)")
    conn.commit()
    assert playbyplay.games_to_fetch(conn, ["2024-25"], None) == ["G3", "G1"]
    assert playbyplay.games_to_fetch(conn, ["2024-25"], 1) == ["G3"]


def test_load_keeps_linked_events_and_is_idempotent():
    # Two rows share actionNumber 8 (a blocked shot). Both must survive, and
    # re-loading the same game must replace, not duplicate.
    conn = db.connect(":memory:")
    conn.executescript(playbyplay.SCHEMA_SQL)
    rows = [
        {"game_id": "0000000001", "action_number": 8, "action_type": "Missed Shot",
         "description": "MISS Williams 10' Step Back"},
        {"game_id": "0000000001", "action_number": 8, "action_type": "Block",
         "description": "Nesmith BLOCK"},
    ]
    playbyplay.load(conn, "1", rows)
    playbyplay.load(conn, "1", rows)  # re-run the same game
    n = conn.execute("SELECT COUNT(*) FROM play_by_play WHERE game_id='0000000001'").fetchone()[0]
    assert n == 2  # both linked events kept; re-load replaced rather than appended
