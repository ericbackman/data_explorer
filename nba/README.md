# nba: local NBA box-score DB (free, from nba_api)

Per-interest data project inside `data_explorer`. Builds a local SQLite DB of NBA
player/team game logs purely from the free **nba_api** (stats.nba.com, no key).

## Layout
- `client.py`: rate-limited, retrying, disk-cached nba_api wrapper
- `parse.py`: LeagueGameLog dataframes → normalized rows (pure, tested)
- `db.py`: SQLite schema + idempotent (`INSERT OR REPLACE`) loaders
- `scrape.py`: resumable backfill/update CLI
- `hof_scrape.py`, Hall of Fame inductees → `hall_of_fame` (Wikipedia, not
  nba_api, see Design notes)
- `tests/`: network-free tests for parsing + the refetch policy
- `data/`: SQLite DB + raw JSON cache (gitignored, regenerable)

## Usage
```powershell
cd $env:USERPROFILE\Github\data_explorer
.\.venv\Scripts\python.exe -m nba.scrape --seasons 1996-2026   # modern era (~2 min)
.\.venv\Scripts\python.exe -m nba.scrape --seasons 1946-2026   # all of NBA history
.\.venv\Scripts\python.exe -m nba.scrape --seasons 2025-2026 --dry-run
.\.venv\Scripts\python.exe -m pytest nba/
```

## Design notes
- **Backbone is `LeagueGameLog`:** one request returns a whole season of
  player/team rows (~480 requests for all history, vs ~65k fetched per game).
- **Three season types:** `Regular Season`, `PlayIn` and `Playoffs`. The play-in
  is its own LeagueGameLog season type from 2020-21 on and appears in neither of
  the others, so it was never stored before 2026-09-14. Filter on
  `season_type = 'Playoffs'`, never `!= 'Regular Season'`, or play-in games count
  as playoff games.
- **Neutral-site games:** `derive_games` finds the home side from MATCHUP ("LAL
  vs. MIN" is home), but at a neutral site (Mexico City, Paris, Berlin, London,
  the NBA Cup semifinals in Las Vegas) both rows read "@". Those games are
  oriented from `BoxScoreSummaryV3`, one request each. V2 answers None for the
  Las Vegas games. Until 2026-09-14 they were dropped from `games` silently:
  1,225 games against 1,230 in `team_game` for 2024-25 and 2025-26.
- **Refetch policy** (`scrape.py`): always re-pull the current + prior season
  (live games + late stat corrections), skip older loaded seasons; `--force`
  rebuilds everything.
- **Raw facts only.** Derive betting metrics (rest, pace, ATS) in SQL. Per-game
  advanced box scores / play-by-play are a later tier that joins on `game_id`.
- **Hall of Fame is NOT an nba_api award** (`hof_scrape.py`): stats.nba.com stops
  emitting `Hall of Fame Inductee` after the **2018** class, so `player_awards`
  has no Kobe/Duncan/Garnett (2020), Dirk/Wade/Gasol (2023) or Carmelo (2025)
  row. Re-running `nba.awards_scrape` cannot fix it: the gap is upstream, and it
  skips every already-fetched player anyway. HOF therefore has its own
  `hall_of_fame` table scraped from Wikipedia's Naismith list, cross-validated
  against the ≤2018 rows nba_api *does* have (a year disagreement fails the run).
  Consumers UNION it into their awards view; never write HOF rows into
  `player_awards`, which `load_player_awards` rewrites per player.

  ```powershell
  .\.venv\Scripts\python.exe -m nba.hof_scrape --dry-run   # parse + validate only
  .\.venv\Scripts\python.exe -m nba.hof_scrape             # load hall_of_fame
  ```
