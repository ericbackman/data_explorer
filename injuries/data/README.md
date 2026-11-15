# injuries/data

## Licence and personal data

The repository's MIT licence covers the code. The data files are derived from third-party sources and stay under those sources' terms: nba.com box scores and statistics (NBA.com Terms of Use; "Statistics: NBA.com"), the NBA's official injury reports (official.nba.com), and third-party scrapes of Pro Sports Transactions (a GitHub repository with no licence; PST's own terms could not be read). Nothing here is affiliated with or endorsed by the NBA or its teams.

The row-level files hold health information about named professional athletes as the league itself published it. Only the season and body-location aggregates and the per-player games-missed table are tracked in the repository; `injury_reports.csv`, `injury_reports_classified.csv`, `box_absences.csv` and `pst_events.csv` are generated locally and gitignored, and in every one of them the free text of a row that is not an injury, rest or suspension is blanked at build time (category kept), so a relative's death, an illness or a protocol status never leaves the source. Corrections and removal requests from a named player or their representative: corrections@buddycheck.dev.

## Pace, minutes and schedule (pace.py)

Source: the canonical NBA database (host and path from `SPORTS_DB_HOST` and `SPORTS_DB_PATH`), read-only over ssh. Regenerate from the repo root with `python injuries/pace.py` (about 10 seconds; it refuses to run while the database's daily writer is mid-write). Seasons are labelled `2024-25`. Regular season only unless a column says otherwise. The current season (2026-27, 9 games per team on 2026-11-05) is written with `partial = 1`; `player_minutes_leaders.csv` leaves it out. Every file is plain CSV with a header row and empty cells for "not available".

### pace_by_season.csv

| Column | Meaning |
|---|---|
| `season`, `partial` | Season label; 1 if the season has no playoff game yet |
| `pace` | League mean of 48 x possessions / (team minutes / 5) over team-games, with possessions = FGA - OREB + TOV + 0.44 x FTA. Team minutes are 240 in regulation and more with overtime, so an overtime game is not inflated. Empty where the inputs cover under 95% of team-games |
| `pace_bbr_formula` | Same, using Basketball-Reference's possession estimate (0.4 x FTA, and 1.07 x offensive-rebound rate x missed FG in place of raw OREB, averaged over both teams). Matches their published league pace to within 0.04 on the four seasons checked |
| `pts_per_game`, `fga_per_game`, `fg3a_per_game`, `fta_per_game` | Mean per team-game, over team-games where the stat is recorded |
| `fg3a_share_of_fga` | Sum FG3A / sum FGA, over team-games where both are recorded. Empty before the three-point line (1979-80) |
| `team_games` | Regular-season team-games in the season |
| `pace_team_games` | Team-games with FGA, OREB, FTA, team minutes and TOV > 0 (TOV of 0 is treated as not recorded) |
| `pace_note` | Why `pace` is empty |

TOV is NULL for every team-game before 1981-82, still NULL for 88% to 92% of them through 1984-85, and complete from 1985-86. Both pace columns are therefore empty for 1946-47 to 1984-85. Team minutes are also mostly 0 in 1946-47 to 1963-64.

### minutes_by_season.csv

Computed from (player, team, season) minute totals. A traded player counts once per team in the team columns and once in total in the player columns.

| Column | Meaning |
|---|---|
| `top8_mean_minutes` | Mean over teams of the total regular-season minutes of the team's 8 players with most minutes (a team-season total, so shortened seasons read low) |
| `top1_mean_minutes` | Mean over teams of the team's leader's minutes |
| `players_2500_plus`, `players_3000_plus` | Players whose total minutes across all teams reach the threshold |
| `mean_minutes_per_player_game` | Total minutes / player-games with minutes above 0 |
| `players_appeared` | Distinct players with any row that season (zero-minute rows count: they are real appearances) |
| `minutes_coverage` | Share of player-game rows with minutes above 0 |
| `minutes_note` | Set when coverage is under 95%; the minute-based columns are then empty |

Minutes are recorded for under 95% of rows in every season from 1946-47 to 1975-76, so those seasons carry only `players_appeared` and `minutes_coverage`. Coverage is 97.9% in 1976-77 and 98% or better in every season after that.

### schedule_by_season.csv

| Column | Meaning |
|---|---|
| `teams` | Teams with a regular-season game |
| `games_per_team` | Maximum games any team played |
| `season_span_days` | Days from the first to the last regular-season game |
| `mean_rest_days` | Mean days off between a team's consecutive games (a back-to-back is 0) |
| `back_to_backs_per_team` | Mean over teams of games played on the calendar day after the team's previous game |
| `playoff_games_total` | Distinct playoff games that season (play-in games excluded) |
| `playoff_games_max_team` | Most playoff games any one team played |

A team shows two games on one date in 1955-56 (twice) and 1978-79 (once); those count as 0 days off and are not back-to-backs. 2019-20 spans 297 days because of the March shutdown and the bubble, so its mean rest is not comparable.

### player_minutes_leaders.csv

Seasons 1996-97 on. `group = league_top3` is the three players with most regular-season minutes (`rank` 1 to 3, ties broken by lower `player_id`; `team` lists every team he played for, most minutes first). `group = finals_team_leader` is the minutes leader of each of the two Finals teams (the two teams in the last playoff game of the season, read from `games`), with `team` as that team. `regular_minutes` and `regular_games` are the player's regular-season totals (for `finals_team_leader`, with that team only); `playoff_minutes` and `playoff_games` are his playoff totals the same way. `regular_games` counts games with minutes above 0.

### zero_minute_rows.csv and zero_minute_rows.md

One row per season and season type (`Regular Season`, `Playoffs`, `PlayIn`) with the count of `player_game` rows where `min = 0`: `rows` (all rows), `zero_minute_rows`, `zero_share`, `zero_with_box_stats` (any of FGA, FTA, PTS, REB, AST, STL, BLK, TOV, PF above 0), `zero_with_plus_minus` (non-zero plus/minus), `zero_plus_minus_null`, `zero_all_blank` (no stats and plus/minus 0). The finding is in `zero_minute_rows.md`: the database holds no did-not-play rows.

## Games missed, 1946-47 on (missed_games.py)

Source: the same canonical database, three CSV extracts pulled over ssh (`python -m injuries.missed_games --pull --from-dir <dir>`). A player who appears for a team on two dates missed every team game in between that he did not play; games after his last appearance count only when he plays for the same team the next season, games before his first only when he played for it the season before. Regular season only. "Rotation" means at least 10 games played and at least 20 minutes per game played; minutes exist from 1951-52 and cover 95% of rows only from 1976-77 (`minutes_by_season.csv`), so the rotation series is reliable from 1976-77.

### missed_games_player_season.csv

One row per player-team-season: `gp`, `mpg`, `rotation` (0/1), `window_games` (team games between first and last appearance, inclusive), `gap_missed`, `tail_missed`, `head_missed`, `team_games`.

### missed_games_by_season.csv

Per season: `rotation_players`, `rotation_gp`, `rotation_missed` (gap + tail + head), the three parts, `rotation_missed_per_team_game` (the headline rate), `rotation_missed_share` (missed / (missed + played)), `rotation_missed_10plus`, `rotation_missed_20plus`, `rotation_missed_0` (player counts), and the same totals for every player (`all_*`). Empty rotation columns before 1951-52.

## Absence reasons from box scores, 1996-97 on (box_absences.py)

Source: `nba_comebacks.db` (nba.com box scores via nba_api, regular season). Every listed player who did not play carries a comment; `classify.py` maps it to a category and, for injuries, a body location. Two listing regimes: through 2002-03 the box score lists the whole roster (about 18 players a team-game), from 2003-04 only the active roster (about 12), so injured players on the inactive list disappear. Body parts are named through 2016-17 and again in some 2025-26 rows; from 2017-18 the league writes "Injury/Illness" only. Treat the file as a sample of reasons, not a rate; `missed_games_by_season.csv` is the rate.

### box_absences.csv

One row per player-game absence (local only, gitignored), coach's-decision rows dropped (their count is in the season file): `comment` (verbatim for injury, rest and suspension rows, blank otherwise), `category`, `location`, `region`, `side`, `nature`, `below_knee`.

### box_absences_by_season.csv

Per season: `games`, `team_games`, `player_games_played`, `absences_total`, one `abs_<category>` column per category, `injury_below_knee`, `health_absences` (injury + injury_unspecified + illness), `health_absences_per_team_game`.

## Official injury reports, 2018-12 on (injury_reports.py, classify_reports.py)

Source: the NBA's daily injury-report PDFs at `ak-static.cms.nba.com/referee/injury/Injury-Report_<date>_<slot>.pdf`, one slot per calendar date (the 05PM report through 2025-12, then the 05_30PM family), probed from 2018-10-16; the first report on the whole range is 2018-12-17 and a 403 means no report that day. Parsed with pdfplumber; the layout changed four times (a separate Category column in 2018-19, Reason before or after Current Status in 2019-20, header on page 1 only from 2022, no spaces in the text layer from 2024), and the parser reads column positions from each header row. Team-level markers ("NOT YET SUBMITTED", "ALL PLAYERS AVAILABLE") produce no row. PDFs are cached in `injuries/.cache/reports/` (gitignored, 94 MB); five of them sit in `injuries/tests/fixtures/` for the parser tests.

### injury_reports.csv

One row per player per report (local only, gitignored): `report_date`, `slot`, `game_date`, `game_time` (24-hour ET), `matchup`, `team`, `player` ("Last, First" as printed), `status` (Out, Doubtful, Questionable, Probable, Available), `reason` verbatim ("Injury/Illness - Left Ankle; Sprain"; 751 rows are blank in the PDF). 140,426 rows, 2018-12-17 to 2026-11-04.

### injury_reports_classified.csv

The same rows with `season` and the `classify.py` columns appended (local only, gitignored); `reason` is blanked where the category is not injury, injury_unspecified, rest or suspension. A player listed Out for a whole recovery produces one row per game day, so the page collapses rows into episodes (a run of listings for one player and body location with no gap over 10 days) before counting.

### injury_reports_coverage.csv

Per season (October to September): `days_probed`, `days_with_report`, `rows_parsed`, first and last report date, `parse_failures` and `failed_dates` (both 0 and empty on the 2026-11-05 run; a non-empty value is a loud failure, and the script exits 3).

## Injured-list events from open mirrors of Pro Sports Transactions (pst_mirror.py)

Source files in `injuries/raw/` (gitignored, third-party): the two elap733 GitHub CSVs (2010-08 to 2019-12) and, when Eric drops it there, the Kaggle 1951-2023 file. `pst_events.csv` has one row per dated move (`event_type` out or return) with the same classification columns; `pst_events_by_season.csv` counts out-events per season by category and `loc_<location>`. Events are dated moves, not games missed.

## Classification (classify.py)

Categories: injury, injury_unspecified, illness, rest, coach, suspension, personal, protocol, roster, unknown. Locations: achilles, ankle, foot, lower_leg (below the knee); knee; hamstring, quad_thigh, hip_groin (upper leg); back, torso, neck; head; shoulder, arm_elbow, hand_wrist; leg_unspecified; other. `below_knee` is 1 for the first four. Rules are ordered keyword lists in the module; the test file lists 50 worked examples.
