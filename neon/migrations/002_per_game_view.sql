-- Per-game rates, computed rather than stored.
--
-- Storing ppg/rpg/apg alongside the totals would let the two disagree the first
-- time a season is re-seeded; a view cannot drift from its own inputs.
--
-- This is also the migration the branch-per-PR workflow exercises: it lands on a
-- fresh Neon branch every run, so `migrate.py` proves it applies cleanly against
-- 001 rather than only against whatever state production happens to be in.

CREATE VIEW player_season_rates AS
SELECT
    ps.player_id,
    p.player_name,
    ps.season,
    ps.season_type,
    ps.team_id,
    t.abbreviation AS team,
    ps.games,
    ps.pts,
    ps.reb,
    ps.ast,
    ROUND(ps.pts::numeric / ps.games, 1) AS ppg,
    ROUND(ps.reb::numeric / ps.games, 1) AS rpg,
    ROUND(ps.ast::numeric / ps.games, 1) AS apg,
    ROUND(ps.minutes / ps.games, 1)      AS mpg
FROM player_season AS ps
JOIN players AS p ON p.player_id = ps.player_id
LEFT JOIN teams AS t ON t.team_id = ps.team_id;

COMMENT ON VIEW player_season_rates IS
    'Per-game rates derived from player_season totals. games > 0 is enforced by a CHECK on the base table, so the division is safe.';
