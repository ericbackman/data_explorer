-- Top scorers of the 2023-24 regular season.
--
-- The `game_date` predicate is not optional: player_game is declared with
-- require_partition_filter, so BigQuery REJECTS this query without it. That is
-- the guardrail working - it makes the cheap version the only version.
--
-- The date range prunes ~80 years of monthly partitions down to ~9, and the
-- clustering on (team_id, season_type) narrows further within them. Compare the
-- dry-run estimate here against the same query with the WHERE removed: the
-- second one will not run at all.
SELECT
  pg.player_id,
  ANY_VALUE(pg.team_id)              AS team_id,
  COUNT(*)                           AS games,
  ROUND(AVG(pg.pts), 1)              AS ppg,
  ROUND(AVG(pg.reb), 1)              AS rpg,
  ROUND(AVG(pg.ast), 1)              AS apg,
  ROUND(AVG(pg.plus_minus), 1)       AS plus_minus
FROM `nba.player_game` AS pg
WHERE pg.game_date BETWEEN DATE '2023-10-01' AND DATE '2024-06-30'
  AND pg.season_type = 'Regular Season'
GROUP BY pg.player_id
HAVING games >= 40
ORDER BY ppg DESC
LIMIT 25
