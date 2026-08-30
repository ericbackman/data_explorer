-- Serving schema for the NBA data.
--
-- This is deliberately NOT a copy of the analytics tables. BigQuery holds the
-- 18.3M-row event log for scanning; this holds a compact, indexed, normalised
-- slice shaped for point lookups and joins - what an API actually queries.
-- Neon's free plan is 0.5 GB per PROJECT shared across every branch, so a
-- serving layer is the only thing that fits, which happens to also be the right
-- design.

CREATE TABLE teams (
    team_id      BIGINT PRIMARY KEY,
    abbreviation TEXT NOT NULL,
    name         TEXT NOT NULL
);

CREATE TABLE players (
    player_id   BIGINT PRIMARY KEY,
    player_name TEXT NOT NULL
);

-- One row per (player, season, season_type). ~37k rows.
CREATE TABLE player_season (
    player_id   BIGINT  NOT NULL REFERENCES players (player_id),
    season      TEXT    NOT NULL,
    season_type TEXT    NOT NULL,
    -- The last team the player appeared for that season. Nullable because the
    -- oldest rows carry team ids that predate the teams dimension, and a FK
    -- that silently dropped those rows would be worse than a NULL.
    team_id     BIGINT  REFERENCES teams (team_id),
    games       INTEGER NOT NULL CHECK (games > 0),
    minutes     NUMERIC(8, 1) NOT NULL DEFAULT 0,
    pts         INTEGER NOT NULL DEFAULT 0,
    reb         INTEGER NOT NULL DEFAULT 0,
    ast         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, season, season_type)
);

-- "Who led this season?" - the leaderboard query. The PK already covers
-- player-first lookups, so this covers the season-first direction.
CREATE INDEX idx_player_season_season ON player_season (season, season_type);

-- "Which players did this team roster?" Partial: rows without a team are never
-- the answer to that question, so they are kept out of the index.
CREATE INDEX idx_player_season_team ON player_season (team_id, season)
    WHERE team_id IS NOT NULL;
