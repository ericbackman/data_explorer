# data_explorer — a personal sports data platform

_An onboarding explainer for someone seeing this for the first time._

## What this is

A collection of **local SQLite databases across sports** — golf, NBA, NFL, NHL,
MLB, sumo and more — that you can **query in plain English**. Ask "who's the best
par-5 scorer since 2005?" or "how often does the 54-hole major leader win?" and get
a real, validated answer. Everything is built from **free** data sources; there are
no paid API subscriptions anywhere in it.

The goal: *one computer that can answer any sports question*, adding sports one at
a time, each one deep enough to be genuinely useful.

## The shape of it (architecture)

Five layers, left to right — raw data becomes an answer:

```
free sources  →  cached scrapers  →  SQLite DBs  →  analysis modules  →  query layer
(ESPN, nflverse,   (resumable,        (per sport,    (leader conversion,   (CLAUDE.md +
 Wikipedia)         disk-cached)       normalized)    SG, course stats…)    SCHEMA.md +
                                                                            MCP server)
```

1. **Sources** — undocumented-but-free JSON APIs (ESPN), open datasets (nflverse),
   and structured web pages (Wikipedia, parsed credit-free via `scrapekit`).
2. **Scrapers** — one per sport, that cache every response to disk and load with
   idempotent upserts. So a re-run re-fetches nothing and never double-counts;
   an interrupted run resumes for free.
3. **Databases** — a normalized SQLite file per sport under `<sport>/data/`.
4. **Analysis modules** — Python that encodes the *right definitions* of common
   questions (e.g., what "the leader converted" means with ties and playoffs).
5. **Query layer** — what makes it answerable in English (see below).

## How you actually use it

- **In Claude Code:** just ask a sports question. A pointer in the workspace
  `CLAUDE.md` tells Claude to read [`SCHEMA.md`](SCHEMA.md) (an auto-generated map
  of every table), write read-only SQL, and **validate the answer against a known
  fact** before reporting.
- **Anywhere else (Claude Desktop, phone):** the `sports-data` **MCP server**
  (`sports_mcp.py`) exposes three read-only tools — `list_databases`,
  `describe_schema`, `run_sql` — so any Claude surface can query the DBs with no
  shell access. Writes are rejected; the connection is opened read-only.

## What's in it (the data)

| Sport | Coverage | Depth |
|-------|----------|-------|
| **Golf** (`pga/`) | 2005–2026 + majors back to 1960 | event → results → rounds → **7M holes** → strokes-gained → player bios |
| **NBA** (`nba/`) | 1946–present | box scores (13.5M rows) |
| **NFL** (`nfl/`) | 1999–present | box scores + play-by-play |
| **NHL** (`nhl/`) | 1997–present | box scores + derived `playoff_series` |
| **MLB** (`mlb/`) | modern era | schedule, box scores |
| **Sumo** (`sumo/`) | 1960–present | every sekitori bout + ranks, physicals, awards |
| **OSRS** (`osrs/`) | current | read-only clan stats |
| **Podcasts** (`podcasts/`) | current | RSS → transcripts → full-text search |

Betting odds used to sit here too. The `betting/`, `sharp-edge/` and `polymarket/`
subtrees were **split out to the private `betting-lab` repo on 2026-08-09** so this
one could be published — see `PLAYBOOK.md`. The golf `betting` module (`pga/betting.py`,
course history and form) is unrelated and still here.

## The golf deep-dive (the flagship)

Golf is the worked example of "deep enough to be useful." It was built in layers,
each free, each validated against reality:

- **Results & leaders** — every event 2005–26; answers "does the 36-/54-hole
  leader win?" Combined with **majors 1960–2004** (scraped from Wikipedia), that's
  266 majors: the 54-hole major leader wins **~53%**, and it's remarkably stable
  across 66 years.
- **Hole-by-hole** — 7 million individual hole scores (re-parsed for free from data
  already cached). Unlocks "hardest hole at Augusta" (it's #11) and per-golfer
  par-3/4/5 profiles.
- **Strokes-gained vs field** — the metric paid services (DataGolf) charge for,
  *derived for free* from the hole data. It reconstructs the real 2024 Masters
  finish order from field-relative scoring alone (Scheffler #1), and pegs his
  +1.92 SG/round at world-#1 level.
- **Player bios** — age, turned-pro, nationality, college, handedness.

## Design principles

- **Free sources only.** Paid/hostile extraction is a deliberate exception; the
  one paid-grade metric (strokes-gained) was *derived*, not bought.
- **Loud failure over silent wrong data.** Withdrawals, partial rounds, team
  events, and over-counted co-leaders were all caught by validating derived
  numbers against known facts (e.g., Nicklaus has exactly 18 majors; a famous
  leader actually led solo). Several real data bugs were found this way.
- **Read-only queries; regenerable data.** The DBs are gitignored (rebuildable
  from the scrapers); only code and costly-to-regenerate seeds are committed.

## Repo map

```
data_explorer/
  pga/  nba/  nfl/        per-sport sub-projects (scraper + schema + analysis)
  scrapekit/              shared credit-free web-extraction toolkit
  db_dashboard.py         visual inventory of every DB
  schema_doc.py → SCHEMA.md   auto-generated schema reference (the query map)
  sports_mcp.py           read-only MCP server (the "ask from anywhere" layer)
  CLAUDE.md               how Claude answers sports questions here
```
