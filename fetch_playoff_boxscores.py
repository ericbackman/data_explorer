"""
NBA Playoff Boxscore Enrichment
=================================
Enriches nba_playoff_comebacks.db with player and team boxscores from
BoxScoreTraditionalV3. Same schema as the regular season boxscore
enrichment, pointed at the playoff database.

Usage:
  python fetch_playoff_boxscores.py                # last season
  python fetch_playoff_boxscores.py --seasons 5    # last 5 seasons
  python fetch_playoff_boxscores.py --seasons 30   # all 30 seasons
"""

import sys
import time
import sqlite3
import argparse
import pathlib

import pandas as pd
from nba_api.stats.endpoints import boxscoretraditionalv3

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = pathlib.Path(__file__).parent / "nba_playoff_comebacks.db"
CACHE_DIR = pathlib.Path(__file__).parent / ".cache" / "playoff_boxscores"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SLEEP = 0.7


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
    person_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    family_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_boxscores (
    game_id TEXT NOT NULL,
    person_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    position TEXT,
    jersey_num TEXT,
    comment TEXT,
    minutes TEXT,
    fgm INTEGER,
    fga INTEGER,
    tpm INTEGER,
    tpa INTEGER,
    ftm INTEGER,
    fta INTEGER,
    oreb INTEGER,
    dreb INTEGER,
    reb INTEGER,
    ast INTEGER,
    stl INTEGER,
    blk INTEGER,
    tov INTEGER,
    pf INTEGER,
    pts INTEGER,
    plus_minus INTEGER,
    PRIMARY KEY (game_id, person_id)
);

CREATE TABLE IF NOT EXISTS team_boxscores (
    game_id TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    starters_bench TEXT NOT NULL,
    minutes TEXT,
    fgm INTEGER,
    fga INTEGER,
    tpm INTEGER,
    tpa INTEGER,
    ftm INTEGER,
    fta INTEGER,
    oreb INTEGER,
    dreb INTEGER,
    reb INTEGER,
    ast INTEGER,
    stl INTEGER,
    blk INTEGER,
    tov INTEGER,
    pf INTEGER,
    pts INTEGER,
    PRIMARY KEY (game_id, team_id, starters_bench)
);

