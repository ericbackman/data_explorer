"""Competition scoring — HOW we rank the clan's gains.

This is the brain of the clan companion: given how much XP each tracked player
gained over a window, decide who's winning. There is no single right answer, and
the choice changes the *character* of the competition — see score_player().

rank_gains() is plumbing (sort + assign places); you own score_player(), the
few lines that define what "most impressive week" means for your clan.
"""

from __future__ import annotations


def score_player(skill_gains: list[dict]) -> float:
    """Return a single 'how good was this window' score for one player.

    `skill_gains` is one player's per-skill gains (from parse.diff_snapshots),
    each item shaped like:
        {
          "skill":         "Slayer",
          "xp_gained":     1_250_000,   # XP added in the window (>= 0)
          "levels_gained": 3,           # whole levels gained (>= 0)
          "before_xp":     5_000_000,   # XP at the start of the window
          "after_xp":      6_250_000,   # XP at the end
          "before_level":  90,
          "after_level":   93,
        }
    Higher score = better window. rank_gains() sorts on this, descending.

    ┌─────────────────────────────────────────────────────────────────────────┐
    │  >>> THIS IS YOUR DESIGN DECISION <<<   (see osrs/README.md)              │
    └─────────────────────────────────────────────────────────────────────────┘
    The OSRS XP curve is exponential: level 92 is *half* the XP of 99, and an
    hour of high-level training can dwarf a fresh account's whole week. So the
    metric you pick decides who the leaderboard flatters:

      • Raw total XP gained         -> rewards grind volume; favours maxed mains
                                        who earn XP fast. Simple and brutal.
      • Levels gained               -> rewards low-level accounts (early levels
                                        are cheap); a maxed main literally can't win.
      • XP relative to current XP   -> "% growth"; flatters small accounts.
      • Effort-normalised (EHP-ish) -> weight each skill's XP by a rough rate so a
                                        slow skill counts for more. Fairest, hardest.
      • Diversity bonus             -> reward training MANY skills, not botting one
                                        (this directly fits your "don't grind one
                                        thing" goal — and friends will feel it).

    Pick one, or blend several. Keep it MONOTONIC (gaining more XP in a skill
    must never lower the score) so test_scoring.py's property test passes.
    """
    raise NotImplementedError(
        "score_player is your contribution — read the docstring above and "
        "osrs/README.md, implement it, then run: python -m pytest osrs/"
    )


def rank_gains(gains_by_player: dict[str, list[dict]]) -> list[dict]:
    """Rank players best-first using score_player. (Plumbing — already done.)

    Returns [{"rsn", "score", "rank"}], rank 1 = best. Ties share the lower place
    (standard competition ranking: 1, 2, 2, 4).
    """
    scored = [
        {"rsn": rsn, "score": float(score_player(gains))}
        for rsn, gains in gains_by_player.items()
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    for i, row in enumerate(scored):
        if i > 0 and row["score"] == scored[i - 1]["score"]:
            row["rank"] = scored[i - 1]["rank"]
        else:
            row["rank"] = i + 1
    return scored
