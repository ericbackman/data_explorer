-- Shooting in the last two minutes of a one-possession fourth quarter,
-- 2023-24 regular season.
--
-- This is the query that justifies BigQuery for this dataset. It reaches into
-- play_by_play (18.3M rows) at the event level - the kind of question the
-- aggregated box-score tables cannot answer at all.
--
-- Note what keeps it cheap:
--   * the game_date predicate prunes to ~9 monthly partitions (and is REQUIRED -
--     the table is declared with require_partition_filter);
--   * only the columns actually used are selected, because BigQuery is columnar
--     and bills per column read, so `SELECT *` here would cost several times
--     more for the same answer.
--
-- `clock` is an ISO-8601 duration string ('PT01M23.00S'), so the remaining time
-- is parsed out rather than compared as text.
WITH clutch AS (
  SELECT
    pbp.team_tricode,
    pbp.shot_result,
    pbp.shot_value,
    ABS(pbp.score_home - pbp.score_away) AS margin,
    CAST(REGEXP_EXTRACT(pbp.clock, r'PT(\d+)M') AS INT64) * 60
      + CAST(REGEXP_EXTRACT(pbp.clock, r'M([\d.]+)S') AS FLOAT64) AS secs_left
  FROM `nba.play_by_play` AS pbp
  WHERE pbp.game_date BETWEEN DATE '2023-10-01' AND DATE '2024-06-30'
    AND pbp.season_type = 'Regular Season'
    AND pbp.period = 4
    AND pbp.is_field_goal = 1
    AND pbp.team_tricode IS NOT NULL
)
SELECT
  team_tricode,
  COUNT(*)                                                        AS attempts,
  COUNTIF(shot_result = 'Made')                                   AS makes,
  ROUND(100 * COUNTIF(shot_result = 'Made') / COUNT(*), 1)        AS fg_pct,
  ROUND(100 * COUNTIF(shot_result = 'Made' AND shot_value = 3)
        / NULLIF(COUNTIF(shot_value = 3), 0), 1)                  AS fg3_pct
FROM clutch
WHERE secs_left <= 120
  AND margin <= 3
GROUP BY team_tricode
HAVING attempts >= 25
ORDER BY fg_pct DESC
LIMIT 30
