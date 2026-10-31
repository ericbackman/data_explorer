# Sports Data Explorer

A personal multi-sport data platform. Each sport gets a cached, resumable scraper, a
normalized SQLite schema and analysis modules. A generated schema map, [`SCHEMA.md`](SCHEMA.md),
lets an agent such as Claude Code turn a plain-English question into read-only SQL, then check
the answer against a known fact before reporting it.

The databases are not in this repo. They are gitignored and rebuilt from the scrapers. Start
with [`OVERVIEW.md`](OVERVIEW.md) for the architecture and [`CLAUDE.md`](CLAUDE.md) for how a
question gets answered.

Unofficial. Not affiliated with or endorsed by any league, team, tour, player or data source
named here.

## What's here

| Path | What it is |
|---|---|
| [`pga/`](pga/README.md) | Golf: events, rounds, 7M hole scores, player bios, and strokes-gained derived from the holes |
| [`nba/`](nba/README.md) | Box scores, play-by-play and advanced stats via `nba_api` |
| `nfl/` | Box scores and play-by-play via nflverse |
| [`nhl/`](nhl/README.md) | Game index, box scores and derived playoff series |
| `mlb/`, [`draft/`](draft/README.md) | MLB draft and careers; draft history across four leagues |
| [`sumo/`](sumo/README.md), [`soccer/`](soccer/README.md), [`osrs/`](osrs/README.md) | Smaller domains built the same way |
| [`podcasts/`](podcasts/README.md) | RSS to transcripts to SQLite full-text search |
| [`cba/`](cba/README.md) | A navigation layer and explainers over the NBA collective bargaining agreement, plus a tested trade-rule engine |
| [`trades/`](trades/README.md) | Draft-pick protections rendered as flowcharts and slot maps |
| [`nba_site/`](nba_site/README.md) | Source of the [Data Lab](https://datalab.ericbackman.com) site |
| [`analysis/`](analysis/README.md) | DuckDB and marimo notebooks over the SQLite files, read-only |
| `scrapekit/` | Credit-free web extraction, with a local-model fallback |
| `sports_mcp.py` | Read-only MCP server over the databases: `list_databases`, `describe_schema`, `run_sql` |
| `bigquery/`, `neon/`, `tidb/`, `kaggle/` | Experiments loading a subset to hosted warehouses |
| `schema_doc.py`, `db_dashboard.py` | Generate the schema map and a visual inventory of every database |

## Try it

Python 3.10+.

```bash
pip install -r requirements.txt pytest
python nba_dashboard.py "Nikola Jokic" 2024-25
python -m pytest nba/tests trades/tests
```

`nba_dashboard.py` also imports as a module and backs a Claude Code command:
`/nba-dashboard Nikola Jokic`.

The trade-rule engine runs on an invented sample league:

```bash
cd cba/trade-machine
npm ci
npm test
npm run dev
```

## Licence

The code is under the [MIT licence](LICENSE). It does not cover third-party data, names or
marks: see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
