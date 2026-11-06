"""Player absences from the NBA's own box scores, 1996-97 to the present.

Every nba.com box score lists the players who did not play with a comment:
``DNP - Coach's Decision``, ``DND - Sprained Left Ankle``, ``NWT - Personal
Reasons``. Through 2016-17 the injury comments name the body part; from
2017-18 the league writes ``DNP - Injury/Illness`` and names nothing (the
official injury report, parsed by ``injury_reports.py``, carries the body part
from 2018-12 on). This module turns those comments into one row per
player-game absence, classified with ``classify.py``, plus the per-season
denominators (player-games played, team-games) the rates need.

Source: ``nba_comebacks.db``, built by ``build_playoff_comebacks_db.py`` from
nba_api box scores (regular season, 1996-11-01 on). Pass its path with
``--db``; the default is the repo-root copy.

Usage::

    python -m injuries.box_absences --db ../nba_comebacks.db
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from collections import Counter
from pathlib import Path

from injuries.classify import COACH, classify, publishable_text

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "nba_comebacks.db"
DATA_DIR = HERE / "data"
ABSENCES_CSV = DATA_DIR / "box_absences.csv"
SEASON_CSV = DATA_DIR / "box_absences_by_season.csv"

ABSENCE_COLUMNS = (
    "game_id",
    "game_date",
    "season",
    "team_id",
    "person_id",
    "player",
    "comment",
    "category",
    "location",
    "region",
    "side",
    "nature",
    "below_knee",
)

ABSENCE_SQL = """
SELECT b.game_id, g.date, g.season, b.team_id, b.person_id,
       TRIM(p.first_name || ' ' || p.family_name) AS player,
       b.comment
FROM player_boxscores b
JOIN games g USING (game_id)
LEFT JOIN players p USING (person_id)
WHERE TRIM(b.comment) != '' AND (b.minutes IS NULL OR TRIM(b.minutes) = '')
ORDER BY g.date, b.game_id, b.team_id, player
"""

PLAYED_SQL = """
SELECT g.season, COUNT(*) AS player_games,
       COUNT(DISTINCT b.game_id) AS games
FROM player_boxscores b
JOIN games g USING (game_id)
WHERE b.minutes IS NOT NULL AND TRIM(b.minutes) != ''
GROUP BY g.season
"""


def open_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"box-score database not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    return con


def classify_rows(rows) -> list[dict]:
    """Attach a Label to each raw (game_id, date, season, team, person, player, comment) row."""
    out = []
    for game_id, date, season, team_id, person_id, player, comment in rows:
        label = classify(comment)
        out.append(
            {
                "game_id": game_id,
                "game_date": date,
                "season": season,
                "team_id": team_id,
                "person_id": person_id,
                "player": player or "",
                "comment": publishable_text(comment.strip(), label.category),
                "category": label.category,
                "location": label.location,
                "region": label.region,
                "side": label.side,
                "nature": label.nature,
                "below_knee": int(label.below_knee),
            }
        )
    return out


def season_summary(absences: list[dict], played: dict[str, tuple[int, int]]) -> list[dict]:
    """One row per season: denominators and absence counts by category."""
    by_season: dict[str, Counter] = {}
    for row in absences:
        by_season.setdefault(row["season"], Counter())[row["category"]] += 1
        if row["category"] == "injury":
            by_season[row["season"]]["injury_located"] += 1
            if row["below_knee"]:
                by_season[row["season"]]["injury_below_knee"] += 1
    seasons = sorted(set(by_season) | set(played))
    out = []
    for season in seasons:
        counts = by_season.get(season, Counter())
        player_games, games = played.get(season, (0, 0))
        if games == 0:
            raise ValueError(f"season {season} has absences but no played rows; the DB is inconsistent")
        row = {
            "season": season,
            "games": games,
            "team_games": games * 2,
            "player_games_played": player_games,
            "absences_total": sum(counts.values()) - counts["injury_located"] - counts["injury_below_knee"],
        }
        for category in ("injury", "injury_unspecified", "illness", "rest", "coach", "suspension", "personal", "protocol", "roster", "unknown"):
            row[f"abs_{category}"] = counts[category]
        row["injury_below_knee"] = counts["injury_below_knee"]
        row["health_absences"] = counts["injury"] + counts["injury_unspecified"] + counts["illness"]
        row["health_absences_per_team_game"] = round(row["health_absences"] / row["team_games"], 4)
        out.append(row)
    return out


def write_csv(path: Path, rows: list[dict], columns) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)
    log.info("wrote %s (%d rows)", path, len(rows))


def build(db_path: Path, keep_coach: bool = False) -> tuple[list[dict], list[dict]]:
    con = open_readonly(db_path)
    raw = con.execute(ABSENCE_SQL).fetchall()
    if not raw:
        raise RuntimeError("no absence rows: the player_boxscores comment column is empty")
    absences = classify_rows(raw)
    played = {season: (pg, games) for season, pg, games in con.execute(PLAYED_SQL)}
    summary = season_summary(absences, played)
    if not keep_coach:
        # Healthy scratches are 75% of the rows and carry no health signal;
        # the per-season file keeps their count.
        absences = [row for row in absences if row["category"] != COACH]
    return absences, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="path to nba_comebacks.db")
    parser.add_argument("--keep-coach", action="store_true", help="keep coach's-decision rows in the per-game file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    absences, summary = build(args.db, keep_coach=args.keep_coach)
    write_csv(ABSENCES_CSV, absences, ABSENCE_COLUMNS)
    write_csv(SEASON_CSV, summary, summary[0].keys())
    unknown = sum(r["abs_unknown"] for r in summary)
    total = sum(r["absences_total"] for r in summary)
    log.info("unknown category: %d of %d absences (%.2f%%)", unknown, total, 100 * unknown / total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
