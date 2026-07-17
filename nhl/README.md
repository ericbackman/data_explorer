# NHL — local box-score + playoff database

Free, local NHL data for answering hockey questions and feeding the
[video-essay pipeline](../../video-essays) — mirrors `nba/` and `nfl/`: a cached
API client, a normalized SQLite schema, and resumable backfills. Everything comes
from the **free** modern NHL endpoints (no key):

- `api.nhle.com/stats/rest/en/game` — the master game index (every game ever, one call)
- `api-web.nhle.com/v1/gamecenter/{id}/boxscore` — per-game skater/goalie stats
- `api-web.nhle.com/v1/gamecenter/{id}/play-by-play` — event stream (optional)

## Build it

Run from the `data_explorer` repo root (so the `nhl` package imports resolve):

```bash
python -m nhl.build --verify                       # schema + games index (1997-98 → now)
python -m nhl.boxscores --team-id 10 --min-season 20122013   # Leafs boxscores, core-four era
python -m nhl.series --team-id 10 --verify         # derive playoff series (needs only the index)
python schema_doc.py                               # refresh SCHEMA.md
```

`--team-id 10` (Toronto) backfills only games that team played (~1,300 for the
Leafs 2012→now, ~9 min) instead of the whole league (~18k, ~2 hrs). Drop it to
backfill everything. Backfills are **resumable** — interrupt and re-run; each
game flips a `boxscore_loaded` / `pbp_loaded` flag and is never re-fetched.

## Tables

| Table | Grain | Notes |
|---|---|---|
| `games` | one game | `game_type` 2=regular, 3=playoff; `season` is the 8-digit int `20122013` |
| `teams` | one franchise | `abbrev` filled during the boxscore backfill |
| `players` | one player | abbreviated name (`A. Matthews`) + last position |
| `skater_boxscores` | player × game | goals/assists/points, +/-, TOI, hits, blocks, faceoff% … |
| `goalie_boxscores` | goalie × game | saves, save%, decision, strength splits |
| `team_game` | team × game | score + shots straight from the boxscore |
| `plays` | event × game | wide table; coords only from 2009-10+ (optional, via `pbp`) |
| `playoff_series` | series × team | **derived** — score, round, Game-7 + blown-lead flags |

## `playoff_series` — the essay's spine

`series.py` groups a team's playoff games by opponent (teams never face two at
once) into series, then computes the score, round, `went_to_game7`, and a
**blown-lead detector**: `blew_lead = 1` when the team *lost* a series it once led
by ≥ 2 games. On the Leafs it fires on exactly the 2021 (3-1 vs Montreal) and 2025
(vs Florida) collapses and stays quiet on the tight Game-7 losses — a blown *series*
lead is a different beast from a blown *game* (e.g. the 2013 Game-7 4-1 collapse,
which is a game score, not a series lead). The raw facts live here; how to *rank*
"most devastating exit" is an essay-adapter judgment, deliberately downstream.

## Gotchas (probed, don't re-derive)

- **Full modern boxscores start 1997-98** (the RTSS era: TOI, hits, blocks,
  takeaways, faceoff%). Earlier games have only basic scoring.
- **Play-by-play coordinates start 2009-10** (`x/y/zone`, `situation_code` are NULL
  before that; the events still load).
- **`api-web.nhle.com` is lenient** but the client still retries 429/5xx with
  backoff and a 25s timeout, per the workspace standard.
- The `season` column is **text** (`'20122013'`); cast when doing range filters.
- DB lives in `nhl/data/` and is **gitignored** — regenerate from the commands above.
```
