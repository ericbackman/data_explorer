# PLAYBOOK — data_explorer

> Operations manual. Read [CLAUDE.md](CLAUDE.md) / [OVERVIEW.md](OVERVIEW.md) first
> for context; this file is PROCEDURE.
> Tier rule: **Sonnet executes what's written here; Opus may change it (log why in
> §8); Eric approves anything public or irreversible.** Not covered here -> stop,
> leave a note, don't improvise.
>
> Provenance: created 2026-07-04 (Fable-week Track 5). See workspace
> [PLAYBOOKS.md](../PLAYBOOKS.md) for the doc-role model this follows.

## 1. System map

Local multi-sport SQLite platform. **Nothing here is scheduled** — every op below
is operator-driven (Eric asks, or a session judges a refresh stale). No
AUTOMATION.md row exists for this repo.

- **Schema map:** [`SCHEMA.md`](SCHEMA.md) — auto-generated, never hand-edit.
- **Query-time behavior:** [`CLAUDE.md`](CLAUDE.md) (SCHEMA.md -> read-only SQL ->
  validate vs known fact) — don't duplicate that logic here.
- **Live query surface:** `sports_mcp.py`, registered as `sports-data` in the
  workspace `.mcp.json` (`command`=`data_explorer/.venv/Scripts/python.exe`,
  `cwd`=`data_explorer/`) — read-only `list_databases`/`describe_schema`/`run_sql`.
- **DB inventory:** `python db_dashboard.py --widget` or `/db-dashboard` skill.
- **Main-checkout DBs** (`db_dashboard.py` MANIFEST): `nba/data/nba.db`,
  `nfl/data/nfl.db`, `pga/data/pga.db`, root `nba_comebacks.db` /
  `nba_playoff_comebacks.db`. All gitignored, regenerable.
- **Branch state:** checkout is on `feature/fold-betting-projects` (verified),
  not master. `betting/`, `sharp-edge/`, `polymarket/` folded in 2026-07-01.
- **Worktree DBs — TRIBAL, do not prune** (6 worktrees; run `git worktree list`).
  Branches unmerged, data gitignored — no other copy exists on disk:
  - `elegant-lamport-1d5555/soccer/` — soccer DB
  - `laughing-hugle-e9875d/mlb/` — mlb DB
  - `zen-turing-c1e6df/nhl.db` (11 MB) **and** `gracious-antonelli-777d65/nhl.db`
    (8.7 MB) — NHL data exists in **two** worktrees at different sizes.
    `TODO(Eric): which NHL copy is canonical?` Until answered, treat zen-turing
    (larger) as the working copy but don't trust either for betting.
  - `gracious-antonelli-777d65/nhl.db` shares that worktree with a root-level
    `nfl.db` (432 MB), distinct from the main checkout's `nfl/data/nfl.db` —
    purpose unconfirmed. `TODO(Eric).`
  - `pedantic-meninsky-e2fee8/drafts.db` (22 MB) — likely the `trades/` draft-pick
    data; purpose unconfirmed. `TODO(Eric).`
  - `epic-faraday-73f136` — parallel full checkout, no unique DB; don't prune blind.
- **Downstream publishes (optional):** private Kaggle dataset (`kaggle/`),
  curated Supabase serving tables (`load_to_supabase.py`).

## 2. Health check — run first

```powershell
cd C:\Users\ericb\Github\data_explorer
python db_dashboard.py --widget
```
**Expect:** inventory of every MANIFEST DB (size, mtime, table/row counts);
missing DBs listed explicitly, not silently dropped.

```powershell
git branch --show-current   # expect: feature/fold-betting-projects
git worktree list            # expect: 6 worktrees (soccer/mlb/nhl×2/nfl/drafts + epic-faraday)
```
If the branch changed, note it, don't act (§6). If a sport worktree row is
missing, **stop** — see §7 (data is gitignored and unrecoverable).

## 3. Operations

