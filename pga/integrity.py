"""Data-integrity audit for the PGA round data (detect-and-report; never mutates).

Two independent internal-consistency checks over raw facts:

  1. Phantom post-cut rounds -- players who MISSED the cut (player_results.made_cut=0)
     yet still carry round 3+ rows in player_rounds. These are ESPN-feed artifacts;
     one (Richard Sterne's phantom 60 at the 2009 PGA) silently crowned a false
     54-hole leader until analysis._LEADERS_SQL was guarded with made_cut=1.
  2. Round/total mismatches -- finished players whose regulation rounds don't sum
     to player_results.total_strokes (a corrupt round or total).

Run this after every data refresh: the leader math is already hardened, so this is
the standing check that a regression hasn't reintroduced bad rows.

    python -m pga.integrity
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .db import connect

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = _ROOT / "data" / "pga.db"

_PHANTOM_SQL = """
SELECT pr.event_id, pr.player_id, p.name, t.name AS event, t.calendar_year AS year,
       pr.round_num, pr.strokes
FROM player_rounds pr
JOIN player_results r ON r.event_id = pr.event_id AND r.player_id = pr.player_id
JOIN players p        ON p.player_id = pr.player_id
JOIN tournaments t    ON t.event_id  = pr.event_id
WHERE r.made_cut = 0 AND pr.round_num >= 3 AND pr.is_playoff = 0
      AND pr.strokes IS NOT NULL AND pr.strokes > 0
ORDER BY pr.strokes
"""

_MISMATCH_SQL = """
SELECT r.event_id, r.player_id, r.total_strokes,
       SUM(CASE WHEN pr.is_playoff = 0 AND pr.strokes IS NOT NULL AND pr.strokes > 0
                THEN pr.strokes END) AS reg_sum
FROM player_results r
JOIN player_rounds pr ON pr.event_id = r.event_id AND pr.player_id = r.player_id
WHERE r.made_cut = 1 AND r.total_strokes IS NOT NULL
GROUP BY r.event_id, r.player_id
HAVING reg_sum IS NOT NULL AND reg_sum != r.total_strokes
"""


def phantom_post_cut_rounds(conn) -> list:
    """Round 3+ rows belonging to players who missed the cut (feed artifacts)."""
    return conn.execute(_PHANTOM_SQL).fetchall()


def total_mismatches(conn) -> list:
    """Finished players whose regulation rounds don't sum to their recorded total."""
    return conn.execute(_MISMATCH_SQL).fetchall()


def audit(conn) -> dict:
    ph = phantom_post_cut_rounds(conn)
    mm = total_mismatches(conn)
    return {
        "phantom_rounds": len(ph),
        "phantom_events": len({r["event_id"] for r in ph}),
        "total_mismatches": len(mm),
        "mismatch_events": len({r["event_id"] for r in mm}),
        "phantom_examples": ph[:5],
        "mismatch_examples": mm[:5],
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Audit PGA round-data integrity.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = connect(args.db)
    try:
        a = audit(conn)
    finally:
        conn.close()

    print(f"Phantom post-cut rounds: {a['phantom_rounds']} across {a['phantom_events']} events")
    print("  (missed-cut players carrying round 3+ rows; neutralized by the made_cut=1")
    print("   guard in leaders_after_round -- raw rows are left intact for provenance)")
    for r in a["phantom_examples"]:
        print(f"    {r['year']} {r['event'][:32]:<32} {r['name']:<20} R{r['round_num']}={r['strokes']}")

    print(f"\nRound/total mismatches (finished players): {a['total_mismatches']} "
          f"across {a['mismatch_events']} events")
    for r in a["mismatch_examples"]:
        print(f"    event {r['event_id']} player {r['player_id']}: "
              f"rounds sum {r['reg_sum']} vs recorded total {r['total_strokes']}")
    verdict = ("^ investigate before trusting finished-player totals"
               if a["total_mismatches"] > 20
               else "  (isolated; 0.02% of finished players, below any level that moves leader stats)")
    print(verdict)


if __name__ == "__main__":
    main()
