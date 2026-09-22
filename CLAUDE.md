# data_explorer: multi-sport data platform

Local SQLite databases for answering sports questions in plain English. Each sport
is a sub-project mirroring the same pattern (`nba/`, `pga/`, `nfl/`, …): a cached
scraper, a normalized schema, and analysis modules. Run python from this repo root
(e.g. `python -m pga.sg ...`).

## Which copy is canonical

For NBA, NFL, NHL and MLB games and stats, the canonical databases are on
homebase, written daily at 06:10 by `sports-crons`. The same-named files in this
repo are a frozen fork: they were copied from the old PC during the 2026-09-20
migration, which reset their mtimes to that day, so the file date says nothing
about the data, and no scheduled job writes them. Measured 2026-09-22:

| Data | Canonical copy | Last final game | Write path |
|---|---|---|---|
| NBA | homebase `/opt/data/sports/nba/data/nba.db` (3.79 GB) | 2026-06-13. The PC fork matches only because it is the offseason; they diverge when the 2026-27 season starts in October | sports-crons |
| NFL | homebase `/opt/data/sports/nfl/data/nfl.db` (2.42 GB) | 2026-09-21, 32 of 272 games of 2026 final. The PC fork ends at Super Bowl LX, 2026-02-08 | sports-crons |
| NHL | homebase `/opt/data/sports/nhl/data/nhl.db` (348 MB) | 2026-06-14. Same offseason caveat as NBA | sports-crons |
| MLB games | homebase `/opt/data/sports/mlb/data/mlb.db` (394 MB) | 2026-09-21, 119,637 games 1974-2026. The PC has no MLB game data at all | sports-crons |
| MLB draft + careers | PC `mlb/data/mlb_draft.db` | drafts through 2025 | none |
| PGA | PC `pga/data/pga.db` | the 2026 U.S. Open, ended 2026-06-21 | none; manual (PLAYBOOK OP-3) |
| Sumo | PC `sumo/data/sumo.db` | July 2026 basho, ended 2026-07-26 | none; manual |
| NBA comebacks, podcasts | PC `nba_comebacks.db`, `podcasts/data/podcasts.db` | derived or ad hoc | none |
| OSRS | none: `osrs/data/osrs.db` was absent on the PC on 2026-09-22 | n/a | none |

Freshness markers live beside the homebase data at
`/opt/data/sports/_status/<league>.json`: `last_success`, `consecutive_failures`,
`outcome` and `last_result`. An `outcome` of `skipped_out_of_season` means an old
`last_success` is expected (NBA read 2026-09-14 on 2026-09-22).

The `sports-data` MCP server (`sports_mcp.py`) reads the PC fork through
`db_dashboard.py`'s MANIFEST, so its NBA, NFL, NHL answers are stale for those
leagues and it has no MLB game data, until a sync from homebase exists.

### Querying homebase (read-only)

`ssh homebase` lands as `ericb`, has python3 with sqlite3 3.45.1, and has no
`sqlite3` CLI. All four databases are WAL-mode files in root-owned directories,
so plain `?mode=ro` fails with `attempt to write a readonly database` on NFL, NHL
and MLB: `ericb` cannot create the `-shm` file. Open with
`?mode=ro&immutable=1` instead. `immutable` also skips locking, so the recipe
refuses when a non-empty `-wal` file shows a writer mid-run; avoid 06:10 to
06:30 local. From Git Bash (tested 2026-09-22):

```bash
ssh homebase python3 - <<'PY'
import os, sqlite3, sys
LEAGUE = "nfl"   # nba | nfl | nhl | mlb
DB = f"/opt/data/sports/{LEAGUE}/data/{LEAGUE}.db"
WAL = DB + "-wal"
if os.path.exists(WAL) and os.path.getsize(WAL) > 0:
    sys.exit(f"{WAL} holds {os.path.getsize(WAL)} bytes: sports-crons is mid-write. Retry later.")
con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
con.execute("PRAGMA query_only = ON")
SQL = """
SELECT gameday, away_team, away_score, home_team, home_score
FROM games WHERE home_score IS NOT NULL
ORDER BY gameday DESC LIMIT 5
"""
for row in con.execute(SQL).fetchmany(200):
    print(row)
PY
```

