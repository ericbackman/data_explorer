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
- **Betting (`betting/`)** — folded in from the `betting_stuff` repo 2026-07-01.
  Playwright FanDuel automation (login/odds/bet with confirm gate — see
  `betting/CLAUDE.md` for safety rules) + personal bet-history exports in
  `betting/raw/` (**gitignored: personal account data, local-only, NEVER
  commit**; second disk copy in `Github\_archive\betting_stuff\`). Creds in
  `betting/.eric.env` (gitignored).
- **Soccer betting UI (`sharp-edge/`)** — folded in 2026-07-01. Static no-vig/EV
  World Cup dashboard (vanilla JS, no build step). Own conventions in
  `sharp-edge/CLAUDE.md`; `lib/draw-signal.js` `shouldTakeDrawLive()` is Eric's
  to write.
- **Polymarket (`polymarket/`)** — folded in from `polymarket-diver` 2026-07-01.
  Read-only python clients (Gamma/CLOB/Data APIs) + rate limiter; used by the
  Iran-strikes insider-trading notebook. `from polymarket import GammaClient`
  works from repo root. See `polymarket/README.md`.

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
