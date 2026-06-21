# pga

A local PGA Tour history database, built entirely from **free** sources, aimed at
answering questions like *"how often does the 36-/54-hole leader actually win?"*
and at supporting the occasional major-championship bet.

A `data_explorer` sub-project (mirrors `nba/`). Run all commands **from the
`data_explorer` repo root** (e.g. `python -m pga.scrape`), not from this folder.

## What's in it

| Tier | Coverage | Granularity | Source |
|------|----------|-------------|--------|
| **1** | 2005–present, every PGA Tour stroke-play event | Full field, round-by-round (front/back nine), positions, earnings, venue | ESPN public JSON API |
| **2** | Majors 1960–2004 | Winner + 36/54-hole leaders | Wikipedia (Firecrawl) |

ESPN's free golf API only returns events back to **2005** (verified empirically),
so 2005+ is the realistic ceiling for full-field round-by-round data. Pre-2005
major history is a separate, shallower tier.

Total size is tens of MB — the whole DB and JSON cache fit comfortably under 1 GB.

## Schema

Raw facts only; analysis is derived at query time so "leader" can be redefined
without re-scraping.

- `tournaments` — one row per event (season, venue, par, purse, `is_major`, winner)
- `players` — id, name, country
- `player_rounds` — one row per player per round (strokes, to-par, front/back nine, playoff flag)
- `player_results` — final position, total, status (finished/cut/wd/dq), earnings

## Usage

```bash
pip install -r requirements.txt

# Backfill everything (resumable; caches raw JSON to data/raw/)
python -m pga.scrape --seasons 2005-2026

# Or one season
python -m pga.scrape --seasons 2024

# Leader-conversion report (all events + majors)
python -m pga.analysis

# Tests (from the data_explorer root)
python -m pytest pga/
```

The scraper is **resumable**: every API response is cached to disk and every load
is an idempotent upsert, so re-running re-fetches nothing and converges to the
same DB.

### Tier 2 — majors 1960–2004 (Firecrawl + Wikipedia)

ESPN has no pre-2005 data, so the deep major history comes from Wikipedia via
Firecrawl's schema-based extraction (one `/scrape` per page, disk-cached).

```bash
# 1. free key at firecrawl.dev -> put it in a gitignored .env:
echo "FIRECRAWL_API_KEY=fc-..." > .env

# 2. (credit-safe) test on a handful of pages first
python -m pga.tier2_firecrawl collect --start 2003 --end 2003 --limit 4

# 3. full backfill -> seeds/major_history_seed.json (cached, resumable)
python -m pga.tier2_firecrawl collect --start 1960 --end 2004

# 4. validate + load into the major_history table
python -m pga.tier2 load seeds/major_history_seed.json
```

~180 pages (4 majors × 45 years) fits inside Firecrawl's free monthly tier; the
disk cache means re-runs cost zero credits.

## Data quirks handled

- Team / match-play events (Presidents Cup, exhibitions) are skipped — no stroke-play leader.
- Withdrawals leave a `value: 0` placeholder round; these are nulled so they never
  pollute leader math (this is why a naive query once crowned a WD as Masters leader).
- The Open Championship is labelled simply **"The Open"** in ESPN's feed.

## The one design decision that's yours

`pga_data/analysis.py :: classify_leader_outcome()` decides what "the leader
converted" *means* when players are tied for the lead and when an event goes to a
playoff. There's no single right answer; the choice moves the headline number.
A documented baseline ships; tighten it to your definition.
