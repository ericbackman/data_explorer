"""
NHL Playoff Series — derive per-team playoff series outcomes from the games table
=================================================================================
Groups a team's game_type=3 (playoff) games, ordered by date, into series by
opponent, then computes the series score, round, a Game-7 flag, and a
blown-lead detector: *lost the series after leading by >= 2 games* — e.g. the
2020-21 Maple Leafs blowing a 3-1 lead to Montreal.

Pure + offline: reads ``games``, writes ``playoff_series``. It needs only the
game index (no boxscores), so it runs immediately after ``build``. The raw facts
it stores (series score, max lead, Game 7, round) are the inputs to an essay's
own "how devastating was this exit" ranking — that judgment lives downstream in
the essay adapter, not here.

Usage:
    python -m nhl.series                       # Toronto (team_id 10), all seasons
    python -m nhl.series --team-id 10 --verify
"""

import argparse
import logging
import pathlib
import sqlite3

log = logging.getLogger("nhl.series")

DB_PATH = pathlib.Path(__file__).parent / "data" / "nhl.db"

TORONTO_TEAM_ID = 10

ROUND_NAMES = {
    1: "First Round",
    2: "Second Round",
    3: "Conference Final",
    4: "Stanley Cup Final",
}

SERIES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS playoff_series (
    season          TEXT NOT NULL,       -- '20202021'
    team_id         INTEGER NOT NULL,    -- subject team (10 = Toronto)
    round_num       INTEGER NOT NULL,    -- 1..4, chronological within the season
    round_name      TEXT,
    opponent_id     INTEGER,
    opponent_abbrev TEXT,
    team_wins       INTEGER NOT NULL,
    opp_wins        INTEGER NOT NULL,
    games_played    INTEGER NOT NULL,
    series_won      INTEGER NOT NULL,    -- 0/1
    went_to_game7   INTEGER NOT NULL,    -- 0/1
    max_series_lead INTEGER NOT NULL,    -- max (team_wins - opp_wins) at any point
    blew_lead       INTEGER NOT NULL,    -- lost the series after leading by >= 2 games
    PRIMARY KEY (season, team_id, round_num)
);
CREATE INDEX IF NOT EXISTS idx_series_team ON playoff_series(team_id);
"""


def team_playoff_games(conn: sqlite3.Connection, team_id: int) -> list[tuple]:
    """Date-ordered ``(season, opponent_id, won)`` rows for a team's playoff games."""
    return conn.execute(
        """
        SELECT season,
               CASE WHEN home_team_id = :t THEN away_team_id ELSE home_team_id END
                   AS opponent_id,
               CASE WHEN (home_team_id = :t AND home_score > away_score)
                      OR (away_team_id = :t AND away_score > home_score)
                    THEN 1 ELSE 0 END AS won
        FROM games
        WHERE game_type = 3
          AND (home_team_id = :t OR away_team_id = :t)
          AND home_score IS NOT NULL AND away_score IS NOT NULL
        ORDER BY season, date
        """,
        {"t": team_id},
    ).fetchall()


def group_series(rows: list[tuple]) -> list[dict]:
    """``[(season, opponent_id, won), ...]`` (date-ordered) -> list of series dicts.

    A new series starts whenever the ``(season, opponent)`` pair changes — teams
    never play two playoff opponents at once, so this cleanly segments rounds.
    """
    series: list[dict] = []
    cur: dict | None = None
    for season, opponent_id, won in rows:
        if cur is None or cur["season"] != season or cur["opponent_id"] != opponent_id:
            cur = {"season": season, "opponent_id": opponent_id, "results": []}
            series.append(cur)
        cur["results"].append(won)
    return series


def summarize(series: list[dict], team_id: int, abbrev_of: dict | None = None) -> list[dict]:
    """Series dicts -> flat ``playoff_series`` rows with the derived metrics.

    ``max_series_lead`` is the high-water mark of (team_wins - opp_wins) over the
    course of the series; ``blew_lead`` fires only when the team *lost* a series
    it once led by two or more games. A series winner is never flagged.
    """
    abbrev_of = abbrev_of or {}
    per_season_round: dict[str, int] = {}
    out: list[dict] = []
    for s in series:
        season = s["season"]
        round_num = per_season_round.get(season, 0) + 1
        per_season_round[season] = round_num

        results = s["results"]
        games_played = len(results)
        team_wins = sum(results)
        opp_wins = games_played - team_wins
        series_won = 1 if team_wins > opp_wins else 0

        tw = ow = max_lead = 0
        for won in results:
            if won:
                tw += 1
            else:
                ow += 1
            max_lead = max(max_lead, tw - ow)
        blew_lead = 1 if (series_won == 0 and max_lead >= 2) else 0

        out.append({
            "season": season,
            "team_id": team_id,
            "round_num": round_num,
            "round_name": ROUND_NAMES.get(round_num),
            "opponent_id": s["opponent_id"],
            "opponent_abbrev": abbrev_of.get(s["opponent_id"]),
            "team_wins": team_wins,
            "opp_wins": opp_wins,
            "games_played": games_played,
            "series_won": series_won,
            "went_to_game7": 1 if games_played == 7 else 0,
            "max_series_lead": max_lead,
            "blew_lead": blew_lead,
        })
    return out


def build_series(conn: sqlite3.Connection, team_id: int) -> int:
    """(Re)derive and store every playoff series for ``team_id``. Returns the count."""
    conn.executescript(SERIES_SCHEMA_SQL)
    abbrev_of = dict(conn.execute("SELECT team_id, abbrev FROM teams").fetchall())
    rows = team_playoff_games(conn, team_id)
    summaries = summarize(group_series(rows), team_id, abbrev_of)
    conn.execute("DELETE FROM playoff_series WHERE team_id = ?", (team_id,))
    conn.executemany(
        """INSERT INTO playoff_series
           (season, team_id, round_num, round_name, opponent_id, opponent_abbrev,
            team_wins, opp_wins, games_played, series_won, went_to_game7,
            max_series_lead, blew_lead)
           VALUES
           (:season, :team_id, :round_num, :round_name, :opponent_id, :opponent_abbrev,
            :team_wins, :opp_wins, :games_played, :series_won, :went_to_game7,
            :max_series_lead, :blew_lead)""",
        summaries,
    )
    conn.commit()
    return len(summaries)


def verify(conn: sqlite3.Connection, team_id: int) -> None:
    log.info("Playoff series for team %d (season | round | opp | score | flags):", team_id)
    for season, rnd, opp, tw, ow, won, g7, blew in conn.execute(
        """SELECT season, round_name, opponent_abbrev, team_wins, opp_wins,
                  series_won, went_to_game7, blew_lead
           FROM playoff_series WHERE team_id = ? ORDER BY season, round_num""",
        (team_id,),
    ):
        flags = " ".join(t for t, on in (("Game7", g7), ("BLEW-LEAD", blew)) if on)
        log.info("  %s  %-16s vs %-3s  %d-%d  %s   %s",
                 season, rnd or "?", opp or "?", tw, ow,
                 "WON " if won else "lost", flags)


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive NHL playoff series for a team")
    parser.add_argument("--team-id", type=int, default=TORONTO_TEAM_ID,
                        help="Subject team id (default 10 = Toronto Maple Leafs)")
    parser.add_argument("--verify", action="store_true", help="Print the derived series")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. Run `python -m nhl.build` first.")

    conn = sqlite3.connect(DB_PATH)
    try:
        n = build_series(conn, args.team_id)
        log.info("Wrote %d playoff series for team %d.", n, args.team_id)
        if args.verify:
            verify(conn, args.team_id)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
