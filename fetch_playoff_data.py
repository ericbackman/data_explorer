"""
NBA Playoff Max-Deficit Data Fetcher
=====================================
Fetches all playoff games going back 30 seasons (1996-2026) and computes
the maximum deficit each team faced at any point during each game.

Uses BoxScoreSummaryV3 DF[7] `biggestLead` field — same approach as the
regular season pipeline but filtered to playoffs only.

Detects playoff round and series matchup for each game by tracking each
team's chronological sequence of opponents within a season.

Usage:
  python fetch_playoff_data.py                # all 30 seasons
  python fetch_playoff_data.py --seasons 5    # last 5 seasons
  python fetch_playoff_data.py --dry-run      # show what would be fetched
"""

import sys
import time
import json
import pathlib
import argparse

import pandas as pd
from nba_api.stats.endpoints import (
    leaguegamelog,
    boxscoresummaryv3,
)

sys.stdout.reconfigure(encoding="utf-8")

SEASONS = [
    "1996-97", "1997-98", "1998-99", "1999-00", "2000-01",
    "2001-02", "2002-03", "2003-04", "2004-05", "2005-06",
    "2006-07", "2007-08", "2008-09", "2009-10", "2010-11",
    "2011-12", "2012-13", "2013-14", "2014-15", "2015-16",
    "2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
    "2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
]
SEASON_TYPE = "Playoffs"
SLEEP = 0.7
CACHE_DIR = pathlib.Path(".cache/playoff_backtest")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CSV = pathlib.Path("playoff_max_deficit_situations.csv")

ROUND_NAMES = {
    1: "First Round",
    2: "Conference Semis",
    3: "Conference Finals",
    4: "Finals",
}


# ── Cache helpers ────────────────────────────────────────────────────────────

def _cache_path(prefix: str, key: str) -> pathlib.Path:
    return CACHE_DIR / f"{prefix}_{key}.json"


def _load_json(path: pathlib.Path):
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return None


def _save_json(path: pathlib.Path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def _load_df(path: pathlib.Path) -> pd.DataFrame | None:
    if path.exists():
        df = pd.read_json(path, orient="records")
        if "GAME_ID" in df.columns:
            df["GAME_ID"] = df["GAME_ID"].astype(str).str.zfill(10)
        for col in ["TEAM_ID", "HOME_TEAM_ID", "AWAY_TEAM_ID"]:
            if col in df.columns:
                df[col] = df[col].astype(int)
        return df
    return None


def _save_df(path: pathlib.Path, df: pd.DataFrame):
    df.to_json(path, orient="records", indent=2)


# ── Step 1: Fetch playoff game logs ─────────────────────────────────────────

def fetch_game_ids(season: str) -> pd.DataFrame:
    cache = _cache_path("playoff_gamelog", season.replace("-", "_"))
    cached = _load_df(cache)
    if cached is not None:
        return cached

    print(f"  Fetching playoff game log for {season}...")
    gl = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star=SEASON_TYPE,
        player_or_team_abbreviation="T",
    )
    time.sleep(SLEEP)
    df = gl.get_data_frames()[0]
    _save_df(cache, df)
    return df


def build_game_index(seasons: list[str]) -> pd.DataFrame:
    all_rows = []

    for season in seasons:
        gl = fetch_game_ids(season)
        if gl.empty:
            print(f"  No playoff games found for {season}")
            continue

        home_games = gl[gl["MATCHUP"].str.contains("vs.")].copy()
        away_games = gl[gl["MATCHUP"].str.contains("@")].copy()

        home_games = home_games.rename(columns={
            "TEAM_ID": "HOME_TEAM_ID",
            "TEAM_ABBREVIATION": "HOME_TEAM",
            "PTS": "HOME_FINAL",
        })
        away_games = away_games.rename(columns={
            "TEAM_ID": "AWAY_TEAM_ID",
            "TEAM_ABBREVIATION": "AWAY_TEAM",
            "PTS": "AWAY_FINAL",
        })

        merged = home_games[["GAME_ID", "GAME_DATE", "HOME_TEAM_ID", "HOME_TEAM", "HOME_FINAL"]].merge(
            away_games[["GAME_ID", "AWAY_TEAM_ID", "AWAY_TEAM", "AWAY_FINAL"]],
            on="GAME_ID",
        )
        merged["SEASON"] = season
        all_rows.append(merged)

    if not all_rows:
        return pd.DataFrame()

    games = pd.concat(all_rows, ignore_index=True)
    games["GAME_ID"] = games["GAME_ID"].astype(str).str.zfill(10)
    print(f"  Total playoff games across {len(seasons)} seasons: {len(games)}")
    return games


