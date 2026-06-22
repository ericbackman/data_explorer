"""Local NFL database, built free from nflverse (nflreadpy / nflfastR data).

Per-interest project inside data_explorer, mirroring nba/. nflverse ships
pre-compiled per-season data (schedules, player/team game stats, ~370-col
play-by-play), so this is a bulk download — not a per-game scrape. Coverage
starts 1999 (structured NFL data isn't freely available before then).

  pull.py — bulk loader: nflreadpy -> pandas -> SQLite, per-season delete+insert
  data/   — nfl.db (gitignored, regenerable)
"""
