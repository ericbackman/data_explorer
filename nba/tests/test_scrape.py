"""Tests for the refetch policy and season ingest — in-memory DB, no network."""

import pandas as pd
import pytest

from nba import db, scrape

DAL, DET, OKC, HOU, MIA, CHI = (
    1610612742, 1610612765, 1610612760, 1610612745, 1610612748, 1610612741)


def _side(gid, date, abbr, team_id, matchup, pts):
    return {"GAME_ID": gid, "TEAM_ID": team_id, "TEAM_ABBREVIATION": abbr,
            "TEAM_NAME": abbr, "GAME_DATE": date, "MATCHUP": matchup,
            "WL": "W", "PTS": pts}


# nba_api column names. 0022500147 is the real Mexico City game (both rows "@");
# Playoffs is empty, the shape PlayIn returns for seasons before 2020-21.
LOGS = {
    "Regular Season": [
        _side("0022500001", "2025-10-21", "OKC", OKC, "OKC vs. HOU", 125),
        _side("0022500001", "2025-10-21", "HOU", HOU, "HOU @ OKC", 124),
        _side("0022500147", "2025-11-01", "DAL", DAL, "DAL @ DET", 116),
        _side("0022500147", "2025-11-01", "DET", DET, "DET @ DAL", 121),
    ],
    "PlayIn": [
        _side("0052500101", "2026-04-14", "MIA", MIA, "MIA vs. CHI", 110),
        _side("0052500101", "2026-04-14", "CHI", CHI, "CHI @ MIA", 100),
    ],
    "Playoffs": [],
}


class _FakeClient:
    def __init__(self, designations):
        self.designations = designations
        self.summaries = []

    def league_game_log(self, season, season_type, player_or_team, use_cache=True):
        rows = [dict(r) for r in LOGS[season_type]]
        if player_or_team == "P":
            for r in rows:
                r["PLAYER_ID"], r["PLAYER_NAME"] = r["TEAM_ID"] * 10, f"{r['TEAM_ABBREVIATION']} guard"
        return pd.DataFrame(rows)

    def designated_teams(self, game_id):
        self.summaries.append(game_id)
        return self.designations[game_id]


def _mem_db():
    return db.connect(":memory:")


def test_force_refetches_everything():
    conn = _mem_db()
    req = ["2022-23", "2023-24", "2024-25", "2025-26"]
    assert scrape.seasons_to_refetch(conn, req, "2025-26", force=True) == req


def test_first_run_fetches_all_requested():
    conn = _mem_db()
    req = ["2023-24", "2024-25", "2025-26"]
    assert scrape.seasons_to_refetch(conn, req, "2025-26", force=False) == req


def test_skips_loaded_old_seasons_but_always_keeps_recent_window():
    conn = _mem_db()
    # Everything except the live season is already loaded.
    db.load_games(conn, [
        {"game_id": "g1", "season": "2022-23"},
        {"game_id": "g2", "season": "2023-24"},
        {"game_id": "g3", "season": "2024-25"},
    ])
    req = ["2022-23", "2023-24", "2024-25", "2025-26"]
    out = scrape.seasons_to_refetch(conn, req, "2025-26", force=False)
    # live season (new) + 2024-25 (recent safety net) refetched; older skipped.
    assert out == ["2024-25", "2025-26"]


def test_ingest_season_stores_play_in_and_neutral_site_games():
    conn = _mem_db()
    client = _FakeClient({"0022500147": (DET, DAL)})
    counts = scrape.ingest_season(client, conn, "2025-26", "2025-26")
    assert counts == {"player_rows": 6, "team_rows": 6, "games": 3, "neutral_site": 1}
    assert client.summaries == ["0022500147"]   # only the game the logs could not orient
    assert conn.execute(
        "SELECT home_team_id, away_team_id, home_pts FROM games WHERE game_id='0022500147'"
    ).fetchone() == (DET, DAL, 121)
    assert conn.execute(
        "SELECT season_type, COUNT(*) FROM games GROUP BY 1 ORDER BY 1").fetchall() == [
        ("PlayIn", 1), ("Regular Season", 2)]


def test_a_failed_season_rolls_back_every_season_type():
    conn = _mem_db()
    with pytest.raises(KeyError):
        scrape.ingest_season(_FakeClient({}), conn, "2025-26", "2025-26")
    for table in ("games", "team_game", "player_game"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
