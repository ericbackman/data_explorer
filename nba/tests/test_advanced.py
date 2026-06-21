"""Advanced-view formula tests against a hand-computed synthetic game (no network)."""

from nba import advanced, db


def _insert(conn, table, **k):
    cols = ",".join(k)
    ph = ",".join("?" * len(k))
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", tuple(k.values()))


def _fixture():
    conn = db.connect(":memory:")
    _insert(conn, "team_game", game_id="G", team_id=1, season="2024-25",
            season_type="Regular Season", game_date="2025-01-01", matchup="A vs. B", wl="W",
            min=240, pts=105, fgm=40, fga=80, fg3m=10, ftm=15, fta=20,
            oreb=10, dreb=30, reb=40, tov=12)
    _insert(conn, "team_game", game_id="G", team_id=2, season="2024-25",
            season_type="Regular Season", game_date="2025-01-01", matchup="B @ A", wl="L",
            min=240, pts=98, fgm=38, fga=85, fg3m=8, ftm=14, fta=18,
            oreb=12, dreb=28, reb=40, tov=14)
    _insert(conn, "player_game", game_id="G", player_id=99, team_id=1, season="2024-25",
            season_type="Regular Season", game_date="2025-01-01",
            min=36, pts=30, fgm=10, fga=20, fg3m=2, ftm=8, fta=10,
            oreb=2, dreb=6, reb=8, ast=5, stl=2, blk=1, tov=3, pf=2)
    advanced.create_views(conn)
    return conn


def test_team_pace_ratings_efg():
    conn = _fixture()
    pace, ortg, drtg, efg = conn.execute(
        "SELECT pace, off_rtg, def_rtg, efg_pct FROM team_advanced WHERE team_id=1").fetchone()
    assert abs(pace - 90.3) < 0.5      # 0.5*(possA+possB), both teams 240 min
    assert abs(ortg - 116.3) < 0.7     # 100 * 105 / poss
    assert abs(drtg - 108.5) < 0.7     # 100 * 98 / poss
    assert abs(efg - 0.563) < 0.002    # (40 + 0.5*10) / 80


def test_player_ts_usage_gamescore():
    conn = _fixture()
    ts, efg, usg, gs = conn.execute(
        "SELECT ts_pct, efg_pct, usg_pct, game_score FROM player_advanced WHERE player_id=99").fetchone()
    assert abs(ts - 0.615) < 0.002     # 30 / (2*(20 + 0.44*10))
    assert abs(efg - 0.55) < 0.002     # (10 + 0.5*2) / 20
    assert abs(usg - 36.2) < 0.5       # 100*((20+4.4+3)*48) / (36*(80+8.8+12))
    assert abs(gs - 24.8) < 0.2        # Hollinger game score


def test_early_era_usage_is_null_without_turnovers():
    # A pre-1973 line has NULL tov -> usage/game_score must be NULL, not a wrong number.
    conn = db.connect(":memory:")
    _insert(conn, "team_game", game_id="H", team_id=1, season="1965-66",
            season_type="Regular Season", min=240, pts=110, fgm=44, fga=95, fta=30, ftm=22,
            oreb=15, dreb=40, reb=55)
    _insert(conn, "team_game", game_id="H", team_id=2, season="1965-66",
            season_type="Regular Season", min=240, pts=100, fgm=40, fga=92, fta=26, ftm=20,
            oreb=14, dreb=38, reb=52)
    _insert(conn, "player_game", game_id="H", player_id=1, team_id=1, season="1965-66",
            season_type="Regular Season", min=40, pts=35, fgm=14, fga=28, fta=9, ftm=7,
            reb=20)  # no tov/stl/blk in this era
    advanced.create_views(conn)
    ts, usg, gs = conn.execute(
        "SELECT ts_pct, usg_pct, game_score FROM player_advanced WHERE player_id=1").fetchone()
    assert ts is not None              # TS% needs only pts/fga/fta -> computable
    assert usg is None and gs is None  # need turnovers -> correctly NULL, not fabricated
