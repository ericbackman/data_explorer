"""Strokes-gained vs field, derived free from the hole-by-hole data.

SG-Total is the PGA Tour's headline metric: for each (event, round, hole) the
field's scoring average is the baseline, and a player's strokes-gained on that
hole is (field_avg - their_strokes). We materialize the field averages once
(`build`), then SG aggregations are cheap joins.

Simplification vs the official tour stat: the field baseline includes the player
themselves (negligible bias in a large field) and there's no morning/afternoon
wave adjustment. Good enough to rank performance; not a tour-certified number.

    python -m pga.sg build                       # one-time: materialize field avgs
    python -m pga.sg player "Scottie Scheffler"  # career SG profile + par splits
    python -m pga.sg event "Masters" --year 2024 # SG leaderboard for an event
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .db import connect, init_db

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"

# Shared SG join: every player-hole against its field baseline.
_SG = """
FROM player_hole_scores phs
JOIN hole_field_avg hfa
  ON hfa.event_id = phs.event_id AND hfa.round_num = phs.round_num AND hfa.hole_num = phs.hole_num
"""


def build_field_avgs(conn) -> int:
    """(Re)materialize the field scoring average per (event, round, hole)."""
    init_db(conn)
    conn.execute("DELETE FROM hole_field_avg")
    conn.execute(
        """
        INSERT INTO hole_field_avg (event_id, round_num, hole_num, field_avg, n_players)
        SELECT event_id, round_num, hole_num, AVG(strokes), COUNT(*)
        FROM player_hole_scores
        WHERE strokes IS NOT NULL
        GROUP BY event_id, round_num, hole_num
        """
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM hole_field_avg").fetchone()[0]


def player_sg(conn, name: str) -> dict | None:
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS holes,
               COUNT(DISTINCT phs.event_id) AS events,
               COUNT(DISTINCT phs.event_id || '-' || phs.round_num) AS rounds,
               SUM(hfa.field_avg - phs.strokes) AS total_sg
        {_SG}
        JOIN players p ON p.player_id = phs.player_id
        WHERE p.name = ?
        """,
        (name,),
    ).fetchone()
    if not row or not row["rounds"]:
        return None
    by_par = conn.execute(
        f"""
        SELECT eh.par,
               COUNT(*) AS holes,
               ROUND(SUM(hfa.field_avg - phs.strokes), 1) AS total_sg,
               ROUND(AVG(hfa.field_avg - phs.strokes), 4) AS sg_per_hole
        {_SG}
        JOIN players p      ON p.player_id = phs.player_id
        JOIN event_holes eh ON eh.event_id = phs.event_id AND eh.hole_num = phs.hole_num
        WHERE p.name = ? AND eh.par BETWEEN 3 AND 5
        GROUP BY eh.par ORDER BY eh.par
        """,
        (name,),
    ).fetchall()
    return {
        "events": row["events"], "rounds": row["rounds"],
        "total_sg": round(row["total_sg"], 1),
        "sg_per_round": round(row["total_sg"] / row["rounds"], 3),
        "by_par": by_par,
    }


def event_sg(conn, name: str, year: int) -> tuple[str, list] | None:
    ev = conn.execute(
        "SELECT event_id, name FROM tournaments WHERE name LIKE ? AND calendar_year = ? LIMIT 1",
        (f"%{name}%", year),
    ).fetchone()
    if not ev:
        return None
    rows = conn.execute(
        f"""
        SELECT p.name,
               COUNT(DISTINCT phs.round_num) AS rounds,
               ROUND(SUM(hfa.field_avg - phs.strokes), 2) AS total_sg
        {_SG}
        JOIN players p ON p.player_id = phs.player_id
        WHERE phs.event_id = ?
        GROUP BY phs.player_id
        ORDER BY total_sg DESC
        """,
        (ev["event_id"],),
    ).fetchall()
    return f"{ev['name']} {year}", rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Strokes-gained vs field.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="materialize field scoring averages (run once)")
    p_player = sub.add_parser("player", help="a player's career SG profile")
    p_player.add_argument("player")
    p_event = sub.add_parser("event", help="SG leaderboard for an event")
    p_event.add_argument("event")
    p_event.add_argument("--year", type=int, required=True)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect(args.db)
    try:
        if args.cmd == "build":
            n = build_field_avgs(conn)
            print(f"built hole_field_avg: {n} (event, round, hole) baselines")
        elif args.cmd == "player":
            s = player_sg(conn, args.player)
            if not s:
                print(f"no SG data for {args.player!r} (did you run `sg build`?)")
                return
            print(f"\n{args.player}: SG vs field over {s['events']} events / {s['rounds']} rounds")
            print(f"  total SG: {s['total_sg']:+.1f}   |   SG per round: {s['sg_per_round']:+.3f}")
            print(f"  {'par':>4}{'holes':>8}{'total SG':>11}{'SG/hole':>10}")
            for r in s["by_par"]:
                print(f"  {r['par']:>4}{r['holes']:>8}{r['total_sg']:>+11.1f}{r['sg_per_hole']:>+10.4f}")
        elif args.cmd == "event":
            res = event_sg(conn, args.event, args.year)
            if not res:
                print(f"no event matching {args.event!r} in {args.year}")
                return
            label, rows = res
            print(f"\nStrokes-gained leaderboard -- {label} (top 15)")
            print(f"  {'SG':>7}{'rds':>5}  player")
            for r in rows[:15]:
                print(f"  {r['total_sg']:>+7.2f}{r['rounds']:>5}  {r['name']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
