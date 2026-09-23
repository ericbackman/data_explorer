# PLAYBOOK: data_explorer

> Operations manual. Read [CLAUDE.md](CLAUDE.md) / [OVERVIEW.md](OVERVIEW.md) first
> for context; this file is PROCEDURE.
> Tier rule: **Sonnet executes what's written here; Opus may change it (log why in
> §8); Eric approves anything public or irreversible.** Not covered here -> stop,
> leave a note, don't improvise.
>
> Provenance: created 2026-07-04 (Fable-week Track 5). See workspace
> [PLAYBOOKS.md](../PLAYBOOKS.md) for the doc-role model this follows.

## 1. System map

Local multi-sport SQLite platform. **Nothing here is scheduled.** Every op below
is operator-driven (Eric asks, or a session judges a refresh stale). No
AUTOMATION.md row exists for this repo.

- **Schema map:** [`SCHEMA.md`](SCHEMA.md), auto-generated, never hand-edit.
- **Query-time behavior:** [`CLAUDE.md`](CLAUDE.md) (SCHEMA.md -> read-only SQL ->
  validate vs known fact): don't duplicate that logic here.
- **Live query surface:** none registered. `sports_mcp.py` (read-only
  `list_databases`/`describe_schema`/`run_sql`) was registered as `sports-data`
  in the workspace `.mcp.json` but removed 2026-09-23 after it failed to
  connect from the Claude Code harness at every session start; see §4. The
  `sports-analyst` agent is the query surface now — it reads homebase
  directly, not this repo's stale fork.
- **DB inventory:** `python db_dashboard.py --widget` or `/db-dashboard` skill.
- **Main-checkout DBs** (`db_dashboard.py` MANIFEST): `nba/data/nba.db`,
  `nfl/data/nfl.db`, `nhl/data/nhl.db`, `mlb/data/mlb_draft.db`,
  `pga/data/pga.db`, `sumo/data/sumo.db`, root `nba_comebacks.db`. All gitignored.
  `nba_playoff_comebacks.db` is listed but absent.
- **Which copy is canonical.** NBA, NFL, NHL and MLB games live on homebase at
  `/opt/data/sports/<league>/data/<league>.db`, written daily at 06:10 by
  `sports-crons`, with freshness in `/opt/data/sports/_status/<league>.json`.
  The PC's `nba`/`nfl`/`nhl` DBs are a frozen fork copied during the 2026-09-20
  migration (mtimes reset to that day); the PC has no MLB game data. Measured
  2026-09-22: NFL on homebase runs to 2026-09-21, the PC fork to 2026-02-08; NBA
  and NHL still match because both leagues are in the offseason, and diverge in
  October. PGA, sumo, MLB draft, NBA comebacks and podcasts exist only on the PC
  with no scheduled writer. Full table and the tested ssh recipe:
  [`CLAUDE.md`](CLAUDE.md) "Which copy is canonical".
- **`sports_mcp.py` still reads the fork.** If ever re-registered, it resolves
  paths through the MANIFEST, so for NBA, NFL, NHL and MLB it would serve
  stale data until a sync from homebase exists. No sync job exists; adding one
  is Eric's call (§6). `sports-analyst` sidesteps this by reading homebase
  directly.
- **Branch state:** checkout is on `main`. The betting / sharp-edge / polymarket
  subtrees were split out to the private `betting-lab` repo on 2026-08-09 so this
  repo could be published; they are not here and should not come back.
- **Worktree DBs: gone.** The six worktrees this section used to protect
  (soccer, mlb, two NHL builds, a root `nfl.db`, `drafts.db`) no longer exist.
  Verified 2026-09-22: `git worktree list` shows only the main checkout,
  `.claude/worktrees/` does not exist, the migration staging copy
  `~/from-old-pc/stage-ignored/data_explorer` holds none of them, and a
  full-depth search of the PC profile (AppData and the iCloud folders excluded)
  and of homebase `/opt`, `/home/ericb` and `/tmp` (re-run in review,
  2026-09-22) finds no soccer, drafts or NHL play-by-play database. What that costs:
  - Soccer: the code is in `soccer/` on `main` and the DB rebuilds from ESPN
    (`python -m soccer.scrape`, see `soccer/README.md`). The only surviving data
    is `/opt/sleep-sports/vendor/soccer_slim.db` on homebase (548 KB,
    2026-07-20): FIFA World Cup 1930-2026, 1,068 matches, a sleep-sports extract.
  - MLB: superseded by homebase `mlb.db` (119,637 games from 1974).
  - NHL play-by-play: lost. The canonical `nhl.db` has an empty `plays` table on
    both machines, so `analysis/nhl_leafs_era.py`, which needed the worktree
    build (`plays` plus `team_games`), cannot run until play-by-play is rebuilt.
  - `drafts.db` and the worktree `nfl.db`: purpose was never confirmed; lost.