# ── Step 2: Detect playoff rounds ───────────────────────────────────────────

def detect_playoff_rounds(games: pd.DataFrame) -> pd.DataFrame:
    """
    For each team in each season, track the chronological sequence of
    unique opponents. The order maps to playoff rounds:
      1st opponent = First Round
      2nd opponent = Conference Semis
      3rd opponent = Conference Finals
      4th opponent = Finals
    """
    games = games.sort_values("GAME_DATE").copy()

    game_rounds = {}
    game_series = {}

    for season in games["SEASON"].unique():
        sg = games[games["SEASON"] == season].sort_values("GAME_DATE")

        # Track each team's series progression
        team_opponents: dict[str, list[str]] = {}
        for _, game in sg.iterrows():
            home, away = game["HOME_TEAM"], game["AWAY_TEAM"]
            for team, opp in [(home, away), (away, home)]:
                if team not in team_opponents:
                    team_opponents[team] = []
                if not team_opponents[team] or team_opponents[team][-1] != opp:
                    team_opponents[team].append(opp)

        for _, game in sg.iterrows():
            gid = game["GAME_ID"]
            home, away = game["HOME_TEAM"], game["AWAY_TEAM"]

            round_num = 0
            if home in team_opponents and away in team_opponents[home]:
                round_num = team_opponents[home].index(away) + 1

            game_rounds[gid] = ROUND_NAMES.get(round_num, f"Round {round_num}")

            pair = "_".join(sorted([home, away]))
            game_series[gid] = f"{season}_{pair}"

    games["PLAYOFF_ROUND"] = games["GAME_ID"].map(game_rounds)
    games["SERIES_ID"] = games["GAME_ID"].map(game_series)
    return games


# ── Step 3: Fetch biggestLead from BoxScoreSummaryV3 DF[7] ──────────────────

def fetch_game_summary(game_id: str) -> dict | None:
    game_id = str(game_id).zfill(10)
    cache = _cache_path("gamesummary", game_id)
    cached = _load_json(cache)
    if cached is not None:
        return cached

    try:
        bs = boxscoresummaryv3.BoxScoreSummaryV3(game_id=game_id)
        time.sleep(SLEEP)
        df7 = bs.get_data_frames()[7]

        if len(df7) != 2:
            return None

        result = {}
        for _, row in df7.iterrows():
            team_id = str(int(row["teamId"]))
            result[team_id] = {
                "tricode": row.get("teamTricode", ""),
                "points": int(row.get("points", 0)),
                "biggest_lead": int(row.get("biggestLead", 0)),
                "lead_changes": int(row.get("leadChanges", 0)),
                "times_tied": int(row.get("timesTied", 0)),
                "biggest_run": int(row.get("biggestScoringRun", 0)),
                "bench_pts": int(row.get("benchPoints", 0)),
            }

        _save_json(cache, result)
        return result
    except Exception:
        return None


