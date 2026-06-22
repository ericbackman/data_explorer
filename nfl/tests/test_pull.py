"""Pure-logic tests for the NFL pull (no network)."""

from nfl import pull


def test_parse_seasons_range():
    assert pull.parse_seasons("2010-2012") == [2010, 2011, 2012]
    assert pull.parse_seasons("2023-2023") == [2023]


def test_parse_seasons_clamped_to_1999_floor():
    out = pull.parse_seasons("1990-2001")   # nflverse has nothing before 1999
    assert out[0] == 1999 and out[-1] == 2001


def test_dataset_registry_covers_box_and_pbp():
    assert pull.DATASETS["schedules"][0] == "games"
    assert pull.DATASETS["player_stats"][0] == "player_game"
    assert pull.DATASETS["pbp"][0] == "play_by_play"


def test_load_season_reconciles_drifting_columns_and_is_idempotent():
    import sqlite3
    import pandas as pd
    conn = sqlite3.connect(":memory:")
    pull.load_season(conn, "t", pd.DataFrame({"season": [2023], "a": [1]}), 2023)
    # 2024 adds a new column 'b' the table doesn't have yet
    pull.load_season(conn, "t", pd.DataFrame({"season": [2024], "a": [2], "b": [9]}), 2024)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(t)")]
    assert "b" in cols
    assert conn.execute("SELECT b FROM t WHERE season=2023").fetchone()[0] is None   # backfilled NULL
    assert conn.execute("SELECT b FROM t WHERE season=2024").fetchone()[0] == 9
    pull.load_season(conn, "t", pd.DataFrame({"season": [2024], "a": [2], "b": [9]}), 2024)  # re-load
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2                  # idempotent
