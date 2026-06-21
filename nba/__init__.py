"""Local NBA database, built purely from the free nba_api (stats.nba.com).

Mirrors the pga-data package layout:
  client.py  — rate-limited, retrying, disk-cached nba_api wrapper
  parse.py   — endpoint dataframes -> normalized row dicts (pure, testable)
  db.py      — SQLite schema + idempotent loaders
  scrape.py  — resumable backfill/update CLI
"""
