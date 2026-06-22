"""Pull NFL data from nflverse (nflreadpy) into a local SQLite DB — free + bulk.

nflverse publishes pre-compiled per-season files (schedules, player/team game
stats, ~370-col play-by-play) on GitHub, so this is a bulk download, not a
per-game scrape. nflreadpy caches downloads, so re-runs are free. Coverage floor
is 1999. Idempotent + resumable: each season is delete-then-insert.

    python -m nfl.pull --datasets schedules,player_stats,team_stats   # box scores
    python -m nfl.pull --datasets pbp                                 # play-by-play
    python -m nfl.pull --datasets schedules --seasons 2010-2025
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sqlite3

import nflreadpy as nfl

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent
DB_PATH = PKG_DIR / "data" / "nfl.db"
EARLIEST_SEASON = 1999  # nflverse structured-data floor

# dataset name -> (table, nflreadpy loader, columns to index)
DATASETS = {
    "schedules":    ("games",         nfl.load_schedules,    ["season", "game_id"]),
    "player_stats": ("player_game",   nfl.load_player_stats, ["season", "player_id", "game_id"]),
    "team_stats":   ("team_game",     nfl.load_team_stats,   ["season", "team", "week"]),
    "pbp":          ("play_by_play",  nfl.load_pbp,          ["season", "game_id", "play_id"]),
}


def parse_seasons(value: str) -> list[int]:
    """'1999-2025' -> [1999..2025], clamped to the nflverse 1999 floor."""
    start_str, _, end_str = value.partition("-")
    start = max(int(start_str), EARLIEST_SEASON)
    if int(start_str) < EARLIEST_SEASON:
        log.warning("nflverse data starts %d; clamping start", EARLIEST_SEASON)
    return list(range(start, int(end_str) + 1))


def load_season(conn: sqlite3.Connection, table: str, df, season: int) -> int:
    """Delete-then-insert one season, reconciling column drift across seasons.

    nflverse column sets aren't identical year to year (e.g. game_id appears in
    some player_stats seasons but not others), so a naive per-season append fails.
    We evolve the table to the union of columns (ALTER ADD), then align each
    season's frame to it (missing columns -> NULL). Idempotent per season."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        df.to_sql(table, conn, if_exists="append", index=False)  # creates the table
        conn.commit()
        return len(df)

    tbl_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    for c in df.columns:
        if c not in tbl_cols:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN "{c}"')
            tbl_cols.append(c)
    conn.execute(f"DELETE FROM {table} WHERE season = ?", (int(season),))
    df.reindex(columns=tbl_cols).to_sql(table, conn, if_exists="append", index=False)
    conn.commit()
    return len(df)


def create_indexes(conn: sqlite3.Connection, table: str, cols: list[str]) -> None:
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for c in cols:
        if c in existing:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{c} ON {table}({c})")
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull free nflverse data into a local SQLite DB")
    ap.add_argument("--datasets", default="schedules,player_stats,team_stats",
                    help="comma list of: " + ", ".join(DATASETS))
    ap.add_argument("--seasons", default="1999-2025", help="START-END (default 1999-2025)")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    seasons = parse_seasons(args.seasons)
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)

    for name in [d.strip() for d in args.datasets.split(",") if d.strip()]:
        if name not in DATASETS:
            raise SystemExit(f"unknown dataset {name!r}; choices: {list(DATASETS)}")
        table, loader, idx = DATASETS[name]
        total = 0
        for season in seasons:
            df = loader(seasons=[season]).to_pandas()   # nflreadpy -> polars -> pandas
            if df.empty:
                log.warning("%s %d: no data", table, season)
                continue
            total += load_season(conn, table, df, season)
            log.info("%s %d: %d rows", table, season, len(df))
        create_indexes(conn, table, idx)
        log.info("== %s: %d rows across %d seasons ==", table, total, len(seasons))

    conn.close()


if __name__ == "__main__":
    main()