def build_max_deficit_dataset(games: pd.DataFrame) -> pd.DataFrame:
    rows = []
    errors = 0
    total = len(games)

    for i, (_, game) in enumerate(games.iterrows()):
        if (i + 1) % 50 == 0:
            print(f"  Fetching game summaries: {i+1}/{total} ({errors} errors)")

        gs = fetch_game_summary(game["GAME_ID"])
        if gs is None:
            errors += 1
            continue

        home_id = str(int(game["HOME_TEAM_ID"]))
        away_id = str(int(game["AWAY_TEAM_ID"]))

        if home_id not in gs or away_id not in gs:
            errors += 1
            continue

        h = gs[home_id]
        a = gs[away_id]
        home_won = game["HOME_FINAL"] > game["AWAY_FINAL"]

        # Home team's max deficit = away team's biggest lead (and vice versa)
        home_max_deficit = a["biggest_lead"]
        away_max_deficit = h["biggest_lead"]

        base = {
            "game_id": game["GAME_ID"],
            "date": game["GAME_DATE"],
            "season": game["SEASON"],
            "playoff_round": game.get("PLAYOFF_ROUND", ""),
            "series_id": game.get("SERIES_ID", ""),
            "home_team": game["HOME_TEAM"],
            "away_team": game["AWAY_TEAM"],
            "home_final": game["HOME_FINAL"],
            "away_final": game["AWAY_FINAL"],
            "lead_changes": h["lead_changes"],
            "times_tied": h["times_tied"],
        }

        rows.append({
            **base,
            "team": game["HOME_TEAM"],
            "team_id": int(home_id),
            "opponent": game["AWAY_TEAM"],
            "location": "home",
            "max_deficit": home_max_deficit,
            "own_biggest_lead": h["biggest_lead"],
            "won": home_won,
            "came_back": home_won and home_max_deficit > 0,
            "final_margin": game["HOME_FINAL"] - game["AWAY_FINAL"],
            "biggest_run": h["biggest_run"],
            "bench_pts": h["bench_pts"],
        })

        rows.append({
            **base,
            "team": game["AWAY_TEAM"],
            "team_id": int(away_id),
            "opponent": game["HOME_TEAM"],
            "location": "away",
            "max_deficit": away_max_deficit,
            "own_biggest_lead": a["biggest_lead"],
            "won": not home_won,
            "came_back": (not home_won) and away_max_deficit > 0,
            "final_margin": game["AWAY_FINAL"] - game["HOME_FINAL"],
            "biggest_run": a["biggest_run"],
            "bench_pts": a["bench_pts"],
        })

    print(f"  Done: {len(rows)} team-game rows from {total} games ({errors} errors)")
    return pd.DataFrame(rows)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch NBA Playoff Max-Deficit Data")
    parser.add_argument("--seasons", type=int, default=30,
                        help="Number of recent seasons (default: 30)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show game counts without fetching summaries")
    args = parser.parse_args()

    seasons = SEASONS[-args.seasons:]
    print(f"Fetching playoff data for {len(seasons)} season(s): {seasons[0]} to {seasons[-1]}")

    print("\n[1/4] Building playoff game index...")
    games = build_game_index(seasons)
    if games.empty:
        print("No playoff games found.")
        return

    print("\n[2/4] Detecting playoff rounds...")
    games = detect_playoff_rounds(games)

    round_counts = games["PLAYOFF_ROUND"].value_counts()
    for rnd, cnt in sorted(round_counts.items(),
                           key=lambda x: list(ROUND_NAMES.values()).index(x[0])
                           if x[0] in ROUND_NAMES.values() else 99):
        print(f"  {rnd}: {cnt} games")

    if args.dry_run:
        eta = len(games) * SLEEP / 60
        print(f"\n  Would fetch {len(games)} game summaries. ETA: ~{eta:.0f} min")
        return

    print("\n[3/4] Fetching biggestLead data...")
    deficit_df = build_max_deficit_dataset(games)

    print("\n[4/4] Saving to CSV...")
    deficit_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  Saved {len(deficit_df)} rows to {OUTPUT_CSV}")

    print("\n  Quick summary:")
    for t in [10, 15, 20, 25]:
        down = deficit_df[deficit_df["max_deficit"] >= t]
        wins = down["won"].sum()
        n = len(down)
        rate = wins / n if n > 0 else 0
        print(f"  Down {t}+: {n} situations, {int(wins)} comebacks ({rate:.1%})")


if __name__ == "__main__":
    main()
