"""
Playoff Health Analysis (2019-2025) — HARD NUMBERS ONLY.

Computes, for every playoff team since 2019, how many playoff games each team's
EXPECTED ROTATION (top-8 by regular-season minutes-per-game) missed. In the
playoffs, teams play every available body, so a rotation player not appearing is
an injury/suspension proxy that is far cleaner than regular-season DNPs.

Outputs:
  reports/playoff_health_2019_2025.csv   — one row per (season, team)
  reports/playoff_health_2019_2025.json  — same, structured for the web page

Methodology (all numbers are computed from nba_api box scores):
  - stars           : top 5 players by RS minutes-per-game (>= 15 GP with team).
                      In the playoffs, starters essentially never sit a FULL game
                      unless injured, so a star's full-game absence is a clean
                      injury proxy (bench/rest noise is excluded).
  - team_po_games   : distinct playoff GAME_IDs the team appeared in
  - star_avail_pct  : star games played / (5 * team_po_games). A RATE, so it is
                      not biased by how many rounds a team survived.
  - star_games_missed: 5*team_po_games - star games played (raw count, for detail)
  - elim_star_missed: star games missed within the team's FINAL (elimination) series
  - rounds_reached  : distinct opponents faced (1=R1 ... 4=Finals)
  - result          : champion / runner-up / eliminated-RN

Cause-of-injury labels are NOT invented here; they are layered in the report
from documented public record, kept separate from these computed counts.
"""

import json
import sys
import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguegamelog

sys.stdout.reconfigure(encoding="utf-8")

SLEEP = 0.6
CACHE = Path(".cache/playoff_health")
CACHE.mkdir(parents=True, exist_ok=True)
OUT = Path("reports")
OUT.mkdir(exist_ok=True)

# playoff year -> nba_api season string
SEASONS = {
    2019: "2018-19",
    2020: "2019-20",
    2021: "2020-21",
    2022: "2021-22",
    2023: "2022-23",
    2024: "2023-24",
    2025: "2024-25",
}
STAR_COUNT = 5  # top-5 by RS MPG = the starters/stars; full-game absence ~ injury
MIN_RS_GP = 15  # games with the team to count as part of the expected rotation


def _cached(name: str, fetch):
    """Cache raw API DataFrames to CSV to avoid re-hitting NBA.com."""
    fp = CACHE / f"{name}.csv"
    if fp.exists():
        return pd.read_csv(fp, dtype={"GAME_ID": str})
    df = fetch()
    df.to_csv(fp, index=False)
    time.sleep(SLEEP)
    return df


def fetch_player_log(season: str, season_type: str) -> pd.DataFrame:
    return _cached(
        f"{season}_{season_type.replace(' ', '')}_P",
        lambda: leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star=season_type,
            player_or_team_abbreviation="P",
            timeout=60,
        ).get_data_frames()[0],
    )


def opponent_from_matchup(matchup: str) -> str:
    # "DEN vs. LAC" or "DEN @ LAC" -> "LAC"
    sep = " vs. " if " vs. " in matchup else " @ "
    return matchup.split(sep)[1].strip()


def analyze_season(year: int, season: str) -> list[dict]:
    rs = fetch_player_log(season, "Regular Season")
    po = fetch_player_log(season, "Playoffs")
    po["GAME_ID"] = po["GAME_ID"].astype(str)

    # A player's final regular-season team that year. Used to exclude players
    # traded AWAY at the deadline (e.g. Durant/Kyrie off 2023 BKN) — they have
    # zero playoff games for the old team but were NOT injured, they were traded.
    last_team = (
        rs.sort_values("GAME_DATE")
        .groupby("PLAYER_ID")["TEAM_ABBREVIATION"]
        .last()
    )

    rows = []
    for team, tpo in po.groupby("TEAM_ABBREVIATION"):
        team_games = sorted(tpo["GAME_ID"].unique())
        n_team_games = len(team_games)

        # --- rounds, opponents, result (champion ends on a WIN) ---
        tg = tpo.drop_duplicates("GAME_ID").sort_values("GAME_DATE")
        tg = tg.assign(OPP=tg["MATCHUP"].map(opponent_from_matchup))
        opponents = list(dict.fromkeys(tg["OPP"]))  # series order preserved
        rounds_reached = len(opponents)
        last_game = tg.iloc[-1]
        won_last = last_game["WL"] == "W"
        final_opp = last_game["OPP"]
        final_series_games = set(tg[tg["OPP"] == final_opp]["GAME_ID"])

        if won_last and rounds_reached == 4:
            result = "champion"
        elif rounds_reached == 4:
            result = "runner-up"
        else:
            result = f"eliminated-R{rounds_reached}"

        # --- stars: top-5 by RS minutes-per-game for THIS team ---
        trs = rs[rs["TEAM_ABBREVIATION"] == team]
        agg = (
            trs.groupby(["PLAYER_ID", "PLAYER_NAME"])
            .agg(GP=("MIN", "size"), MIN_TOT=("MIN", "sum"))
            .reset_index()
        )
        agg = agg[agg["GP"] >= MIN_RS_GP]
        # keep only players who FINISHED the season on this team (drops trades-away)
        agg = agg[agg["PLAYER_ID"].map(last_team) == team]
        agg["MPG"] = agg["MIN_TOT"] / agg["GP"]
        stars = agg.sort_values("MPG", ascending=False).head(STAR_COUNT)
        n_stars = len(stars)

        # --- playoff appearances per star ---
        po_games_by_player = (
            tpo.groupby("PLAYER_ID")["GAME_ID"].apply(set).to_dict()
        )

        star_played = 0
        elim_missed = 0
        injured_detail = []
        for _, p in stars.iterrows():
            pid = p["PLAYER_ID"]
            played_set = po_games_by_player.get(pid, set())
            played = len(played_set)
            star_played += played
            missed = max(n_team_games - played, 0)
            elim_missed_p = len(final_series_games - played_set)
            elim_missed += elim_missed_p
            if missed > 0:
                injured_detail.append(
                    {"player": p["PLAYER_NAME"], "missed": int(missed),
                     "of": int(n_team_games), "in_elim_series": int(elim_missed_p)}
                )

        denom = n_stars * n_team_games
        star_avail_pct = round(100 * star_played / denom, 1) if denom else 100.0

        rows.append({
            "year": year,
            "season": season,
            "team": team,
            "result": result,
            "rounds_reached": rounds_reached,
            "team_po_games": n_team_games,
            "n_stars": int(n_stars),
            "star_avail_pct": star_avail_pct,
            "star_games_missed": int(denom - star_played),
            "elim_star_missed": int(elim_missed),
            "injured_stars": injured_detail,
        })
    return rows


