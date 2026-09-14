"""Pure-logic tests for the NFL pull (no network)."""

import pytest

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


def test_load_season_quotes_a_drifted_column_name_it_did_not_choose():
    import sqlite3
    import pandas as pd
    conn = sqlite3.connect(":memory:")
    pull.load_season(conn, "t", pd.DataFrame({"season": [2023]}), 2023)
    # Unescaped, this name would end the identifier early and splice SQL into the ALTER.
    odd = 'x" INTEGER, "y'
    pull.load_season(conn, "t", pd.DataFrame({"season": [2024], odd: [7]}), 2024)
    assert [r[1] for r in conn.execute("PRAGMA table_info(t)")] == ["season", odd]
    assert conn.execute(
        f"SELECT {pull.quote_ident(odd)} FROM t WHERE season=2024").fetchone()[0] == 7


def test_quote_ident_doubles_quotes_and_refuses_nul():
    assert pull.quote_ident('a"b') == '"a""b"'
    with pytest.raises(ValueError, match="NUL"):
        pull.quote_ident("a\x00b")
