"""Play-by-play enrichment — the per-game tier (PlayByPlayV2, 1996-97 onward).

Unlike box scores, there's no bulk endpoint: one request per game (~37k games,
~16M events, a few GB). So this is built to run incrementally — newest games
first, resumable (skips game_ids already loaded), batched commits, and per-game
resilient (one bad game logs and is skipped, never aborts the run).

    python -m nba.playbyplay --seasons 2024-2026            # recent first
    python -m nba.playbyplay --seasons 2024-2026 --limit 50 # a capped test slice
    python -m nba.playbyplay --seasons 1996-2024            # backfill the archive
"""

from __future__ import annotations

import argparse
import logging
import math
import pathlib
import sqlite3

import pandas as pd

from nba.client import NBAClient

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent
DB_PATH = PKG_DIR / "data" / "nba.db"
CACHE_DIR = PKG_DIR / "data" / "cache"     # only used by NBAClient bookkeeping
PBP_EARLIEST_YEAR = 1996                    # PlayByPlayV2 has no data before 1996-97

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS play_by_play (
    game_id TEXT NOT NULL,
    action_number INTEGER NOT NULL,
    period INTEGER,
    clock TEXT,                  -- ISO duration as returned, e.g. "PT11M44.00S"
    team_id INTEGER, team_tricode TEXT,
    person_id INTEGER, player_name TEXT,
    action_type TEXT, sub_type TEXT,   -- e.g. "2pt"/"Jump Shot", "Rebound"/"offensive"
    description TEXT,
    shot_result TEXT, is_field_goal INTEGER, shot_value INTEGER, shot_distance INTEGER,
    shot_x INTEGER, shot_y INTEGER,    -- xLegacy/yLegacy court coords (shot charts)
    score_home INTEGER, score_away INTEGER, points_total INTEGER,
    location TEXT
    -- no per-event PK: V3 reuses actionNumber for linked events (block shares its
    -- number with the missed shot). Idempotency is per game (delete-then-insert).
);
CREATE INDEX IF NOT EXISTS idx_pbp_game   ON play_by_play(game_id, action_number);
CREATE INDEX IF NOT EXISTS idx_pbp_person ON play_by_play(person_id);
CREATE INDEX IF NOT EXISTS idx_pbp_action ON play_by_play(action_type);
"""

COLS = ["game_id", "action_number", "period", "clock", "team_id", "team_tricode",
        "person_id", "player_name", "action_type", "sub_type", "description",
        "shot_result", "is_field_goal", "shot_value", "shot_distance",
        "shot_x", "shot_y", "score_home", "score_away", "points_total", "location"]


def _int(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _txt(v):
    """Empty string -> None (V3 uses '' for non-applicable fields)."""
    return v or None


def parse_pbp(df: pd.DataFrame, game_id: str) -> list[dict]:
    gid = str(game_id).zfill(10)
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append({
            "game_id": gid,
            "action_number": _int(r.get("actionNumber")),
            "period": _int(r.get("period")),
            "clock": _txt(r.get("clock")),
            "team_id": _int(r.get("teamId")),
            "team_tricode": _txt(r.get("teamTricode")),
            "person_id": _int(r.get("personId")),
            "player_name": _txt(r.get("playerName")),
            "action_type": _txt(r.get("actionType")),
            "sub_type": _txt(r.get("subType")),
            "description": _txt(r.get("description")),
            "shot_result": _txt(r.get("shotResult")),
            "is_field_goal": _int(r.get("isFieldGoal")),
            "shot_value": _int(r.get("shotValue")),
            "shot_distance": _int(r.get("shotDistance")),
            "shot_x": _int(r.get("xLegacy")),
            "shot_y": _int(r.get("yLegacy")),
            "score_home": _int(r.get("scoreHome")),
            "score_away": _int(r.get("scoreAway")),
            "points_total": _int(r.get("pointsTotal")),
            "location": _txt(r.get("location")),
        })
    return rows


def load(conn: sqlite3.Connection, game_id: str, rows: list[dict]) -> int:
    """Replace all rows for one game (delete-then-insert). There's no per-event
    natural key (V3 reuses actionNumber for linked events), so idempotency is per
    game: re-fetching a game cleanly replaces its rows and never drops events."""
    conn.execute("DELETE FROM play_by_play WHERE game_id = ?", (str(game_id).zfill(10),))
    if rows:
        placeholders = ",".join("?" * len(COLS))
        conn.executemany(
            f"INSERT INTO play_by_play ({','.join(COLS)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in COLS) for r in rows],
        )
    return len(rows)


def games_to_fetch(conn: sqlite3.Connection, seasons: list[str], limit: int | None) -> list[str]:
    """game_ids in the requested seasons that have no PBP yet, newest first."""
    loaded = {r[0] for r in conn.execute("SELECT DISTINCT game_id FROM play_by_play")}
    qmarks = ",".join("?" * len(seasons))
    todo = [r[0] for r in conn.execute(
        f"SELECT game_id FROM games WHERE season IN ({qmarks}) "
        f"ORDER BY game_date DESC, game_id DESC", seasons)
        if r[0] not in loaded]
    return todo[:limit] if limit else todo


def _season_str(y: int) -> str:
    return f"{y}-{str(y + 1)[-2:]}"


def parse_seasons_arg(value: str) -> list[str]:
    """'2024-2026' -> ['2025-26','2024-25'] (clamped to PBP's 1996 floor, newest first)."""
    start_str, _, end_str = value.partition("-")
    start = max(int(start_str), PBP_EARLIEST_YEAR)
    end = int(end_str)
    if int(start_str) < PBP_EARLIEST_YEAR:
        log.warning("PBP only exists from %d-97; clamping start to %d",
                    PBP_EARLIEST_YEAR, PBP_EARLIEST_YEAR)
    return [_season_str(y) for y in range(end - 1, start - 1, -1)]  # newest first


def main() -> None:
    ap = argparse.ArgumentParser(description="Enrich nba.db with play-by-play (PlayByPlayV2)")
    ap.add_argument("--seasons", default="2024-2026", help="START-END by start year (default 2024-2026)")
    ap.add_argument("--limit", type=int, default=None, help="cap games this run (for test slices)")
    ap.add_argument("--batch-size", type=int, default=25, help="commit every N games")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    seasons = parse_seasons_arg(args.seasons)
    todo = games_to_fetch(conn, seasons, args.limit)
    log.info("seasons %s — %d games need play-by-play (newest first)", seasons, len(todo))

    if args.dry_run or not todo:
        log.info("ETA ~%.0f min at 0.7s/game", len(todo) * 0.7 / 60)
        conn.close()
        return

    client = NBAClient(CACHE_DIR)
    events = done = failed = 0
    for i, gid in enumerate(todo, 1):
        try:
            rows = parse_pbp(client.play_by_play(gid), gid)
            events += load(conn, gid, rows)
            done += 1
        except Exception as e:  # one bad game must not abort the backfill
            log.error("game %s failed: %s — skipping", gid, e)
            failed += 1
        if i % args.batch_size == 0:
            conn.commit()
            log.info("  [%d/%d] %d games, %d events loaded", i, len(todo), done, events)

    conn.commit()
    conn.close()
    log.info("done: %d games, %d events (%d failed)", done, events, failed)


if __name__ == "__main__":
    main()
