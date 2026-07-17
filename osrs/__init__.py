"""OSRS clan companion — local Hiscores snapshots + gains competitions.

Tracks RuneScape names over time via the public OSRS Hiscores API (read-only
public stats — no game automation, no client interaction) so a friend group can
race XP gains and see who's grinding what. Mirrors the nba/pga/nfl package
layout: client (resilient I/O) -> parse (pure) -> db (schema) -> snapshot (CLI),
with competition scoring in scoring.py.
"""