The heredoc is local and quoted, so neither shell expands anything in the
Python. From PowerShell, pipe the same body in a single-quoted here-string:
`@'` on its own line, the Python, `'@` at column 0, then `| ssh homebase python3 -`.

Coverage and freshness for all four leagues in one line (same line works in
PowerShell as `'<python>' | ssh homebase python3 -`):

```bash
ssh homebase python3 - <<< 'import sqlite3,json,os; P="/opt/data/sports"; D={"nba":("game_date","home_pts"),"nfl":("gameday","home_score"),"nhl":("date","home_score"),"mlb":("game_date","home_score")}; [print(l, "max_final", sqlite3.connect(f"file:{P}/{l}/data/{l}.db?mode=ro&immutable=1", uri=True).execute(f"SELECT MAX({d}) FROM games WHERE {s} IS NOT NULL").fetchone()[0], "wal_bytes", os.path.getsize(f"{P}/{l}/data/{l}.db-wal") if os.path.exists(f"{P}/{l}/data/{l}.db-wal") else 0, {k: json.load(open(f"{P}/_status/{l}.json")).get(k) for k in ("last_success","consecutive_failures","outcome")}) for l,(d,s) in D.items()]'
```

Filter on a non-NULL score: NFL, NHL and MLB `games` also hold scheduled and
postponed rows (NFL 2026 lists games through 2027-01-10). Homebase schemas match
the PC tables for NBA and NHL; NFL `player_game` and `team_game` carry 35 extra
columns on homebase. The MLB game schema exists only on homebase and is listed in
[`SCHEMA.md`](SCHEMA.md).

## Answering a sports question: ALWAYS do this when asked one

1. **Read [`SCHEMA.md`](SCHEMA.md)** for the exact tables/columns: never guess
   column names. It's auto-generated from the PC copies; the homebase MLB game
   schema is in its header section.
2. Pick the database for the sport. NBA, NFL, NHL and MLB games go to homebase
   (recipe above); the rest are on the PC. Query **read-only** with python + sqlite3.
   If homebase is unreachable, use the PC fork and say so, with the fork's
   measured last date.
3. **Validate** before reporting: check the answer against a known fact (a famous
   result or number). If a derived stat disagrees with reality, suspect the query
   or the data, not reality. A famous old fact cannot catch staleness, so also
   report the measured last date and the league's `_status` freshness.
4. Prefer the existing analysis modules when one fits (they encode the right
   definitions); drop to raw SQL for anything novel.
5. After adding/refreshing data, regenerate the map: `python schema_doc.py`.

## Per-sport notes

- **Golf (`pga/`).** Events → results → rounds → **holes (7M)** → **bios** →
  **strokes-gained**, plus majors 1960-2004 (`major_history`). For "who played
  best", prefer **SG-Total** (`hole_field_avg` baseline) over finishing position.
  Modules: `analysis` (leader conversion), `betting` (course history / form /
  closers / comebacks), `holes` (hole & course difficulty, par-3/4/5 splits),
  `sg` (strokes-gained), `tier2` (deep majors). See `pga/README.md`.
- **NBA (`nba/`).** Box scores from 1946 (nba_api). See `nba/README.md`.
- **NFL (`nfl/`).** Nflverse box scores + play-by-play from 1999.
- **NHL (`nhl/`).** Free NHL API (`api-web.nhle.com`). Game index from 1997;
  skater/goalie box scores (RTSS era 1997+); resumable `--team-id` backfill.
  `playoff_series` is derived (round + Game-7 + blown-lead flags). Built for the
  Leafs "Plan the Parade" video essay. See `nhl/README.md`.
