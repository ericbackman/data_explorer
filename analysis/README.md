# Sports analysis environment

A dedicated, reproducible workspace for hand-driven exploratory analysis over the
local sports SQLite databases. **DuckDB** attaches each `.db` file
**read-only** and acts as a fast analytical front-end, so the databases stay the
single source of truth and analysis can never corrupt them.

## Stack (and why)

| Choice | Role | Why |
|--------|------|-----|
| **uv** | env + deps | One committed `uv.lock` → identical installs everywhere. |
| **DuckDB** | query engine | Columnar speed + joins *across* SQLite DBs, zero data duplication, read-only. |
| **Jupyter** | notebook | Your default; `01_explore.ipynb` is the starter. |
| **marimo** | notebook (sample) | The 2026 reactive, pure-`.py`, git-friendly style — `marimo_sample.py` to compare. |
| pandas / Polars | dataframes | `sportsdb.q()` → pandas, `sportsdb.pl()` → Polars. |

## First-time setup

From this directory (`data_explorer/analysis/`):

```bash
uv sync                                   # build the env from pyproject + lockfile
uv run python -m ipykernel install --user --name sports-analysis \
    --display-name "Sports analysis (uv)"   # register the Jupyter kernel
```

## Day-to-day

```bash
uv run jupyter lab 01_explore.ipynb       # Jupyter (pick the "Sports analysis (uv)" kernel)
uv run marimo edit marimo_sample.py       # marimo reactive notebook
uv run python sportsdb.py                 # CLI smoke test — lists attached DBs
```

## Querying

```python
import sportsdb
con = sportsdb.connect()                  # attaches every available core DB, read-only
sportsdb.databases()                      # what's attached
sportsdb.tables()                         # every table, all DBs

sportsdb.q("SELECT * FROM nba.player_game LIMIT 5")     # -> pandas
sportsdb.pl("SELECT * FROM pga.tournaments")            # -> Polars
```

Attached aliases (the schema you query): `nba`, `nfl`, `pga`.
See the table/column map in [`../SCHEMA.md`](../SCHEMA.md).

## Adding a database

Add one line to `MANIFEST` in [`sportsdb.py`](sportsdb.py), then
`sportsdb.connect(refresh=True)`. Commented-out examples
(`nba_comebacks`, `mtg`, `life`, `games`) are there to copy.

## Discipline

Agent-written or hand-written SQL that *executes* is not necessarily *correct*.
Validate every derived number against a known fact before trusting it — the same
rule `data_explorer/CLAUDE.md` already enforces.
