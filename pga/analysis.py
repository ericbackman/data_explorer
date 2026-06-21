"""Leader-conversion analysis: how often does the 36-/54-hole leader win?

The mechanical part (who led after round N) is fully implemented below. The
*policy* part -- what counts as "the leader converting" when players are tied and
when there's a playoff -- is deliberately isolated in ``classify_leader_outcome``
because there's no single right answer, and the choice materially moves the
headline number.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from .db import connect

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"

_LEADERS_SQL = """
WITH cum AS (
    SELECT player_id,
           SUM(strokes)  AS strokes_through,
           COUNT(*)      AS rounds_done
    FROM player_rounds
    WHERE event_id = ? AND round_num <= ? AND is_playoff = 0 AND strokes IS NOT NULL
    GROUP BY player_id
    HAVING COUNT(*) >= ?
)
SELECT player_id, strokes_through
FROM cum
WHERE strokes_through = (SELECT MIN(strokes_through) FROM cum)
ORDER BY player_id
"""


def leaders_after_round(conn: sqlite3.Connection, event_id: int, through: int) -> list[int]:
    """Player ids tied for the lead after ``through`` rounds (regulation only)."""
    rows = conn.execute(_LEADERS_SQL, (event_id, through, through)).fetchall()
    return [r["player_id"] for r in rows]


def event_had_playoff(conn: sqlite3.Connection, event_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM player_rounds WHERE event_id = ? AND is_playoff = 1 LIMIT 1",
        (event_id,),
    ).fetchone()
    return row is not None


# ----------------------------------------------------------------------------
#  >>> THE ONE DECISION THAT IS YOURS, ERIC <<<
#
#  Given the set of co-leaders after a round, the eventual winner, and whether
#  the event went to a playoff, decide whether the leader "converted".
#
#  Trade-offs to weigh (each gives a different, defensible headline number):
#    * Solo vs co-leaders: if three players share the 54-hole lead and one wins,
#      is that a conversion? Counting it inflates the rate; ignoring ties
#      (only scoring events with a SOLO leader) is stricter and more quoted.
#    * Playoffs: the 54-hole leader who loses a playoff led but didn't win.
#      Count as a failure? (Most analysts do.) The `had_playoff` flag lets you.
#    * What you return shapes the report: a bool is simplest; a string label
#      ("solo_converted" / "co_converted" / "failed") lets the report break it out.
#
#  Replace the baseline body below with your policy (≈5-10 lines).
# ----------------------------------------------------------------------------
def classify_leader_outcome(
    leaders: list[int],
    winner_id: int | None,
    had_playoff: bool,
) -> bool | str:
    """BASELINE (v1): leader converts iff the winner was among the co-leaders.

    This counts co-leaders as conversions and treats a playoff win normally.
    It is intentionally simple so you can see a number first, then tighten it.
    """
    if winner_id is None or not leaders:
        return False
    return winner_id in leaders


def conversion_summary(conn: sqlite3.Connection, *, majors_only: bool = False) -> dict:
    """Aggregate conversion rates after rounds 2 and 3 across all qualifying events."""
    where = "WHERE num_rounds >= 4" + (" AND is_major = 1" if majors_only else "")
    events = conn.execute(
        f"SELECT event_id, winner_player_id FROM tournaments {where}"
    ).fetchall()

    counts = {2: {"n": 0, "converted": 0}, 3: {"n": 0, "converted": 0}}
    for ev in events:
        eid, winner = ev["event_id"], ev["winner_player_id"]
        if winner is None:
            continue
        had_playoff = event_had_playoff(conn, eid)
        for through in (2, 3):
            leaders = leaders_after_round(conn, eid, through)
            if not leaders:
                continue
            counts[through]["n"] += 1
            outcome = classify_leader_outcome(leaders, winner, had_playoff)
            if outcome is True or (isinstance(outcome, str) and "converted" in outcome):
                counts[through]["converted"] += 1

    def rate(d: dict) -> float:
        return (d["converted"] / d["n"] * 100) if d["n"] else 0.0

    return {
        "scope": "majors" if majors_only else "all events",
        "after_36_holes": {**counts[2], "rate_pct": round(rate(counts[2]), 1)},
        "after_54_holes": {**counts[3], "rate_pct": round(rate(counts[3]), 1)},
    }


def _table_has_rows(conn, table: str) -> bool:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
    except sqlite3.OperationalError:
        return False


def majors_all_eras(conn) -> list[dict]:
    """Combine Tier-2 history (major_history, 1960-2004) with Tier-1 round-derived
    majors (2005-2026) into historical / modern / combined conversion rows.
    Returns [] when Tier-2 hasn't been loaded."""
    if not _table_has_rows(conn, "major_history"):
        return []

    def pct(won: int, n: int) -> float:
        return round(won / n * 100, 1) if n else 0.0

    h = conn.execute(
        "SELECT COUNT(leader_36_won) n36, COALESCE(SUM(leader_36_won),0) w36, "
        "       COUNT(leader_54_won) n54, COALESCE(SUM(leader_54_won),0) w54 "
        "FROM major_history"
    ).fetchone()
    m = conversion_summary(conn, majors_only=True)
    hist = {"era": "Historical 1960-2004", "n_36": h["n36"], "won_36": h["w36"],
            "n_54": h["n54"], "won_54": h["w54"]}
    modern = {"era": "Modern 2005-2026",
              "n_36": m["after_36_holes"]["n"], "won_36": m["after_36_holes"]["converted"],
              "n_54": m["after_54_holes"]["n"], "won_54": m["after_54_holes"]["converted"]}
    combined = {"era": "Combined 1960-2026",
                "n_36": hist["n_36"] + modern["n_36"], "won_36": hist["won_36"] + modern["won_36"],
                "n_54": hist["n_54"] + modern["n_54"], "won_54": hist["won_54"] + modern["won_54"]}
    rows = [hist, modern, combined]
    for r in rows:
        r["rate_36"] = pct(r["won_36"], r["n_36"])
        r["rate_54"] = pct(r["won_54"], r["n_54"])
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Leader-conversion report.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = connect(args.db)
    try:
        for majors_only in (False, True):
            s = conversion_summary(conn, majors_only=majors_only)
            print(f"\n=== {s['scope']} ===")
            for label, key in (("36-hole (Day 2)", "after_36_holes"),
                               ("54-hole (Day 3)", "after_54_holes")):
                d = s[key]
                print(f"  {label} leader won: {d['converted']}/{d['n']} = {d['rate_pct']}%")

        eras = majors_all_eras(conn)
        if eras:
            print("\n=== majors, all eras (Tier-2 history + Tier-1 rounds) ===")
            for era in eras:
                print(f"  {era['era']:<22} 36-hole {era['won_36']}/{era['n_36']} "
                      f"({era['rate_36']}%)   54-hole {era['won_54']}/{era['n_54']} ({era['rate_54']}%)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