CREATE INDEX IF NOT EXISTS idx_pb_game ON player_boxscores(game_id);
CREATE INDEX IF NOT EXISTS idx_pb_person ON player_boxscores(person_id);
CREATE INDEX IF NOT EXISTS idx_pb_team ON player_boxscores(team_id);
CREATE INDEX IF NOT EXISTS idx_tb_game ON team_boxscores(game_id);
CREATE INDEX IF NOT EXISTS idx_tb_team ON team_boxscores(team_id);
"""


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(game_id: str) -> pathlib.Path:
    return CACHE_DIR / f"{game_id}.json"


def _is_cached(game_id: str) -> bool:
    return _cache_path(game_id).exists()


def _save_cache(game_id: str, data: dict):
    import json
    with open(_cache_path(game_id), "w") as f:
        json.dump(data, f)


def _load_cache(game_id: str) -> dict | None:
    import json
    path = _cache_path(game_id)
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return None


# ── Fetch logic ───────────────────────────────────────────────────────────────

def _int(val) -> int | None:
    if val is None or pd.isna(val):
        return None
    return int(val)


def fetch_boxscore(game_id: str) -> dict | None:
    """Fetch boxscore from API or cache. Returns dict with 'players' and 'teams' keys."""
    game_id = str(game_id).zfill(10)

    cached = _load_cache(game_id)
    if cached is not None:
        return cached

    try:
        bs = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
        time.sleep(SLEEP)
        dfs = bs.get_data_frames()

        player_df = dfs[0]
        team_df = dfs[1]

        players = []
        for _, row in player_df.iterrows():
            players.append({
                "person_id": int(row["personId"]),
                "first_name": row.get("firstName", ""),
                "family_name": row.get("familyName", ""),
                "team_id": int(row["teamId"]),
                "position": row.get("position", ""),
                "jersey_num": row.get("jerseyNum", ""),
                "comment": row.get("comment", ""),
                "minutes": row.get("minutes", ""),
                "fgm": _int(row.get("fieldGoalsMade")),
                "fga": _int(row.get("fieldGoalsAttempted")),
                "tpm": _int(row.get("threePointersMade")),
                "tpa": _int(row.get("threePointersAttempted")),
                "ftm": _int(row.get("freeThrowsMade")),
                "fta": _int(row.get("freeThrowsAttempted")),
                "oreb": _int(row.get("reboundsOffensive")),
                "dreb": _int(row.get("reboundsDefensive")),
                "reb": _int(row.get("reboundsTotal")),
                "ast": _int(row.get("assists")),
                "stl": _int(row.get("steals")),
                "blk": _int(row.get("blocks")),
                "tov": _int(row.get("turnovers")),
                "pf": _int(row.get("foulsPersonal")),
                "pts": _int(row.get("points")),
                "plus_minus": _int(row.get("plusMinusPoints")),
            })

        teams = []
        for _, row in team_df.iterrows():
            teams.append({
                "team_id": int(row["teamId"]),
                "starters_bench": row.get("startersBench", ""),
                "minutes": row.get("minutes", ""),
                "fgm": _int(row.get("fieldGoalsMade")),
                "fga": _int(row.get("fieldGoalsAttempted")),
                "tpm": _int(row.get("threePointersMade")),
                "tpa": _int(row.get("threePointersAttempted")),
                "ftm": _int(row.get("freeThrowsMade")),
                "fta": _int(row.get("freeThrowsAttempted")),
                "oreb": _int(row.get("reboundsOffensive")),
                "dreb": _int(row.get("reboundsDefensive")),
                "reb": _int(row.get("reboundsTotal")),
                "ast": _int(row.get("assists")),
                "stl": _int(row.get("steals")),
                "blk": _int(row.get("blocks")),
                "tov": _int(row.get("turnovers")),
                "pf": _int(row.get("foulsPersonal")),
                "pts": _int(row.get("points")),
            })

        result = {"players": players, "teams": teams}
        _save_cache(game_id, result)
        return result

    except Exception as e:
        print(f"    ✗ {game_id}: {e}")
        return None


# ── DB insertion ──────────────────────────────────────────────────────────────

def init_schema(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def game_already_loaded(conn: sqlite3.Connection, game_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM player_boxscores WHERE game_id = ? LIMIT 1", (game_id,)
    ).fetchone()
    return row is not None


def insert_boxscore(conn: sqlite3.Connection, game_id: str, data: dict):
    game_id = str(game_id).zfill(10)

    for p in data["players"]:
        conn.execute(
            "INSERT OR IGNORE INTO players (person_id, first_name, family_name) VALUES (?, ?, ?)",
            (p["person_id"], p["first_name"], p["family_name"]),
        )
        conn.execute(
            """INSERT OR IGNORE INTO player_boxscores
            (game_id, person_id, team_id, position, jersey_num, comment,
             minutes, fgm, fga, tpm, tpa, ftm, fta,
             oreb, dreb, reb, ast, stl, blk, tov, pf, pts, plus_minus)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (game_id, p["person_id"], p["team_id"], p["position"],
             p["jersey_num"], p["comment"], p["minutes"],
             p["fgm"], p["fga"], p["tpm"], p["tpa"], p["ftm"], p["fta"],
             p["oreb"], p["dreb"], p["reb"], p["ast"], p["stl"],
             p["blk"], p["tov"], p["pf"], p["pts"], p["plus_minus"]),
        )

    for t in data["teams"]:
        conn.execute(
            """INSERT OR IGNORE INTO team_boxscores
            (game_id, team_id, starters_bench, minutes,
             fgm, fga, tpm, tpa, ftm, fta,
             oreb, dreb, reb, ast, stl, blk, tov, pf, pts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (game_id, t["team_id"], t["starters_bench"], t["minutes"],
             t["fgm"], t["fga"], t["tpm"], t["tpa"], t["ftm"], t["fta"],
             t["oreb"], t["dreb"], t["reb"], t["ast"], t["stl"],
             t["blk"], t["tov"], t["pf"], t["pts"]),
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def get_game_ids_for_seasons(conn: sqlite3.Connection, num_seasons: int) -> list[tuple[str, str]]:
    """Get (game_id, season) pairs from the games table, most recent N seasons."""
    rows = conn.execute(
        "SELECT DISTINCT season FROM games ORDER BY season DESC LIMIT ?",
        (num_seasons,)
    ).fetchall()
    seasons = [r[0] for r in rows]

    placeholders = ",".join("?" * len(seasons))
    games = conn.execute(
        f"SELECT game_id, season FROM games WHERE season IN ({placeholders}) ORDER BY date",
        seasons,
    ).fetchall()
    return games


def main():
    parser = argparse.ArgumentParser(description="Fetch NBA Playoff Boxscores")
    parser.add_argument("--seasons", type=int, default=1,
                        help="Number of seasons to fetch (default: 1 = most recent)")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Commit every N games")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be fetched without fetching")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    init_schema(conn)

    games = get_game_ids_for_seasons(conn, args.seasons)
    print(f"Found {len(games)} playoff games across {args.seasons} season(s)")

    already = 0
    to_fetch = []
    for game_id, season in games:
        if game_already_loaded(conn, game_id):
            already += 1
        else:
            to_fetch.append((game_id, season))

    print(f"  Already loaded: {already}")
    print(f"  To fetch: {len(to_fetch)}")

    if args.dry_run:
        eta_minutes = len(to_fetch) * SLEEP / 60
        print(f"  ETA: ~{eta_minutes:.0f} minutes")
        conn.close()
        return

    if not to_fetch:
        print("Nothing to do.")
        conn.close()
        return

    eta_minutes = len(to_fetch) * SLEEP / 60
    print(f"  ETA: ~{eta_minutes:.0f} minutes")
    print()

    fetched = 0
    failed = 0
    current_season = None

    for i, (game_id, season) in enumerate(to_fetch, 1):
        if season != current_season:
            current_season = season
            print(f"── {season} ──")

        data = fetch_boxscore(game_id)
        if data is None:
            failed += 1
            continue

        insert_boxscore(conn, game_id, data)
        fetched += 1

        if fetched % args.batch_size == 0:
            conn.commit()
            print(f"  [{i}/{len(to_fetch)}] committed {fetched} games...")

    conn.commit()
    conn.close()

    print()
    print(f"Done. Fetched: {fetched}, Failed: {failed}, Skipped: {already}")

    db_size = DB_PATH.stat().st_size / 1024 / 1024
    print(f"DB size: {db_size:.1f} MB")


if __name__ == "__main__":
    main()
