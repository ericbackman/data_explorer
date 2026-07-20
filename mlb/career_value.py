"""
Career value v0
================
v0 (documented here per project convention — this is a deliberately crude
first cut, not a sabermetric model):

    value_games = MAX(career batting games, career pitching games)

Summed per player across every batting/pitching stint on record, then take
the **max** of the two totals (not the sum) — a two-way player logged in
both tables would otherwise be double-counted across what the data treats
as two disjoint careers, which the metric isn't trying to unify. This is
crude but verified (Piazza checks out at ~1912 games) and monotone-enough
to separate steals from busts across the hitter/pitcher split. It is NOT
a value model (no WAR, no era/park adjustment, no defense) — that's future
work; document any replacement as v1+ in this same docstring.

Most drafted players have **no row at all** here — zero MLB games is the
norm for a draft (most picks never reach the majors), not a bug.
"""

from __future__ import annotations


def _to_int(value) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def sum_games_by_player(rows: list[dict], player_id_key: str = "playerID", games_key: str = "G") -> dict[str, int]:
    """Sum the games-played column per player id across every stint/year row."""
    totals: dict[str, int] = {}
    for row in rows:
        player_id = row.get(player_id_key)
        if not player_id:
            continue
        totals[player_id] = totals.get(player_id, 0) + _to_int(row.get(games_key))
    return totals


def compute_career_value(batting_rows: list[dict], pitching_rows: list[dict]) -> dict[str, dict]:
    """{playerID: {"batting_g": int, "pitching_g": int, "value_games": int}}
    for every player who appears in either table."""
    batting_g = sum_games_by_player(batting_rows)
    pitching_g = sum_games_by_player(pitching_rows)

    all_ids = set(batting_g) | set(pitching_g)
    return {
        player_id: {
            "batting_g": batting_g.get(player_id, 0),
            "pitching_g": pitching_g.get(player_id, 0),
            "value_games": max(batting_g.get(player_id, 0), pitching_g.get(player_id, 0)),
        }
        for player_id in all_ids
    }
