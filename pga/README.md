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
| **1h** | 2005–present | **Hole-by-hole** (7M+ rows): every player, round, hole, strokes + derived par | re-parsed from the same cached scoreboards |
| **1b** | player dimension | **Bios**: age, turned-pro, birthplace, citizenship, hand, college, ht/wt | ESPN athlete endpoint |
| **1s** | derived | **Strokes-gained vs field**: SG-Total per hole/round/event, par-3/4/5 splits | computed from the hole data |
| **2** | Majors 1960–2004 | Winner + 36/54-hole leaders | Wikipedia (scrapekit) |

ESPN's free golf API only returns events back to **2005** (verified empirically),
so 2005+ is the realistic ceiling for full-field round-by-round data. Pre-2005
major history is a separate, shallower tier.

Total size is tens of MB — the whole DB and JSON cache fit comfortably under 1 GB.

## Schema

Raw facts only; analysis is derived at query time so "leader" can be redefined
without re-scraping.

- `tournaments`: one row per event (season, venue, par, purse, `is_major`, winner)
- `players`: id, name, country
- `player_rounds`: one row per player per round (strokes, to-par, front/back nine, playoff flag)
- `player_results`: final position, total, status (finished/cut/wd/dq), earnings

## Usage

```bash
pip install -r requirements.txt

# Backfill everything (resumable; caches raw JSON to data/raw/)
python -m pga.scrape --seasons 2005-2026

# Or one season
python -m pga.scrape --seasons 2024

# Leader-conversion report (all events + majors)
python -m pga.analysis

# Hole-level depth: backfill from cache (no network), then query
python -m pga.holes_scrape --seasons 2005-2026
python -m pga.holes course "Augusta National Golf Club"   # hardest holes
python -m pga.holes player "Scottie Scheffler"            # par-3/4/5 profile

# Player bios (age, turned pro, birthplace, hand, college) from ESPN athletes
python -m pga.bios_scrape                  # all players (resumable, cached)
python -m pga.bios_scrape --min-results 4  # only regulars

# Strokes-gained vs field (derived; build once, then query)
python -m pga.sg build
python -m pga.sg player "Scottie Scheffler"      # career SG + par splits
python -m pga.sg event "Masters" --year 2024     # SG leaderboard

# Tests (from the data_explorer root)
python -m pytest pga/
```

The scraper is **resumable**: every API response is cached to disk and every load
is an idempotent upsert, so re-running re-fetches nothing and converges to the
same DB.

### Tier 2: majors 1960–2004 (Wikipedia)

ESPN has no pre-2005 data, so the deep major history comes from Wikipedia. The
**primary, free** path uses [scrapekit](../scrapekit/) (`pandas.read_html`): the
36-/54-hole leaders are computed deterministically from each page's per-round
leaderboard tables (`70-68=138` after R2), and the champion comes from the
infobox. No API key, no credits, and *more precise* than prose extraction: it
reads the `Place` column, so it distinguishes solo leaders from co-leaders.

```bash
# Primary: free, deterministic, no key
python -m pga.tier2_scrapekit collect --start 1960 --end 2004
python -m pga.tier2 load seeds/major_history_seed.json
```

A **Firecrawl** collector (`tier2_firecrawl.py`) is kept as a fallback for pages
the table parser can't handle (per the data_explorer convention, paid extraction
is reserved for hostile/awkward sites). It needs `FIRECRAWL_API_KEY` in a
gitignored `.env` (project root or `~/.env`):

```bash
python -m pga.tier2_firecrawl collect --start 1960 --end 2004   # ~2.7 credits/page
```

`seeds/major_history_seed.json` is the committed, validated output (winner
matches the historical record player-for-player; Nicklaus 18, Watson 8, …).

## Data quirks handled

- Team / match-play events (Presidents Cup, exhibitions) are skipped: no stroke-play leader.
- Withdrawals leave a `value: 0` placeholder round; these are nulled so they never
  pollute leader math (this is why a naive query once crowned a WD as Masters leader).
- The Open Championship is labelled simply **"The Open"** in ESPN's feed.

## The one design decision that's yours

`pga_data/analysis.py :: classify_leader_outcome()` decides what "the leader
converted" *means* when players are tied for the lead and when an event goes to a
playoff. There's no single right answer; the choice moves the headline number.
A documented baseline ships; tighten it to your definition.
