"""pga: a local PGA Tour history database built from free sources.

A data_explorer sub-project (mirrors the nba/ layout). Run from the repo root:
    python -m pga.scrape --seasons 2005-2026

Tier 1 (2005-present): full-field, round-by-round data from ESPN's public JSON API.
Tier 2 (1960-2004 majors): winner + 36/54-hole leaders from Wikipedia, parsed
free via scrapekit (pandas.read_html); Firecrawl kept as a fallback.
"""

__version__ = "0.1.0"
