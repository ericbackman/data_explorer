"""Pre-1999 NFL game results (1966-1998) from the free Spreadspoke dataset.

nflverse starts 1999 and Pro Football Reference (the only 1920+ source) is
anti-bot walled, so this fills 1966-1998 from Spreadspoke's free CSV — game
results + lines, normalized to the nflverse `games` schema and tagged
source='spreadspoke' so the games table reads as one continuous 1966-2025 history.
(1920-1965 has no free source; it would require Firecrawl on PFR.)

    python -m nfl.historical          # download + load 1966-1998 into games
"""

from __future__ import annotations

import argparse
import io
import logging
import sqlite3

import pandas as pd
import requests

from nfl import pull

log = logging.getLogger(__name__)

# Static historical mirror of the Kaggle Spreadspoke file (old rows never change).
SPREADSPOKE_URL = "https://raw.githubusercontent.com/peanutshawny/nfl-sports-betting/master/data/spreadspoke_scores.csv"
START, END = 1966, 1998   # 1999+ comes authoritatively from nflverse

# Spreadspoke full team name -> current franchise abbreviation (nflverse codes).
# Relocations collapse to the franchise's current code (Oakland/LA Raiders -> LV).
TEAM_MAP = {
    "Arizona Cardinals": "ARI", "Phoenix Cardinals": "ARI", "St. Louis Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Colts": "IND", "Indianapolis Colts": "IND",
    "Baltimore Ravens": "BAL",
    "Boston Patriots": "NE", "New England Patriots": "NE",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Oilers": "TEN", "Tennessee Oilers": "TEN", "Tennessee Titans": "TEN",
    "Houston Texans": "HOU", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Los Angeles Chargers": "LAC", "San Diego Chargers": "LAC",
    "Los Angeles Raiders": "LV", "Oakland Raiders": "LV",
    "Los Angeles Rams": "LAR", "St. Louis Rams": "LAR",
    "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN", "New Orleans Saints": "NO",
    "New York Giants": "NYG", "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB", "Washington Redskins": "WAS",
}

# Spreadspoke playoff label -> (game_type, week number for game_id construction)
PLAYOFF_ROUND = {
    "wildcard": ("WC", 18), "division": ("DIV", 19),
    "conference": ("CON", 20), "superbowl": ("SB", 21),
}


def _abbr(name: str) -> str:
    abbr = TEAM_MAP.get(name)
    if abbr is None:
        raise ValueError(f"unmapped team name: {name!r}")  # fail loud, don't drop games
    return abbr


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Spreadspoke rows -> nflverse `games`-shaped rows for START..END."""
    df = df[df["schedule_season"].between(START, END)].copy()
    rows = []
    for r in df.to_dict("records"):
        wk_raw = str(r["schedule_week"]).strip()
        if bool(r["schedule_playoff"]):
            game_type, week = PLAYOFF_ROUND.get(wk_raw.lower().replace(" ", ""), ("POST", None))
        else:
            game_type, week = "REG", (int(wk_raw) if wk_raw.isdigit() else None)
        home, away = _abbr(r["team_home"]), _abbr(r["team_away"])
        hs, as_ = r["score_home"], r["score_away"]
        scored = pd.notna(hs) and pd.notna(as_)
        rows.append({
            "game_id": f"{int(r['schedule_season'])}_{week:02d}_{away}_{home}" if week else None,
            "season": int(r["schedule_season"]),
            "game_type": game_type,
            "week": week,
            "gameday": pd.to_datetime(r["schedule_date"], format="%m/%d/%Y").strftime("%Y-%m-%d"),
            "away_team": away, "home_team": home,
            "away_score": int(as_) if scored else None,
            "home_score": int(hs) if scored else None,
            "result": int(hs - as_) if scored else None,       # home margin (nflverse convention)
            "total": int(hs + as_) if scored else None,
            "total_line": r.get("over_under_line"),
            "location": "Neutral" if r.get("stadium_neutral") else "Home",
            "stadium": r.get("stadium"),
            "temp": r.get("weather_temperature"),
            "wind": r.get("weather_wind_mph"),
            "source": "spreadspoke",
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Load pre-1999 (1966-1998) game results from Spreadspoke")
    ap.add_argument("--db", default=str(pull.DB_PATH))
    ap.add_argument("--url", default=SPREADSPOKE_URL)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    log.info("downloading %s", args.url)
    resp = requests.get(args.url, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    raw = pd.read_csv(io.StringIO(resp.text))
    norm = normalize(raw)
    log.info("normalized %d games (%d-%d)", len(norm), START, END)

    conn = sqlite3.connect(args.db)
    for season, sdf in norm.groupby("season"):
        pull.load_season(conn, "games", sdf, int(season))
    # mark the nflverse-origin rows for provenance clarity
    conn.execute("UPDATE games SET source='nflverse' WHERE source IS NULL")
    conn.commit()
    lo, hi = conn.execute("SELECT MIN(season), MAX(season) FROM games").fetchone()
    n = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    conn.close()
    log.info("games now: %d rows spanning %d-%d", n, lo, hi)


if __name__ == "__main__":
    main()
