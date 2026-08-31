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
- **Live query surface:** `sports_mcp.py`, registered as `sports-data` in the
  workspace `.mcp.json` (`command`=`data_explorer/.venv/Scripts/python.exe`,
  `cwd`=`data_explorer/`): read-only `list_databases`/`describe_schema`/`run_sql`.
- **DB inventory:** `python db_dashboard.py --widget` or `/db-dashboard` skill.
- **Main-checkout DBs** (`db_dashboard.py` MANIFEST): `nba/data/nba.db`,
  `nfl/data/nfl.db`, `pga/data/pga.db`, root `nba_comebacks.db` /
  `nba_playoff_comebacks.db`. All gitignored, regenerable.
- **Branch state:** checkout is on `main`. The betting / sharp-edge / polymarket
  subtrees were split out to the private `betting-lab` repo on 2026-08-09 so this
  repo could be published; they are not here and should not come back.
- **Worktree DBs: TRIBAL, do not prune** (6 worktrees; run `git worktree list`).
  Branches unmerged, data gitignored: no other copy exists on disk:
  - `elegant-lamport-1d5555/soccer/`: soccer DB
  - `laughing-hugle-e9875d/mlb/`: mlb DB
  - `zen-turing-c1e6df/nhl.db` (11 MB) **and** `gracious-antonelli-777d65/nhl.db`
    RESOLVED 2026-08-09: the three NHL copies are different BUILDS, not
    duplicates, so "which is canonical" depends on what you need:
      * `nhl/data/nhl.db` (348 MB) is canonical for everything box-score:
        70,352 games (1997-2026), 2.43M skater rows, drafts, playoff_series.
        Schema uses `team_game` (SINGULAR). Its `plays` table exists but is EMPTY.
      * `gracious-antonelli-777d65/nhl.db` (9 MB) is the ONLY play-by-play source
        (29,710 `plays` over 7,085 games) and uses `team_games` (PLURAL): a
        different schema, NOT a drop-in. `analysis/nhl_leafs_era.py` needs this one.
      * `zen-turing-c1e6df/nhl.db` (11 MB) is a partial backfill superseded by the
        canonical build (36,012 games but only 2,850 team_game / 51,300 skater
        rows). Prunable once the owner confirms: no unique data found in it.
  - `gracious-antonelli-777d65/nhl.db` shares that worktree with a root-level
    `nfl.db` (432 MB), distinct from the main checkout's `nfl/data/nfl.db`:
    purpose unidentified; do not prune until someone confirms what it is.
  - `pedantic-meninsky-e2fee8/drafts.db` (22 MB): likely the `trades/` draft-pick
    data; unconfirmed. Do not prune until someone confirms what it is.
  - `epic-faraday-73f136`: parallel full checkout, no unique DB; don't prune blind.
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
git worktree list            # expect: 6 worktrees (soccer/mlb/nhl×2/nfl/drafts + epic-faraday)
```
If the branch changed, note it, don't act (§6). If a sport worktree row is
missing, **stop.** See §7 (data is gitignored and unrecoverable).

## 3. Operations

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

### OP-8: Worktree sport DBs (soccer / mlb / nhl): read only, never prune
- **Trigger:** a soccer, MLB, or NHL question arrives.
- **Steps:** `cd` into the specific worktree before querying, the main
  checkout has no soccer/mlb/nhl tables:
  ```powershell
  cd $env:USERPROFILE\Github\data_explorer\.claude\worktrees\elegant-lamport-1d5555\soccer
  cd $env:USERPROFILE\Github\data_explorer\.claude\worktrees\laughing-hugle-e9875d\mlb
  # NHL: two copies exist — use zen-turing (11 MB) as the working copy:
  cd $env:USERPROFILE\Github\data_explorer\.claude\worktrees\zen-turing-c1e6df
  ```
- **Verify:** sport dir + `data/*.db` (or root `nhl.db`) present under that worktree.
- **If it fails:** "DB doesn't exist" -> wrong location (§4). For NHL, confirm
  which build you need before trusting results: box scores vs play-by-play use
  different copies with different schemas (§6).

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
| "soccer/MLB DB doesn't exist" | Searched main checkout, not the worktree | Re-run in the correct worktree (OP-8). NHL box scores ARE in main (`nhl/data/nhl.db`); only play-by-play lives in a worktree (§1) | `data/*.db` found under that worktree |
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
- Merging any soccer/mlb/nhl worktree branch: branch strategy is Eric's call.
- Pruning `.claude/worktrees/zen-turing-c1e6df`: its NHL copy looks superseded
  by the canonical build (§1) but deleting data is Eric's call, not an agent's.

## 7. Do-not list

- **Never** mutate a DB during analysis: read-only always; `<sport>/data/` is
  gitignored, never force-add.
- **Never** prune `.claude/worktrees/elegant-lamport-1d5555` or
  `laughing-hugle-e9875d`: only local copies of the soccer/mlb DBs, unrecoverable if deleted.
- **Never** let the Kaggle dataset go public: confirm **Private** after every `--create`.
- **Never** default to Firecrawl/paid extraction: free sources first; paid is
  a deliberate exception, never a reflex.
- **Never** push raw/full DBs to Supabase: curated serving tables only; creds
  stay in `~\.config\supabase.env`, never inline.
- **Never** skip `python schema_doc.py` after a refresh, and never hand-edit `SCHEMA.md`.

## 8. Maintenance

Update this playbook in the SAME change as any operation change.

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
