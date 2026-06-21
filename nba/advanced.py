"""Advanced NBA stats — DERIVED from the box scores already in nba.db (zero API).

Most "advanced" metrics are pure functions of the traditional box score, so we
compute them as SQL VIEWS over player_game / team_game instead of fetching
stats.nba.com's per-game advanced endpoint (~37k requests, 1996+ only). Views
mean: no storage, no staleness, all 80 seasons, instant, and consistent with the
underlying rows by construction. Formulas follow Basketball-Reference / Dean
Oliver conventions (not the NBA's exact official figures).

Columns that need stats the NBA didn't track in a given era (STL/BLK/TOV from
1973-74, 3PT from 1979-80) come back NULL for older seasons — correct, not buggy.

    python -m nba.advanced            # (re)create the views + print sanity samples
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sqlite3

log = logging.getLogger(__name__)

DB_PATH = pathlib.Path(__file__).resolve().parent / "data" / "nba.db"

# team_advanced: one row per team per game. Joins each team to its opponent (same
# game_id, different team_id) so possessions/pace/ratings can use both sides.
TEAM_VIEW = """
DROP VIEW IF EXISTS team_advanced;
CREATE VIEW team_advanced AS
WITH paired AS (
  SELECT t.game_id, t.team_id, t.season, t.season_type, t.game_date, t.matchup, t.wl,
         t.min AS tm_min, t.pts, t.fgm, t.fga, t.fg3m, t.ftm, t.fta,
         t.oreb, t.dreb, t.tov,
         o.team_id AS opp_team_id, o.pts AS opp_pts, o.fgm AS opp_fgm, o.fga AS opp_fga,
         o.ftm AS opp_ftm, o.fta AS opp_fta, o.oreb AS opp_oreb, o.dreb AS opp_dreb, o.tov AS opp_tov
  FROM team_game t
  JOIN team_game o ON o.game_id = t.game_id AND o.team_id <> t.team_id
),
poss AS (
  SELECT *,
    0.5 * (
      (fga + 0.4*fta - 1.07*(CAST(oreb AS REAL)/NULLIF(oreb+opp_dreb,0))*(fga-fgm) + tov)
      + (opp_fga + 0.4*opp_fta - 1.07*(CAST(opp_oreb AS REAL)/NULLIF(opp_oreb+dreb,0))*(opp_fga-opp_fgm) + opp_tov)
    ) AS poss
  FROM paired
)
SELECT game_id, team_id, opp_team_id, season, season_type, game_date, matchup, wl,
       pts, opp_pts,
       ROUND(poss, 1)                                               AS poss,
       ROUND(48.0 * poss / NULLIF(tm_min/5.0, 0), 1)               AS pace,
       ROUND(100.0 * pts / NULLIF(poss, 0), 1)                     AS off_rtg,
       ROUND(100.0 * opp_pts / NULLIF(poss, 0), 1)                 AS def_rtg,
       ROUND(100.0 * (pts - opp_pts) / NULLIF(poss, 0), 1)         AS net_rtg,
       ROUND(1.0*(fgm + 0.5*COALESCE(fg3m,0)) / NULLIF(fga, 0), 3) AS efg_pct,
       ROUND(1.0*tov / NULLIF(fga + 0.44*fta + tov, 0), 3)         AS tov_pct,
       ROUND(1.0*oreb / NULLIF(oreb + opp_dreb, 0), 3)             AS orb_pct,
       ROUND(1.0*fta / NULLIF(fga, 0), 3)                          AS ft_rate
FROM poss;
"""

# player_advanced: one row per player per game, joined to own-team and opponent
# team totals (needed for usage / rebound% / assist%).
PLAYER_VIEW = """
DROP VIEW IF EXISTS player_advanced;
CREATE VIEW player_advanced AS
WITH p AS (
  SELECT pg.game_id, pg.player_id, pg.team_id, pg.season, pg.season_type, pg.game_date,
         pg.min, pg.pts, pg.fgm, pg.fga, pg.fg3m, pg.ftm, pg.fta,
         pg.oreb, pg.dreb, pg.reb, pg.ast, pg.stl, pg.blk, pg.tov, pg.pf,
         t.min AS tm_min, t.fgm AS tm_fgm, t.fga AS tm_fga, t.fta AS tm_fta,
         t.tov AS tm_tov, t.reb AS tm_reb,
         o.reb AS opp_reb
  FROM player_game pg
  JOIN team_game t ON t.game_id = pg.game_id AND t.team_id = pg.team_id
  JOIN team_game o ON o.game_id = pg.game_id AND o.team_id <> pg.team_id
)
SELECT game_id, player_id, team_id, season, season_type, game_date, min, pts,
       ROUND(1.0*pts / NULLIF(2*(fga + 0.44*fta), 0), 3)                          AS ts_pct,
       ROUND(1.0*(fgm + 0.5*COALESCE(fg3m,0)) / NULLIF(fga, 0), 3)                AS efg_pct,
       ROUND(100.0 * ((fga + 0.44*fta + tov) * (tm_min/5.0))
             / NULLIF(min * (tm_fga + 0.44*tm_fta + tm_tov), 0), 1)              AS usg_pct,
       ROUND(100.0 * (reb * (tm_min/5.0)) / NULLIF(min * (tm_reb + opp_reb), 0), 1) AS reb_pct,
       ROUND(100.0 * ast / NULLIF((min/(tm_min/5.0))*tm_fgm - fgm, 0), 1)        AS ast_pct,
       ROUND(pts + 0.4*fgm - 0.7*fga - 0.4*(fta-ftm) + 0.7*oreb + 0.3*dreb
             + stl + 0.7*ast + 0.7*blk - 0.4*pf - tov, 1)                        AS game_score
FROM p;
"""


def create_views(conn: sqlite3.Connection) -> None:
    conn.executescript(TEAM_VIEW)
    conn.executescript(PLAYER_VIEW)
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description="Create derived advanced-stat views over nba.db")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    conn = sqlite3.connect(args.db)
    create_views(conn)
    log.info("created views: team_advanced, player_advanced")

    log.info("league average pace by sample season (sanity ~90-105):")
    for season, pace in conn.execute("""
        SELECT season, ROUND(AVG(pace),1) FROM team_advanced
        WHERE season IN ('1985-86','1995-96','2004-05','2024-25') AND season_type='Regular Season'
        GROUP BY season ORDER BY season"""):
        log.info("    %s  pace=%s", season, pace)

    log.info("top TS%% single seasons (>=1000 min, 2024-25):")
    rows = conn.execute("""
        SELECT pl.player_name, ROUND(SUM(pa.pts)*1.0,0) AS pts,
               ROUND(100.0*SUM(pa.pts)/SUM(2*(pg.fga+0.44*pg.fta)),1) AS ts
        FROM player_advanced pa
        JOIN player_game pg ON pg.game_id=pa.game_id AND pg.player_id=pa.player_id
        JOIN players pl ON pl.player_id=pa.player_id
        WHERE pa.season='2024-25' AND pa.season_type='Regular Season'
        GROUP BY pa.player_id HAVING SUM(pa.min) >= 1000
        ORDER BY ts DESC LIMIT 5""").fetchall()
    for name, pts, ts in rows:
        log.info("    %-24s TS%%=%s", name, ts)

    conn.close()


if __name__ == "__main__":
    main()