def main():
    all_rows = []
    for year, season in SEASONS.items():
        print(f"[{year}] season {season} ...", flush=True)
        all_rows.extend(analyze_season(year, season))

    df = pd.DataFrame(all_rows)
    # per-season health rank: 1 = healthiest (highest star availability %)
    df["health_rank"] = (
        df.groupby("year")["star_avail_pct"]
        .rank(method="min", ascending=False)
        .astype(int)
    )
    df["field_size"] = df.groupby("year")["team"].transform("size")

    csv_cols = ["year", "season", "team", "result", "rounds_reached",
                "team_po_games", "n_stars", "star_avail_pct",
                "star_games_missed", "elim_star_missed", "health_rank",
                "field_size"]
    df[csv_cols].sort_values(["year", "health_rank"]).to_csv(
        OUT / "playoff_health_2019_2025.csv", index=False
    )
    (OUT / "playoff_health_2019_2025.json").write_text(
        df.to_json(orient="records"), encoding="utf-8"
    )

    # ---- console summary: the two questions the user asked ----
    print("\n=== STAR AVAILABILITY: CHAMPION & RUNNER-UP (rank 1 = healthiest of 16) ===")
    print(f"{'Yr':<5}{'Champion':<28}{'Runner-up':<28}")
    champ_ranks, ru_ranks = [], []
    for year in SEASONS:
        sub = df[df["year"] == year]
        ch = sub[sub["result"] == "champion"].iloc[0]
        ru = sub[sub["result"] == "runner-up"].iloc[0]
        champ_ranks.append(ch["health_rank"])
        ru_ranks.append(ru["health_rank"])
        cstr = f"{ch['team']} #{ch['health_rank']} ({ch['star_avail_pct']}%)"
        ustr = f"{ru['team']} #{ru['health_rank']} ({ru['star_avail_pct']}%)"
        print(f"{year:<5}{cstr:<28}{ustr:<28}")

    print("\n=== ELIMINATED TEAMS MISSING A STAR IN THEIR FINAL SERIES (injury-compromised) ===")
    elim = df[(df["elim_star_missed"] > 0) & (df["result"].str.startswith("eliminated"))]
    for _, r in elim.sort_values(["year", "elim_star_missed"], ascending=[True, False]).iterrows():
        names = ", ".join(f"{d['player']} (-{d['in_elim_series']})"
                          for d in r["injured_stars"] if d["in_elim_series"] > 0)
        print(f"  {r['year']} {r['team']:<4} {r['result']:<14} "
              f"star-games missed in elim series: {r['elim_star_missed']:<3} {names}")

    n = len(SEASONS)
    print(f"\nChampion was top-4 healthiest in its field:        "
          f"{sum(1 for x in champ_ranks if x <= 4)}/{n} seasons")
    print(f"Champion in top-HALF (rank <=8) for health:        "
          f"{sum(1 for x in champ_ranks if x <= 8)}/{n} seasons")
    print(f"Finalists (champ+RU) BOTH in top-half for health:  "
          f"{sum(1 for c, u in zip(champ_ranks, ru_ranks) if c <= 8 and u <= 8)}/{n} seasons")
    print(f"Champion had >=95% star availability:              "
          f"{sum(1 for year in SEASONS for _, r in df[(df.year==year)&(df.result=='champion')].iterrows() if r['star_avail_pct']>=95)}/{n} seasons")
    print(f"\nWrote reports/playoff_health_2019_2025.csv and .json")


if __name__ == "__main__":
    main()
