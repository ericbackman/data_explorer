-- player_game at the raw grain: one row per player per game, ~1.48M rows.
--
-- This is the HTAP case. The same table has to answer both:
--   OLTP  "show me this player's game log"      - point lookup, milliseconds
--   OLAP  "league-wide scoring by season"        - full scan, aggregate
-- On a row store the second is slow; on a columnar store the first is. TiDB
-- keeps both representations of ONE table and lets the optimizer choose, which
-- is why this table lives here rather than being split across two systems.
--
-- MySQL dialect, not Postgres: TiDB speaks the MySQL protocol.

CREATE TABLE IF NOT EXISTS player_game (
    game_id      VARCHAR(16)  NOT NULL,
    player_id    BIGINT       NOT NULL,
    team_id      BIGINT       NOT NULL,
    season       VARCHAR(9)   NOT NULL,
    season_type  VARCHAR(24)  NOT NULL,
    game_date    DATE         NOT NULL,
    matchup      VARCHAR(32),
    wl           CHAR(1),
    min          DECIMAL(6,1),
    fgm          INT, fga  INT, fg_pct  DECIMAL(5,3),
    fg3m         INT, fg3a INT, fg3_pct DECIMAL(5,3),
    ftm          INT, fta  INT, ft_pct  DECIMAL(5,3),
    oreb         INT, dreb INT, reb     INT,
    ast          INT, stl  INT, blk     INT,
    tov          INT, pf   INT, pts     INT,
    plus_minus   DECIMAL(7,1),

    -- CLUSTERED so the row data lives in the primary key's B-tree rather than
    -- behind a separate row id. (game_id, player_id) is the natural key and is
    -- also how a box score is read, so the common lookup touches one structure.
    --
    -- Deliberately NOT an AUTO_INCREMENT surrogate: in a distributed store a
    -- monotonic key sends every insert to the same region, and that write
    -- hotspot is the single most common way a TiDB schema is got wrong. A
    -- natural composite key spreads writes across the keyspace for free.
    PRIMARY KEY (game_id, player_id) CLUSTERED
);

-- "This player's game log, newest first" - the OLTP access path.
CREATE INDEX idx_player_date ON player_game (player_id, game_date DESC);

-- Narrows season-scoped analytics before any scan is needed.
CREATE INDEX idx_season ON player_game (season, season_type);
