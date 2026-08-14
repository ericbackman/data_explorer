"""
sumo — a physical-attributes deep dive on two decades of professional sumo
==========================================================================
Local SQLite database of every sekitori (top two divisions: Makuuchi + Juryo)
bout, built from the free community JSON API at https://sumo-api.com (which in
turn mirrors the SumoDB historical record).

Why sumo? It is the most physically legible sport with a public record: two
humans of *known height and weight* collide, and exactly one wins. Every bout is
a controlled experiment in whether mass, height, and body composition decide the
outcome — and the answer is a query away.

Layout mirrors the other sports in this repo (nba/, nhl/, ...):

    api.py       cached, retrying client + pure parsers (testable off-network)
    build.py     schema + resumable backfill (bouts, rikishi, measurements, ranks)
    physical.py  the point-in-time "as-of" join + derived physical features
    analyze.py   the deep dive: win rate by weight / BMI / size mismatch / age

Run from the repo root, e.g.  `python -m sumo.build --verify`.
"""
