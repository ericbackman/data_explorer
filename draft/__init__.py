"""Unified cross-sport draft database (NBA / NFL / NHL / MLB).

One table, every league: a draft pick is the same shape everywhere — (year,
round, overall pick, team, player, where-they-came-from) — so all four sources
normalize into a single `draft_picks` table discriminated by `sport`. Build it:

    python -m draft.build --sports nba,nfl,nhl,mlb     # all available history
    python -m draft.build --sports nba --years 1996-2025
"""
