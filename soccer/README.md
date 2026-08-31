# soccer

A local multi-competition soccer database, built from **free** sources, aimed at
answering questions like *"who's scored the most World Cup goals?"*, *"how often
does the host nation reach the semifinal?"*, and (later, via event data) *"who
overperformed their xG at a tournament?"*

A `data_explorer` sub-project (mirrors `pga/` structurally — soccer's
*competition → match → events* nests like golf's *tournament → round → hole*). Run
all commands **from the `data_explorer` repo root** (e.g. `python -m soccer.scrape`).

## What's in it

| Tier | Coverage | Granularity | Source |
|------|----------|-------------|--------|
| **1** | Every FIFA World Cup **1930–2026** (incl. the live 2026 tournament) | Match list: scores, penalty shootouts, venue, attendance, round | ESPN public JSON API |
| **1.5** | Same matches | **Events**: goals, penalties, own goals, cards — minute-stamped, **with scorer name** | embedded in the same scoreboard responses |
| **1L** *(planned)* | Recent matches | **Lineups**: starting XI + bench, positions | ESPN `summary` endpoint |
| **2** *(planned)* | WC 2018, 2022 + 6 historical; Messi-era La Liga; CL seasons | **Event-level**: every pass & shot with **xG** | StatsBomb open data (free) |

The schema is **competition-agnostic**: the World Cup, the Euros, the Champions
League, and the top-5 leagues are all just rows in `competitions`. Adding one is a
new ESPN league-code in `parse.COMPETITIONS`, never a new table.

ESPN's soccer scoreboard returns match *results* back to **1930** (verified: 18
matches in 1930, 64 in 2010 — historically exact). Per-match lineup depth only
exists for recent decades; the scraper degrades gracefully when it's absent.

## Schema

Raw facts only; analysis (standings, scorer tables, xG) is derived at query time
so definitions can change without re-scraping.

- `competitions` — World Cup / Euro / Champions League / a league (`kind`, `slug`)
- `seasons` — one edition (World Cup 2022; Premier League 2023/24)
- `teams`, `players` — dimensions (national teams *are* teams)
- `matches` — the spine: score, halftime, penalty shootout, round, venue, `outcome`
- `lineups` — starting XI / bench per match (Tier 1L)
- `match_events` — goals, cards, subs, minute-stamped (Tier 1.5)

## Usage

```bash
pip install -r requirements.txt

# Backfill all World Cups (resumable; caches raw JSON under data/cache/)
python -m soccer.scrape                          # default competition = fifa.world
python -m soccer.scrape --dry-run                # show the plan, fetch nothing

# Extend to other competitions (schema already supports them)
python -m soccer.scrape --competition uefa.euro --years 1960-2024
python -m soccer.scrape --competition eng.1      --years 2001-2026

# Tests (from the data_explorer root)
python -m pytest soccer/
```

The scraper is **resumable**: every API response is cached to disk and every load
is an idempotent upsert. A completed tournament is fetched once; the live 2026
edition is re-fetched each run for updated scores.

## Data quirks handled

- **A penalty shootout is officially a draw.** The shootout result lives in
  `matches.home_pens` / `away_pens`; shootout kicks are stored as
  `match_events.type = 'Shootout Penalty'` so they never get counted as match goals.
- **Own goals** are tagged `'Own Goal'` (credited to the conceding player but
  counting for the opponent on the scoreboard).
- **Old tournaments carry no event data** — pre-modern World Cups load matches and
  scores with an empty event stream; that's expected, not a bug.

## The one design decision that's yours

`soccer/parse.py :: match_outcome()` decides what a match *result* means — most
importantly, whether a knockout decided on penalties counts as a draw (FIFA's
official record) or a win for the team that converted more penalties. Both are
valid; the choice moves every win/draw/loss tally in the DB. It ships as a stub
that returns `None` (the scraper says so loudly); implement your rule and re-run.