- **Downstream publishes (optional):** private Kaggle dataset (`kaggle/`),
  curated Supabase serving tables (`load_to_supabase.py`).

## 2. Health check: run first

```powershell
cd $env:USERPROFILE\Github\data_explorer
python db_dashboard.py --widget
```
**Expect:** inventory of every MANIFEST DB (size, mtime, table/row counts);
missing DBs listed explicitly, not silently dropped.

```powershell
git branch --show-current   # expect: main
git worktree list            # expect: the main checkout only (since 2026-09-22)
```
If the branch changed, note it, don't act (§6).

Then check the canonical copies on homebase: the coverage check in
[`CLAUDE.md`](CLAUDE.md) ("Querying homebase") prints each league's last final
game and `_status` fields, and refuses while any `-wal` file is non-empty.
**Expect:** `consecutive_failures` 0 and `last_success` from this morning for
any league in season (`skipped_out_of_season` explains an older one).

## 3. Operations

> **OP-1 and OP-2 refresh the PC fork, not the canonical copy.** `sports-crons`
> on homebase writes MLB daily since 2026-08-21 and NBA, NFL, NHL since
> 2026-09-14. A PC scrape makes the fork diverge further from homebase rather
> than catch it up; for a current answer, query homebase instead (OP-8).

### OP-1: NBA DB refresh
- **Trigger:** Eric asks / before betting analysis / current season stale.
- **Steps** (repo's own `.venv`, not `analysis/.venv`):
  ```powershell
  cd $env:USERPROFILE\Github\data_explorer
  .\.venv\Scripts\python.exe -m nba.scrape --seasons 1996-2026   # modern era, ~2 min
  # rarely: --seasons 1946-2026 (full history); --dry-run to preview; --force to rebuild
  ```
  Refetch policy always re-pulls current+prior season, skips older loaded ones:
  by design.
- **Verify:** `.\.venv\Scripts\python.exe -m pytest nba/` all green, then
  spot-check one known recent game score per CLAUDE.md's validation rule.
- **If it fails:** interrupted run -> re-run identical command (idempotent
  upserts resume free). Suspected stale data -> `--force`. Else -> §4.

### OP-2: NFL DB refresh
- **Trigger:** Eric asks / new season weeks landed.
- **Pre-flight:** no `nfl/README.md`: commands below are from the
  `nfl/pull.py`/`nfl/historical.py` docstrings, verified against the code.
- **Steps:**
  ```powershell
  cd $env:USERPROFILE\Github\data_explorer
  python -m nfl.pull --datasets schedules,player_stats,team_stats   # box scores
  python -m nfl.pull --datasets pbp                                 # play-by-play
  python -m nfl.historical   # one-shot: 1966-1998 Spreadspoke backfill, rarely re-run
  ```
- **Verify:** sanity-check row counts, then validate one famous game score.
  (Rough baseline through 2025 from session memory, not repo-verifiable: ~7,276
  games / ~476K player-games: recheck via `SELECT COUNT(*) FROM games` if unsure.)
- **If it fails:** pre-1999 season -> auto-clamped to `EARLIEST_SEASON=1999`
  with a warning, expected. Column-set drift across seasons -> `load_season()`
  already ALTER-ADDs + delete-then-inserts per season, don't "fix" it.
  1920-1965 requested -> no free source (PFR anti-bot walled); don't attempt
  without Eric's explicit Firecrawl decision (§7).

### OP-3: PGA DB refresh (tiered)
- **Trigger:** Eric asks / after a major.
- **Steps** (repo root, per `pga/README.md`):
  ```powershell
  python -m pga.scrape --seasons 2005-2026        # Tier 1: ESPN full-field
  python -m pga.holes_scrape --seasons 2005-2026  # Tier 1h: hole-by-hole, cache-only
  python -m pga.bios_scrape                       # Tier 1b: bios
  python -m pga.sg build                          # Tier 1s: strokes-gained
  python -m pga.tier2_scrapekit collect --start 1960 --end 2004   # Tier 2: majors, free
  python -m pga.tier2 load seeds/major_history_seed.json
  ```
- **Verify:** `python -m pytest pga/` green + known facts: Nicklaus = 18 majors;
  Scheffler #1 in 2024 Masters SG order; 54-hole major leader ~53% (266 majors).
- **If it fails:** pre-2005 in Tier 1 -> ESPN has no data before 2005 (expected;
  use Tier 2). Leader-conversion % looks inflated -> co-leader over-counting;
  `tier2_scrapekit`'s `Place`-column read already fixes this, don't re-derive.
  Tier-2 page defeats the parser -> `pga/tier2_firecrawl.py` fallback exists but
  needs a deliberate Eric paid-extraction decision (§7), not a default.

### OP-4: SCHEMA.md regeneration (mandatory after ANY refresh)
- **Steps:** `python schema_doc.py`
- **Verify:** `git diff SCHEMA.md` shows the new tables/counts; `db_dashboard.py
  --widget` inventory matches disk.
- **If it fails:** DB missing from output -> add a line to `MANIFEST` in
  `db_dashboard.py` (schema_doc.py imports it directly).

### OP-5: Kaggle dataset push: prerequisites not yet met
- **Trigger:** after a refresh worth publishing.
- **Pre-flight (incomplete, owner action required):** needs (1) API token at
  `$env:USERPROFILE\.kaggle\kaggle.json`, (2) `kaggle==1.6.17` pinned (already in
  `analysis/.venv`: default `pip install kaggle` is broken on import, don't let
  it drift), (3) `fingerprint()` implemented in `kaggle/push_datasets.py`
  (stub; `kaggle/tests/test_fingerprint.py` is red by design until written).
  **Owner action required: create the token, run the first `--create` push, and
  implement `fingerprint()`. An agent must never create accounts or API tokens on
  the owner's behalf.**
- **Steps (once met):**
  ```powershell
  $py = "$env:USERPROFILE\Github\data_explorer\analysis\.venv\Scripts\python.exe"
  cd $env:USERPROFILE\Github\data_explorer\kaggle
  & $py push_datasets.py --create                          # FIRST push only
  & $py push_datasets.py -m "refresh nba through 2026-07"   # subsequent
  ```
- **Verify:** prints `Done. Dataset (PRIVATE): https://www.kaggle.com/datasets/<you>/sports-dbs`: open it, confirm **Private** badge (§7). In-notebook: `sportsdb.databases()` lists all DBs.
- **If it fails:** see troubleshooting table in `kaggle/SETUP.md` (missing
  `kaggle.json`, 401, `kagglesdk` import error, 409 on `--create`). Dirty
  SQLite typing already handled (`build_duckdb.py` `TRY_CAST`s to NULL).

### OP-6: Supabase serving-table load
- **Pre-flight:** `~\.config\supabase.env` must hold `pooler_url`: never inline it.
- **Steps:** `python load_to_supabase.py <sqlite_path> <src_table> <dest_table>`
- **Verify:** prints `Loaded into Supabase public.<dest_table>: <N> rows`; `<N>`
  matches the printed source row count.
- **If it fails:** blank/whitespace numeric cells already coerced to NULL
  (`make_conv()`) before COPY — don't re-solve, it's handled.

### OP-7: scrapekit web extraction (used by OP-3 Tier 2 + ad hoc enrichment)
- **Escalation ladder, cheapest first** (`scrapekit/extract.py`):
  1. `Extractor.read_tables()`: parser-first `pandas.read_html` over cached HTML.
  2. `ParseError`/empty result -> `extract_with_fallback()` drops to local
     Ollama (`qwen2.5:7b`, `http://localhost:11434`; install hint in-module).
  3. Firecrawl: last resort, a deliberate paid decision, never a reflex.
- **Verify:** extracted tables spot-checked vs the live page; fetches disk-cached.
- **If it fails:** 403 on a non-browser UA -> already sends a real browser UA, handled.

### OP-8: Homebase read path (NBA / NFL / NHL / MLB games)
- **Trigger:** any NBA, NFL, NHL or MLB game or stat question.
- **Steps:** paste the recipe in [`CLAUDE.md`](CLAUDE.md) ("Querying homebase"):
  `ssh homebase python3 -` with the Python on stdin, opening
  `file:/opt/data/sports/<league>/data/<league>.db?mode=ro&immutable=1`. Run the
  coverage check in the same session and report the league's last final
  date with the answer.
- **Verify:** the known-fact check from CLAUDE.md, plus `_status/<league>.json`
  showing `consecutive_failures` 0.
- **If it fails:** `attempt to write a readonly database` -> the URI lacks
  `immutable=1` (§4). Recipe exits on a non-empty `-wal` -> `sports-crons` is
  mid-write; retry after 06:30. ssh unreachable -> answer from the PC fork and
  say so, with the fork's measured last date. Soccer questions: no soccer DB
  exists (§1).

### OP-9: Answering a sports question (reference only, fully covered elsewhere)
See [`CLAUDE.md`](CLAUDE.md) (SCHEMA.md -> read-only SQL -> validate) and
[`analysis/README.md`](analysis/README.md) (uv + DuckDB via `sportsdb.py`:
`sportsdb.q()`/`pl()`, aliases `nba`/`nfl`/`pga`). Never skip the
known-fact validation step, on any surface.

## 4. Failure modes & recovery

| Symptom | Cause | Fix | Verify |
|---|---|---|---|
| Scrape run interrupted | Network drop mid-backfill | Re-run identical command: idempotent upserts resume free | Row counts match, `pytest` green |
| NFL loader errors across seasons | nflverse column sets differ year to year | Already handled: `load_season()` ALTER-ADDs union, missing->NULL — don't patch | New season present, old unaffected |
| Golf leader-conversion % too high | Co-leaders double-counted | Already handled: `tier2_scrapekit` reads `Place` to isolate solo leaders | 54-hole major leader ~53%, stable across eras |
| `ModuleNotFoundError: kagglesdk` | Default `pip install kaggle` broke import | Reinstall `kaggle==1.6.17` in `analysis/.venv` | `pip show kaggle` -> `1.6.17` |
| Kaggle push re-uploads full ~6GB every time | `fingerprint()` unimplemented | Pending Eric (OP-5): don't implement yourself | `pytest -q` in `kaggle/` still red |
| Supabase COPY rejects a row | Blank/whitespace in numeric SQLite column | Already handled: `make_conv()` -> NULL before COPY | Load completes, row count matches |
| "MLB games DB doesn't exist" | MLB game data is on homebase only; the PC has `mlb_draft.db` | Query homebase `mlb.db` (OP-8) | Coverage check prints an `mlb` last final date |
| "soccer DB doesn't exist" | The worktree that held it is gone (§1) | Rebuild with `python -m soccer.scrape` if Eric wants it; `soccer_slim.db` on homebase covers World Cup matches only | `soccer/data/*.db` present |
| `attempt to write a readonly database` on homebase | WAL-mode DB in a root-owned dir: `ericb` cannot create `-shm` under plain `?mode=ro` | Open `?mode=ro&immutable=1` with the `-wal` guard (CLAUDE.md recipe) | Query returns rows |
| MCP `sports-data` won't connect | Not a config bug: removed from `.mcp.json` 2026-09-23 after it failed at every session start even with a correct `mcp<2` venv (the script handshakes fine standalone — the failure was harness-spawn-specific and wasn't reproduced outside it) | Use the `sports-analyst` agent instead (reads homebase, not this repo's fork). To re-enable `sports_mcp.py`: re-add the `sports-data` block to `.mcp.json`, and first confirm `.venv\Scripts\python.exe -c "import sports_mcp"` exits 0 (needs `mcp<2`; mcp 2.x renames `FastMCP` and the import dies) | `sports-analyst` answers the question |
| Site 403s the scraper | Site rejects non-browser clients | `scrapekit` now identifies honestly by DEFAULT. Presenting as a browser is opt-in via `SCRAPEKIT_USER_AGENT`: check the target's robots.txt/terms FIRST; some sites prohibit automated access outright and a spoofed UA does not change that | Fetch succeeds, cached to disk |

## 5. Tuning knobs

| Param | Where | Current | Notes | Owner |
|---|---|---|---|---|
| NBA season range / `--force` / `--dry-run` | `nba/scrape.py` CLI args | `1996-2026` typical | `--force` = full rebuild, expensive | agent |
| NFL `--datasets` / `--seasons` | `nfl/pull.py` `DATASETS` + CLI | `schedules,player_stats,team_stats`, `1999-2025` | Floor `EARLIEST_SEASON=1999`, auto-clamped | agent |
| Kaggle dataset contents | `SOURCES` dict in `kaggle/push_datasets.py` | nba/nfl/pga | Add one line to `SOURCES`, then re-push (its docstring says so) | agent |
| Analysis attached DBs | `MANIFEST` in `analysis/sportsdb.py` | nba, nfl, pga | Add a line, `connect(refresh=True)` | agent |
| scrapekit politeness/retry | `scrapekit/extract.py` constants | `MIN_INTERVAL_S=0.5`, `MAX_RETRIES=4`, `TIMEOUT_S=30` | Lower interval only for known-friendly APIs | agent |
| `fingerprint(db_path)` strategy | `kaggle/push_datasets.py` stub; tests `kaggle/tests/test_fingerprint.py` | unimplemented (red) | Must be content-based, not mtime | **Eric.** Propose, never implement unasked |
| `classify_leader_outcome()` tie/playoff def | pga analysis module (`pga/README.md`) | documented baseline ships | Moves the headline %; a judgment call | **Eric.** Propose, don't silently change |

## 6. Escalate to Eric (stop conditions)

- Known-fact validation fails on a refresh (e.g. Nicklaus != 18 majors): stop;
  don't push suspect data to Kaggle/Supabase.
- A source API changes shape beyond the drift already handled (ESPN golf JSON,
  nba_api, nflverse) requiring scraper redesign — Opus/Eric territory.
- Kaggle first push: token + `--create` are pending Eric (OP-5), don't create
  accounts/tokens on his behalf.
- A sync from homebase to the PC fork (so the MCP server and PC analysis see
  current NBA/NFL/NHL/MLB data) is a scheduled-job change: propose it, never
  register it.
- Rebuilding the lost soccer DB or NHL play-by-play: a multi-hour scrape and a
  choice of where the canonical copy lives; Eric's call.

## 7. Do-not list

- **Never** mutate a DB during analysis: read-only always; `<sport>/data/` is
  gitignored, never force-add.
- **Never** write to the homebase databases or `_status/` files; they belong to
  `sports-crons`. Reads only, `?mode=ro&immutable=1`.
- **Never** answer an NBA, NFL, NHL or MLB question from the PC fork without
  saying so and giving the fork's measured last date.
- **Never** let the Kaggle dataset go public: confirm **Private** after every `--create`.
- **Never** default to Firecrawl/paid extraction: free sources first; paid is
  a deliberate exception, never a reflex.
- **Never** push raw/full DBs to Supabase: curated serving tables only; creds
  stay in `~\.config\supabase.env`, never inline.
- **Never** skip `python schema_doc.py` after a refresh, and never hand-edit `SCHEMA.md`.

## 8. Maintenance

Update this playbook in the SAME change as any operation change.

- 2026-09-22: pointed the read path at homebase. Its `sports-crons` databases
  are canonical for NBA/NFL/NHL/MLB and the PC copies are a frozen fork from the
  2026-09-20 migration (NFL 2026-02-08 vs 2026-09-21 on homebase; no MLB games on
  the PC). Tested the ssh recipe from Git Bash and PowerShell; plain `mode=ro`
  fails on the WAL-mode files, so it opens `immutable=1` behind a `-wal` guard.
  Replaced the TRIBAL worktree section: all six worktrees are gone and none of
  their DBs survives (§1). Rebuilt `.venv` for the MCP server with `mcp<2`.
  Review moved the homebase section of SCHEMA.md into `schema_doc.py` (a static
  block) so OP-4 keeps it, and both recipes now re-check `-wal` after reading.

- 2026-09-14: NBA scrape now pulls the `PlayIn` season type (2020-21 on) and
  orients neutral-site games from BoxScoreSummaryV3; nfl/pull.py quotes drifted
  column names (PR #4). Verified by re-scraping 2020-21..2025-26 with `--force`:
  `games` equals distinct `team_game` games in all 80 seasons, 36 play-in and 10
  neutral-site games added. sports-crons vendors `nba/client.py`, `nba/parse.py`
  and `nfl/pull.py` byte-identical and needs a re-sync PR.

- 2026-08-09: betting / sharp-edge / polymarket split out to the private
  `betting-lab` repo (with `nba/exec_scrape.py`) so this repo can be published;
  their operating rules moved to that repo's playbook. Removed the dangling
  pre-fold `betting_stuff/data/odds_history.db` MANIFEST entry (the open question
  in §4/§6 is resolved by deletion: the DB never existed here). Corrected the
  §4 scrapekit row: the default UA now identifies the project, browser spoofing
  is opt-in. Answered the open NHL-canonical question with measured row
  counts (§1): three copies are different builds, not duplicates.

- 2026-07-04: created (Fable-week Track 5), grounded against the live repo:
  verified branch (`feature/fold-betting-projects`), all scrape entrypoints, and
  flagged a real MANIFEST path drift (`betting_stuff/data/odds_history.db`
  post-fold) as an open question.
- 2026-07-04: corrected after adversarial verify: all **6** worktrees enumerated
  (prior draft saw only 2 and wrongly said NHL was missing). NHL DB exists in two
  worktrees at different sizes (duplication → which is canonical was unresolved); extra root
  `nfl.db` (432 MB) + `drafts.db` (22 MB) noted, purpose unconfirmed. Kaggle knob
  corrected (`SOURCES` only, no `kaggle_sportsdb.py` MANIFEST).
