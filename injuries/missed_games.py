"""Games missed by NBA players, 1946-47 to the present, from the box scores alone.

The league's own box scores name the reason for an absence only from 1996-97
(``box_absences.py``), and from 2003-04 they list the active roster only, so
an injured player on the inactive list simply disappears. This module does
not need a reason or a listing: a player who appears for a team on 2 November
and again on 20 November, with the team playing eight games in between, missed
eight games. Summed over the players who actually play (minutes per game at or
above ``ROTATION_MPG``), that gap count is the one injury-burden measure that
is defined the same way in 1952 and 2025.

Three gap kinds per player-team-season:

- ``gap_missed``: team games strictly between the player's first and last
  appearance that he did not play. Always counted.
- ``tail_missed``: team games after his last appearance, counted only when he
  plays for the same team the following season (so the absence was not a
  release, retirement or trade). This is where season-ending injuries land.
- ``head_missed``: team games before his first appearance, counted only when he
  played for the same team the previous season.

Trades mid-season split a player into two rows, one per team, so the window
method never counts another team's games. Rest days and suspensions are gaps
too; the per-season reason shares from ``box_absences.py`` size them.

Inputs are three CSV extracts from the canonical database on its host (SPORTS_DB_HOST, SPORTS_DB_PATH)
(``--pull`` runs the extract over ssh; ``--from-dir`` reads existing files):
``pts_tenure.csv`` (one row per player-team-season), ``team_dates.csv`` (one row
per team-game) and ``players.csv``.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import logging
import os
import subprocess
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
PLAYER_CSV = DATA_DIR / "missed_games_player_season.csv"
SEASON_CSV = DATA_DIR / "missed_games_by_season.csv"

ROTATION_MPG = 20.0  # minutes per game played; the cut between rotation and bench
MIN_GP_FOR_RATE = 10  # a player needs this many games for his minutes per game to mean anything
FIRST_MINUTES_SEASON = "1951-52"  # minutes were not recorded before this season
# Host and path come from the environment (loud when missing); the repo names neither.
SSH_HOST = os.environ.get("SPORTS_DB_HOST") or ""
REMOTE_DB = os.environ.get("SPORTS_DB_PATH") or ""

EXTRACT_SCRIPT = r'''
import os, sqlite3, sys, csv, time
DB = "%(db)s"; WAL = DB + "-wal"
if os.path.exists(WAL) and os.path.getsize(WAL) > 0:
    sys.exit(f"{WAL} is non-empty: sports-crons is mid-write. Retry later.")
con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
con.execute("PRAGMA query_only = ON")
def dump(sql, path):
    cur = con.execute(sql)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow([d[0] for d in cur.description]); w.writerows(cur)
dump("""SELECT player_id, team_id, season, MIN(game_date) first_date, MAX(game_date) last_date,
        COUNT(*) gp, SUM(COALESCE(min,0)) min_total, SUM(COALESCE(pts,0)) pts_total,
        SUM(CASE WHEN min IS NULL THEN 1 ELSE 0 END) min_null, SUM(CASE WHEN min=0 THEN 1 ELSE 0 END) min_zero
        FROM player_game WHERE season_type='Regular Season' GROUP BY 1,2,3""", "/tmp/pts_tenure.csv")
dump("""SELECT team_id, season, game_date, game_id FROM team_game WHERE season_type='Regular Season'
        ORDER BY team_id, season, game_date""", "/tmp/team_dates.csv")
dump("SELECT player_id, player_name FROM players", "/tmp/players.csv")
if os.path.exists(WAL) and os.path.getsize(WAL) > 0:
    sys.exit(f"{WAL} appeared during the extract: results may be inconsistent. Retry after 06:30.")
print("ok")
'''

PLAYER_COLUMNS = (
    "season",
    "team_id",
    "player_id",
    "player",
    "first_date",
    "last_date",
    "gp",
    "mpg",
    "rotation",
    "window_games",
    "gap_missed",
    "tail_missed",
    "head_missed",
    "team_games",
)


def pull(dest: Path, host: str = SSH_HOST, db: str = REMOTE_DB) -> None:
    """Run the extract on the database host and copy the three CSVs into `dest`. Fails loud."""
    if not host or not db:
        raise RuntimeError("set SPORTS_DB_HOST (ssh host of the sports database) and SPORTS_DB_PATH (path of nba.db on it)")
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ssh", host, "python3", "-"], input=EXTRACT_SCRIPT % {"db": db}, text=True, check=True, timeout=600)
    files = ["pts_tenure.csv", "team_dates.csv", "players.csv"]
    subprocess.run(["scp", "-q", *[f"{host}:/tmp/{f}" for f in files], str(dest)], check=True, timeout=600)
    for f in files:
        if not (dest / f).exists():
            raise FileNotFoundError(f"extract did not produce {dest / f}")
    log.info("pulled %s into %s", files, dest)


def load_team_dates(path: Path) -> dict[tuple[int, str], list[str]]:
    """(team_id, season) -> sorted list of game dates."""
    out: dict[tuple[int, str], list[str]] = defaultdict(list)
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out[(int(row["team_id"]), row["season"])].append(row["game_date"])
    for dates in out.values():
        dates.sort()
    if not out:
        raise ValueError(f"{path} holds no team games")
    return dict(out)


def load_players(path: Path) -> dict[int, str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {int(r["player_id"]): r["player_name"] for r in csv.DictReader(fh)}


def load_tenure(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} is empty")
    for r in rows:
        r["player_id"] = int(r["player_id"])
        r["team_id"] = int(r["team_id"])
        r["gp"] = int(r["gp"])
        r["min_total"] = float(r["min_total"])
        r["min_null"] = int(r["min_null"])
    return rows


def games_between(dates: list[str], first: str, last: str) -> int:
    """Team games on or after `first` and on or before `last`."""
    lo = bisect.bisect_left(dates, first)
    hi = bisect.bisect_right(dates, last)
    return hi - lo


def next_season(season: str) -> str:
    start = int(season[:4]) + 1
    return f"{start}-{str(start + 1)[-2:]}"


def prev_season(season: str) -> str:
    start = int(season[:4]) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def compute_player_rows(tenure: list[dict], team_dates: dict[tuple[int, str], list[str]], players: dict[int, str]) -> list[dict]:
    """Pure: one output row per player-team-season with the three gap counts."""
    present = {(r["player_id"], r["team_id"], r["season"]) for r in tenure}
    out = []
    for r in tenure:
        key = (r["team_id"], r["season"])
        if key not in team_dates:
            raise KeyError(f"no team games for team {r['team_id']} in {r['season']}")
        dates = team_dates[key]
        window = games_between(dates, r["first_date"], r["last_date"])
        gap = window - r["gp"]
        if gap < 0:
            raise ValueError(f"player {r['player_id']} {r['season']} played {r['gp']} in a {window}-game window")
        tail = head = 0
        if (r["player_id"], r["team_id"], next_season(r["season"])) in present:
            tail = len(dates) - bisect.bisect_right(dates, r["last_date"])
        if (r["player_id"], r["team_id"], prev_season(r["season"])) in present:
            head = bisect.bisect_left(dates, r["first_date"])
        mpg = r["min_total"] / r["gp"] if r["gp"] and r["min_null"] == 0 else None
        rotation = int(mpg is not None and r["gp"] >= MIN_GP_FOR_RATE and mpg >= ROTATION_MPG)
        out.append(
            {
                "season": r["season"],
                "team_id": r["team_id"],
                "player_id": r["player_id"],
                "player": players.get(r["player_id"], ""),
                "first_date": r["first_date"],
                "last_date": r["last_date"],
                "gp": r["gp"],
                "mpg": round(mpg, 1) if mpg is not None else "",
                "rotation": rotation,
                "window_games": window,
                "gap_missed": gap,
                "tail_missed": tail,
                "head_missed": head,
                "team_games": len(dates),
            }
        )
    return out


def season_summary(player_rows: list[dict], team_dates: dict[tuple[int, str], list[str]]) -> list[dict]:
    """Pure: per-season burden for rotation players and for everyone."""
    team_games = defaultdict(int)
    teams = defaultdict(set)
    for (team_id, season), dates in team_dates.items():
        team_games[season] += len(dates)
        teams[season].add(team_id)
    acc: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in player_rows:
        a = acc[r["season"]]
        missed = r["gap_missed"] + r["tail_missed"] + r["head_missed"]
        a["players"] += 1
        a["all_missed"] += missed
        a["all_gap_missed"] += r["gap_missed"]
        if r["rotation"]:
            a["rotation_players"] += 1
            a["rotation_gp"] += r["gp"]
            a["rotation_gap_missed"] += r["gap_missed"]
            a["rotation_tail_missed"] += r["tail_missed"]
            a["rotation_head_missed"] += r["head_missed"]
            a["rotation_missed"] += missed
            if missed >= 10:
                a["rotation_missed_10plus"] += 1
            if missed >= 20:
                a["rotation_missed_20plus"] += 1
            if missed == 0:
                a["rotation_missed_0"] += 1
    out = []
    for season in sorted(team_games):
        a = acc[season]
        tg = team_games[season]
        has_minutes = season >= FIRST_MINUTES_SEASON
        row = {
            "season": season,
            "teams": len(teams[season]),
            "team_games": tg,
            "players": a["players"],
            "all_missed": a["all_missed"],
            "all_gap_missed": a["all_gap_missed"],
            "all_missed_per_team_game": round(a["all_missed"] / tg, 4),
            "rotation_players": a["rotation_players"] if has_minutes else "",
            "rotation_gp": a["rotation_gp"] if has_minutes else "",
            "rotation_missed": a["rotation_missed"] if has_minutes else "",
            "rotation_gap_missed": a["rotation_gap_missed"] if has_minutes else "",
            "rotation_tail_missed": a["rotation_tail_missed"] if has_minutes else "",
            "rotation_head_missed": a["rotation_head_missed"] if has_minutes else "",
            "rotation_missed_per_team_game": round(a["rotation_missed"] / tg, 4) if has_minutes else "",
            "rotation_missed_share": round(a["rotation_missed"] / (a["rotation_missed"] + a["rotation_gp"]), 4) if has_minutes and a["rotation_gp"] else "",
            "rotation_missed_10plus": a["rotation_missed_10plus"] if has_minutes else "",
            "rotation_missed_20plus": a["rotation_missed_20plus"] if has_minutes else "",
            "rotation_missed_0": a["rotation_missed_0"] if has_minutes else "",
            "note": "" if has_minutes else "minutes not recorded; rotation series starts 1951-52",
        }
        out.append(row)
    return out


def write_csv(path: Path, rows: list[dict], columns) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(columns))
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %s (%d rows)", path, len(rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from-dir", type=Path, required=True, help="folder holding pts_tenure.csv, team_dates.csv, players.csv")
    parser.add_argument("--pull", action="store_true", help="run the extract on the database host into --from-dir first")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.pull:
        pull(args.from_dir)
    team_dates = load_team_dates(args.from_dir / "team_dates.csv")
    players = load_players(args.from_dir / "players.csv")
    tenure = load_tenure(args.from_dir / "pts_tenure.csv")
    player_rows = compute_player_rows(tenure, team_dates, players)
    summary = season_summary(player_rows, team_dates)
    write_csv(PLAYER_CSV, player_rows, PLAYER_COLUMNS)
    write_csv(SEASON_CSV, summary, summary[0].keys())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
