"""Tests for the refetch policy — uses an in-memory DB, no network."""

from nba import db, scrape


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