- **Sumo (`sumo/`).** Free community API (`sumo-api.com`, mirrors SumoDB). Every
  sekitori bout from 1960 (the PC copy ends at the July 2026 basho) (Makuuchi + Juryo) plus wrestler bios, **measurement
  change-points, full rank history, and awards. Query `bout_wrestler`**, the
  derived table: two rows per bout (one per wrestler's view) with physicals
  resolved **as-of** that tournament: never join a bout to a career-latest
  weight. Exclude `kimarite = 'fusen'` (forfeits, not contests). **Caveat:** win
  rate by *absolute* weight/BMI is rank-confounded; only the differential columns
  (`weight_adv`, …) are safe to read causally. See `sumo/README.md`.
- **Podcasts (`podcasts/`).** Folded in from the standalone `podcast-lab` folder
  2026-08-07. Semantic layer over podcasts: RSS ingest → free-first transcript
  waterfall (YouTube captions, faster-whisper fallback) → SQLite FTS →
  mention-count queries by year. `podcasts/data/` gitignored (nested
  `.gitignore`). See `podcasts/README.md`.
- **NBA CBA (`cba/`).** Folded in from the standalone `nba-cba` repo 2026-08-30.
  An agentic knowledge layer over the Collective Bargaining Agreement: ask a cap
  question in plain English and get an answer that **routes to and quotes the
  governing text** instead of hallucinating cap rules. `semantic/` holds the
  DERIVED navigation artifacts (Article/Section → corpus line + page, an 88-term
  Article I glossary, the §2(e)(4) second-apron hard-cap table) for both the 2017
  and 2023 agreements, so `tools/diff_cbas.py` can show what actually changed.
  `trade-machine/` is a separate TS trade-legality engine + Vite app: **not** the
  same thing as `trades/` below, which is about draft-pick protections; this one
  is about whether a trade is legal under the apron rules.
  ⚠ **`cba/corpus/` (PDFs + extracted text) is © NBA/NBPA and is gitignored via a
  nested `.gitignore`**: the same pattern as `podcasts/data/`, but load-bearing
  here in a way it was not in the standalone repo, because this repo is public.
  Re-download it with `python cba/tools/fetch_cba.py`; commit only derived analysis.
  Tools resolve paths `__file__`-relative, so they run from anywhere. See `cba/README.md`.
- **Trades (`trades/`).** Pure-logic (no DB) tool that turns an NBA draft-pick
  trade (protections, rolling conditions, swaps) into flowcharts / a slot map /
  an ownership board. Pipeline: `model` → `expand`/`board` → `render` (Mermaid,
  HTML, SVG). Real sourced deals in `real_2026.py`; `python -m trades --list`.
  Best view for a protected pick is the slot strip (`board.slot_strips` →
  `render.slot_strip_html`): every landing slot 1-30 colored by outcome. See
  `trades/README.md`.

## Conventions

- DBs live in `<sport>/data/` and are gitignored (regenerable from scrapers).
  Curated, costly-to-regen seeds (e.g. `pga/seeds/`) are committed.
- Queries are read-only: never mutate a DB during analysis.
- Free sources only by default; paid/hostile extraction is a deliberate exception
  (see `scrapekit/` for the credit-free web-extraction toolkit).
- `python db_dashboard.py --widget` / the `/db-dashboard` skill shows a live
  inventory of every DB.
- `sports_mcp.py` is a local MCP server (read-only `list_databases` /
  `describe_schema` / `run_sql`) registered as `sports-data` in the workspace
  `.mcp.json`: it lets any Claude surface query these DBs without shell access.
  It reads the PC copies only, so for NBA, NFL, NHL and MLB it serves the stale
  fork (see "Which copy is canonical"). It needs `mcp<2`: mcp 2.x renamed
  `FastMCP`, and the server dies on import under it. The venv rebuilt on
  2026-09-22 holds mcp 1.30.0, but `requirements.txt` still says bare `mcp`.