### OP-1: NBA DB refresh
- **Trigger:** Eric asks / before betting analysis / current season stale.
- **Steps** (repo's own `.venv`, not `analysis/.venv`):
  ```powershell
  cd C:\Users\ericb\Github\data_explorer
  .\.venv\Scripts\python.exe -m nba.scrape --seasons 1996-2026   # modern era, ~2 min
  # rarely: --seasons 1946-2026 (full history); --dry-run to preview; --force to rebuild
  ```
  Refetch policy always re-pulls current+prior season, skips older loaded ones —
  by design.
- **Verify:** `.\.venv\Scripts\python.exe -m pytest nba/` all green, then
  spot-check one known recent game score per CLAUDE.md's validation rule.
- **If it fails:** interrupted run -> re-run identical command (idempotent
  upserts resume free). Suspected stale data -> `--force`. Else -> §4.

### OP-2: NFL DB refresh
- **Trigger:** Eric asks / new season weeks landed.
- **Pre-flight:** no `nfl/README.md` — commands below are from the
  `nfl/pull.py`/`nfl/historical.py` docstrings, verified against the code.
- **Steps:**
  ```powershell
  cd C:\Users\ericb\Github\data_explorer
  python -m nfl.pull --datasets schedules,player_stats,team_stats   # box scores
  python -m nfl.pull --datasets pbp                                 # play-by-play
  python -m nfl.historical   # one-shot: 1966-1998 Spreadspoke backfill, rarely re-run
  ```
- **Verify:** sanity-check row counts, then validate one famous game score.
  (Rough baseline through 2025 from session memory, not repo-verifiable: ~7,276
  games / ~476K player-games — recheck via `SELECT COUNT(*) FROM games` if unsure.)
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

### OP-5: Kaggle dataset push — prerequisites `TODO(Eric)`, not yet met
- **Trigger:** after a refresh worth publishing.
- **Pre-flight (owner:Eric, incomplete):** needs (1) API token at
  `C:\Users\ericb\.kaggle\kaggle.json`, (2) `kaggle==1.6.17` pinned (already in
  `analysis/.venv` — default `pip install kaggle` is broken on import, don't let
  it drift), (3) `fingerprint()` implemented in `kaggle/push_datasets.py`
  (stub; `kaggle/tests/test_fingerprint.py` is red by design until written).
  **`TODO(Eric): create token, run first `--create` push, implement
  `fingerprint()`. Do not create Kaggle accounts/tokens on his behalf.`**
- **Steps (once met):**
  ```powershell
  $py = "C:\Users\ericb\Github\data_explorer\analysis\.venv\Scripts\python.exe"
  cd C:\Users\ericb\Github\data_explorer\kaggle
  & $py push_datasets.py --create                          # FIRST push only
  & $py push_datasets.py -m "refresh nba through 2026-07"   # subsequent
  ```
- **Verify:** prints `Done. Dataset (PRIVATE): https://www.kaggle.com/datasets/<you>/sports-dbs`
  — open it, confirm **Private** badge (§7). In-notebook: `sportsdb.databases()` lists all DBs.
- **If it fails:** see troubleshooting table in `kaggle/SETUP.md` (missing
  `kaggle.json`, 401, `kagglesdk` import error, 409 on `--create`). Dirty
  SQLite typing already handled (`build_duckdb.py` `TRY_CAST`s to NULL).

### OP-6: Supabase serving-table load
- **Pre-flight:** `~\.config\supabase.env` must hold `pooler_url` — never inline it.
- **Steps:** `python load_to_supabase.py <sqlite_path> <src_table> <dest_table>`
- **Verify:** prints `Loaded into Supabase public.<dest_table>: <N> rows`; `<N>`
  matches the printed source row count.
- **If it fails:** blank/whitespace numeric cells already coerced to NULL
  (`make_conv()`) before COPY — don't re-solve, it's handled.

### OP-7: scrapekit web extraction (used by OP-3 Tier 2 + ad hoc enrichment)
- **Escalation ladder, cheapest first** (`scrapekit/extract.py`):
  1. `Extractor.read_tables()` — parser-first `pandas.read_html` over cached HTML.
  2. `ParseError`/empty result -> `extract_with_fallback()` drops to local
     Ollama (`qwen2.5:7b`, `http://localhost:11434`; install hint in-module).
  3. Firecrawl — last resort, a deliberate paid decision, never a reflex.
- **Verify:** extracted tables spot-checked vs the live page; fetches disk-cached.
- **If it fails:** 403 on a non-browser UA -> already sends a real browser UA, handled.

### OP-8: Worktree sport DBs (soccer / mlb / nhl) — read only, never prune
- **Trigger:** a soccer, MLB, or NHL question arrives.
- **Steps:** `cd` into the specific worktree before querying — the main
  checkout has no soccer/mlb/nhl tables:
  ```powershell
  cd C:\Users\ericb\Github\data_explorer\.claude\worktrees\elegant-lamport-1d5555\soccer
  cd C:\Users\ericb\Github\data_explorer\.claude\worktrees\laughing-hugle-e9875d\mlb
  # NHL: two copies exist — use zen-turing (11 MB) as the working copy:
  cd C:\Users\ericb\Github\data_explorer\.claude\worktrees\zen-turing-c1e6df
  ```
- **Verify:** sport dir + `data/*.db` (or root `nhl.db`) present under that worktree.
- **If it fails:** "DB doesn't exist" -> wrong location (§4). For NHL, confirm
  which of the two copies is canonical before trusting results for betting (§6).

### OP-9: Answering a sports question (reference only, fully covered elsewhere)
See [`CLAUDE.md`](CLAUDE.md) (SCHEMA.md -> read-only SQL -> validate) and
[`analysis/README.md`](analysis/README.md) (uv + DuckDB via `sportsdb.py` —
`sportsdb.q()`/`pl()`, aliases `nba`/`nfl`/`pga`/`betting`). Never skip the
known-fact validation step, on any surface.

## 4. Failure modes & recovery

| Symptom | Cause | Fix | Verify |
|---|---|---|---|
| Scrape run interrupted | Network drop mid-backfill | Re-run identical command — idempotent upserts resume free | Row counts match, `pytest` green |
| NFL loader errors across seasons | nflverse column sets differ year to year | Already handled: `load_season()` ALTER-ADDs union, missing->NULL — don't patch | New season present, old unaffected |
| Golf leader-conversion % too high | Co-leaders double-counted | Already handled: `tier2_scrapekit` reads `Place` to isolate solo leaders | 54-hole major leader ~53%, stable across eras |
| `ModuleNotFoundError: kagglesdk` | Default `pip install kaggle` broke import | Reinstall `kaggle==1.6.17` in `analysis/.venv` | `pip show kaggle` -> `1.6.17` |
| Kaggle push re-uploads full ~6GB every time | `fingerprint()` unimplemented | Pending Eric (OP-5) — don't implement yourself | `pytest -q` in `kaggle/` still red |
| Supabase COPY rejects a row | Blank/whitespace in numeric SQLite column | Already handled: `make_conv()` -> NULL before COPY | Load completes, row count matches |
| "soccer/MLB/NHL DB doesn't exist" | Searched main checkout, not the worktree | Re-run in the correct worktree (OP-8); NHL lives in zen-turing / gracious-antonelli, not main | `data/*.db` or root `nhl.db` found under that worktree |
| Betting DB path looks wrong in MANIFEST | `db_dashboard.py` + `analysis/sportsdb.py` MANIFESTs still point at pre-fold `betting_stuff/data/odds_history.db`; `betting/` folded in 2026-07-01 | **Don't silently "fix"** — confirm the correct current path with Eric first | `TODO(Eric): confirm betting DB path and which MANIFEST(s) to update` |
| Site 403s the scraper | Non-browser default UA | Already handled: `scrapekit/extract.py` sends a real browser UA | Fetch succeeds, cached to disk |

## 5. Tuning knobs

| Param | Where | Current | Notes | Owner |
|---|---|---|---|---|
| NBA season range / `--force` / `--dry-run` | `nba/scrape.py` CLI args | `1996-2026` typical | `--force` = full rebuild, expensive | agent |
| NFL `--datasets` / `--seasons` | `nfl/pull.py` `DATASETS` + CLI | `schedules,player_stats,team_stats`, `1999-2025` | Floor `EARLIEST_SEASON=1999`, auto-clamped | agent |
| Kaggle dataset contents | `SOURCES` dict in `kaggle/push_datasets.py` | nba/nfl/pga | Add one line to `SOURCES`, then re-push (its docstring says so) | agent |
| Analysis attached DBs | `MANIFEST` in `analysis/sportsdb.py` | nba, nfl, pga, betting (path may be stale — §4) | Add a line, `connect(refresh=True)` | agent |
| scrapekit politeness/retry | `scrapekit/extract.py` constants | `MIN_INTERVAL_S=0.5`, `MAX_RETRIES=4`, `TIMEOUT_S=30` | Lower interval only for known-friendly APIs | agent |
| `fingerprint(db_path)` strategy | `kaggle/push_datasets.py` stub; tests `kaggle/tests/test_fingerprint.py` | unimplemented (red) | Must be content-based, not mtime | **Eric** — propose, never implement unasked |
| `shouldTakeDrawLive()` | `sharp-edge/lib/draw-signal.js` | placeholder | No default right answer | **Eric** — propose, never write the real logic |
| FanDuel `confirm=True` | `betting/fanduel/bet.py` via `betting/run.py --confirm` | `False` unless explicit | Real money, never standing-authorized | **Eric** — per-bet only |
| `classify_leader_outcome()` tie/playoff def | pga analysis module (`pga/README.md`) | documented baseline ships | Moves the headline %; a judgment call | **Eric** — propose, don't silently change |

## 6. Escalate to Eric (stop conditions)

- Any real FanDuel bet placement/modification, or FanDuel login/2FA beyond odds scraping.
- Known-fact validation fails on a refresh (e.g. Nicklaus != 18 majors) — stop;
  don't push suspect data to Kaggle/Supabase.
- A source API changes shape beyond the drift already handled (ESPN golf JSON,
  nba_api, nflverse) requiring scraper redesign — Opus/Eric territory.
- Kaggle first push: token + `--create` are pending Eric (OP-5) — don't create
  accounts/tokens on his behalf.
- Merging `feature/fold-betting-projects` to master, or any soccer/mlb/nhl
  worktree branch — branch strategy is Eric's call.
- NHL data is needed for betting/analysis — two worktree copies exist at
  different sizes; confirm which is canonical before trusting it (don't rebuild).
- The betting-path MANIFEST drift (§4) needs a real decision — don't guess.

## 7. Do-not list

- **Never** pass `confirm=True`/`--confirm` to FanDuel bet placement without
  Eric's explicit per-bet instruction — real money.
- **Never** commit `betting/raw/` or `betting/.eric.env` — gitignored personal
  financial data.
- **Never** mutate a DB during analysis — read-only always; `<sport>/data/` is
  gitignored, never force-add.
- **Never** prune `.claude/worktrees/elegant-lamport-1d5555` or
  `laughing-hugle-e9875d` — only local copies of the soccer/mlb DBs, unrecoverable if deleted.
- **Never** let the Kaggle dataset go public — confirm **Private** after every `--create`.
- **Never** default to Firecrawl/paid extraction — free sources first; paid is
  a deliberate exception, never a reflex.
- **Never** push raw/full DBs to Supabase — curated serving tables only; creds
  stay in `~\.config\supabase.env`, never inline.
- **Never** skip `python schema_doc.py` after a refresh, and never hand-edit `SCHEMA.md`.

## 8. Maintenance

Update this playbook in the SAME change as any operation change.

- 2026-07-04 — created (Fable-week Track 5), grounded against the live repo:
  verified branch (`feature/fold-betting-projects`), all scrape entrypoints, and
  flagged a real MANIFEST path drift (`betting_stuff/data/odds_history.db`
  post-fold) as `TODO(Eric)`.
- 2026-07-04 — corrected after adversarial verify: all **6** worktrees enumerated
  (prior draft saw only 2 and wrongly said NHL was missing). NHL DB exists in two
  worktrees at different sizes (duplication → `TODO(Eric)` canonical); extra root
  `nfl.db` (432 MB) + `drafts.db` (22 MB) noted, purpose unconfirmed. Kaggle knob
  corrected (`SOURCES` only, no `kaggle_sportsdb.py` MANIFEST).
