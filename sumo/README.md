# Sumo — bouts + a point-in-time physique database

Two decades-plus of professional sumo, local and queryable — mirrors `nba/`,
`nhl/`, `nfl/`: a cached, retrying API client, a normalized SQLite schema, and a
resumable backfill. Everything comes from the **free** community API at
[sumo-api.com](https://sumo-api.com) (which mirrors the SumoDB historical record).
No key, no scraping.

**Why sumo?** It is the most physically legible sport with a public record: two
humans of *known height and weight* collide, and exactly one wins. Every bout is a
controlled experiment in whether mass decides the outcome — and the answer is a
query away.

## Build it

Run from the `data_explorer` repo root (so the `sumo` package imports resolve):

```bash
python -m sumo.build --verify                  # full crawl: bouts, wrestlers, awards, career cards
python -m sumo.build --start 202001 --verify   # shorter window
python -m sumo.build --limit-basho 1 --verify  # one tournament (smoke test)
python -m sumo.physical --verify               # derive bout_wrestler (the as-of join)
python -m sumo.analyze                         # the deep dive: does size win?
python schema_doc.py                           # refresh SCHEMA.md
```

The crawl is **resumable** — interrupt and re-run. Each unit of work (a
basho×division×day, a tournament's awards) writes a row to the `fetched` ledger
and is never re-fetched; wrestlers and career cards resume off their own tables.
A wrestler that fails to fetch is logged loudly and retried next run rather than
being silently skipped.

Current local build: **193,405 bouts** across **398 basho (1960-01 → 2026-07)**,
989 wrestlers, 8,683 measurement change-points.

## Tables

| Table | Grain | Notes |
|---|---|---|
| `bouts` | one bout | east/west + `winner_id` + `kimarite` (deciding technique) |
| `rikishi` | one wrestler | bio + stable (`heya`) + **latest** height/weight |
| `measurements` | wrestler × **change-point** | size *as recorded at* `basho_id` — not per-tournament |
| `ranks` | wrestler × basho | `rank_value` numeric, lower = higher (Yokozuna 1E = 101) |
| `basho` | one tournament | dates, which is what makes age-at-bout possible |
| `yusho` | basho × division | the division champion; Makuuchi yusho is the top honour |
| `sansho` | basho × prize × wrestler | the three special prizes, co-awardable |
| `rikishi_stats` | one wrestler | career accolade card (titles, W-L, top-division longevity) |
| `bout_wrestler` | **bout × wrestler** | **derived** — the analysis-ready table (see below) |

## `bout_wrestler` — the as-of physical join

`physical.py` expands every bout into **two rows**, one from each man's point of
view, with his physicals *and* his opponent's *and* the differentials
(`weight_adv`, `height_adv`, `bmi_adv`, `age_adv`, `rank_adv` — own minus
opponent). That shape makes "win rate by attribute" a one-line `GROUP BY`, and it
is point-symmetric by construction: `winrate(+d) = 1 - winrate(-d)`, so the
overall win rate is exactly 50.00% — a built-in consistency check that catches a
broken build immediately.

The hard part is **honesty about time**. Measurements are change-points, so a bout
in 2011 must join to the size recorded *by* 2011, never to the career-latest
weight — a naive join is silently wrong for every historical bout. That policy
lives in one function, `resolve_measurement()`: most-recent-measurement
at-or-before the bout, falling back to the earliest recorded when the bout
predates the first measurement. It resolves a weight for **95.6%** of rows;
unresolved ones are `NULL`, never a fake 0. Swap that function's body to change
the policy — everything downstream re-derives.

## Gotchas (probed, don't re-derive)

- **Query `bout_wrestler`, not `bouts`**, for anything about physiques. `bouts` is
  the raw record; the as-of resolution only exists on the derived table.
- **Exclude `kimarite = 'fusen'`** — forfeits where a wrestler was absent and no
  sumo happened. They are wins in the record but not physical contests.
- **Marginal-mass claims are rank-confounded.** Win rate by *absolute* `weight_kg`
  or `bmi` largely measures rank: heavier men are disproportionately higher-ranked
  and rank predicts winning. Only the *differential* columns are matchup-internal
  and safe to read causally. Any "each extra kg is worth X%" claim must control on
  `rank_value` / `rank_adv` first. `analyze.py` labels the absolute-weight curve as
  confounded for exactly this reason.
- **Size does win, but modestly**: outweighing your opponent by 40 kg+ is worth
  ~52% (n=25k), not 60%. The differential curve is monotone and symmetric, which
  is the honest headline.
- **Only the sekitori** (`Makuuchi` + `Juryo`, the two salaried divisions) have
  per-day bout records; lower divisions are not crawled.
- **Basho ids are `'YYYYMM'` text** for the six annual honbasho (odd months). They
  compare chronologically as strings, which is what the as-of join relies on.
- DB lives in `sumo/data/` and is **gitignored** — regenerate with the commands
  above.

## Validated against

`Hakuho Sho` leads Makuuchi championships with **45**, ahead of Taiho (32) and
Chiyonofuji (31) — matches the real record. `build.py --verify` prints this check
and the Makuuchi win leaders on every run.
