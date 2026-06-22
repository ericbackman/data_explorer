# nba — local NBA box-score DB (free, from nba_api)

Per-interest data project inside `data_explorer`. Builds a local SQLite DB of NBA
player/team game logs purely from the free **nba_api** (stats.nba.com, no key).

## Layout
- `client.py` — rate-limited, retrying, disk-cached nba_api wrapper
- `parse.py`  — LeagueGameLog dataframes → normalized rows (pure, tested)
- `db.py`     — SQLite schema + idempotent (`INSERT OR REPLACE`) loaders
- `scrape.py` — resumable backfill/update CLI
- `tests/`    — network-free tests for parsing + the refetch policy
- `data/`     — SQLite DB + raw JSON cache (**gitignored**, regenerable)

## Usage
```powershell
cd C:\Users\ericb\Github\data_explorer
.\.venv\Scripts\python.exe -m nba.scrape --seasons 1996-2026   # modern era (~2 min)
.\.venv\Scripts\python.exe -m nba.scrape --seasons 1946-2026   # all of NBA history
.\.venv\Scripts\python.exe -m nba.scrape --seasons 2025-2026 --dry-run
.\.venv\Scripts\python.exe -m pytest nba/
```

## Design notes
- **Backbone is `LeagueGameLog`:** one request returns a whole season of
  player/team rows (~320 requests for all history, vs ~65k fetched per game).
- **Refetch policy** (`scrape.py`): always re-pull the current + prior season
  (live games + late stat corrections), skip older loaded seasons; `--force`
  rebuilds everything.
- **Raw facts only** — derive betting metrics (rest, pace, ATS) in SQL. Per-game
  advanced box scores / play-by-play are a later tier that joins on `game_id`.
