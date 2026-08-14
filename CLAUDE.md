# data_explorer — multi-sport data platform

Local SQLite databases for answering sports questions in plain English. Each sport
is a sub-project mirroring the same pattern (`nba/`, `pga/`, `nfl/`, …): a cached
scraper, a normalized schema, and analysis modules. Run python from this repo root
(e.g. `python -m pga.sg ...`).

## Answering a sports question — ALWAYS do this when asked one

1. **Read [`SCHEMA.md`](SCHEMA.md)** for the exact tables/columns — never guess
   column names. It's auto-generated and current.
2. Pick the database for the sport; query it **read-only** with python + sqlite3.
3. **Validate** before reporting — check the answer against a known fact (a famous
   result or number). If a derived stat disagrees with reality, suspect the query
   or the data, not reality.
4. Prefer the existing analysis modules when one fits (they encode the right
   definitions); drop to raw SQL for anything novel.
5. After adding/refreshing data, regenerate the map: `python schema_doc.py`.

## Per-sport notes

- **Golf (`pga/`)** — events → results → rounds → **holes (7M)** → **bios** →
  **strokes-gained**, plus majors 1960-2004 (`major_history`). For "who played
  best", prefer **SG-Total** (`hole_field_avg` baseline) over finishing position.
  Modules: `analysis` (leader conversion), `betting` (course history / form /
  closers / comebacks), `holes` (hole & course difficulty, par-3/4/5 splits),
  `sg` (strokes-gained), `tier2` (deep majors). See `pga/README.md`.
- **NBA (`nba/`)** — box scores 1946-present (nba_api). See `nba/README.md`.
- **NFL (`nfl/`)** — nflverse box scores + play-by-play, 1999-present.
- **NHL (`nhl/`)** — free NHL API (`api-web.nhle.com`). Game index 1997-present;
  skater/goalie box scores (RTSS era 1997+); resumable `--team-id` backfill.
  `playoff_series` is derived (round + Game-7 + blown-lead flags). Built for the
  Leafs "Plan the Parade" video essay. See `nhl/README.md`.
- **Sumo (`sumo/`)** — free community API (`sumo-api.com`, mirrors SumoDB). Every
  sekitori bout 1960-present (Makuuchi + Juryo) plus wrestler bios, **measurement
  change-points**, full rank history, and awards. Query **`bout_wrestler`**, the
  derived table: two rows per bout (one per wrestler's view) with physicals
  resolved **as-of** that tournament — never join a bout to a career-latest
  weight. Exclude `kimarite = 'fusen'` (forfeits, not contests). **Caveat:** win
  rate by *absolute* weight/BMI is rank-confounded; only the differential columns
  (`weight_adv`, …) are safe to read causally. See `sumo/README.md`.
- **Podcasts (`podcasts/`)** — folded in from the standalone `podcast-lab` folder
  2026-08-07. Semantic layer over podcasts: RSS ingest → free-first transcript
  waterfall (YouTube captions, faster-whisper fallback) → SQLite FTS →
  mention-count queries by year. `podcasts/data/` gitignored (nested
  `.gitignore`). See `podcasts/README.md`.
- **Trades (`trades/`)** — pure-logic (no DB) tool that turns an NBA draft-pick
  trade (protections, rolling conditions, swaps) into flowcharts / a slot map /
  an ownership board. Pipeline: `model` → `expand`/`board` → `render` (Mermaid,
  HTML, SVG). Real sourced deals in `real_2026.py`; `python -m trades --list`.
  Best view for a protected pick is the **slot strip** (`board.slot_strips` →
  `render.slot_strip_html`): every landing slot 1-30 colored by outcome. See
  `trades/README.md`.

## Conventions

- DBs live in `<sport>/data/` and are **gitignored** (regenerable from scrapers).
  Curated, costly-to-regen seeds (e.g. `pga/seeds/`) are committed.
- Queries are read-only — never mutate a DB during analysis.
- Free sources only by default; paid/hostile extraction is a deliberate exception
  (see `scrapekit/` for the credit-free web-extraction toolkit).
- `python db_dashboard.py --widget` / the `/db-dashboard` skill shows a live
  inventory of every DB.
- `sports_mcp.py` is a local **MCP server** (read-only `list_databases` /
  `describe_schema` / `run_sql`) registered as `sports-data` in the workspace
  `.mcp.json` — it lets any Claude surface query these DBs without shell access.
