"""Hole- and course-level analysis -- the questions the round-level data couldn't
answer: hardest holes at a venue, and a golfer's par-3/4/5 scoring profile.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .db import connect

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"


def hardest_holes(conn, venue: str) -> list:
    """Every hole at a venue, ranked by scoring average vs par (all years pooled)."""
    return conn.execute(
        """
        SELECT phs.hole_num,
               ROUND(AVG(eh.par), 1)     AS par,
               COUNT(*)                  AS plays,
               ROUND(AVG(phs.to_par), 3) AS avg_vs_par,
               ROUND(AVG(phs.strokes), 2) AS avg_strokes
        FROM player_hole_scores phs
        JOIN tournaments t  ON t.event_id = phs.event_id
        JOIN event_holes eh ON eh.event_id = phs.event_id AND eh.hole_num = phs.hole_num
        WHERE t.venue = ?
        GROUP BY phs.hole_num
        ORDER BY avg_vs_par DESC
        """,
        (venue,),
    ).fetchall()


def player_par_splits(conn, name: str) -> list:
    """A player's scoring by hole par (3/4/5) across the whole DB."""
    return conn.execute(
        """
        SELECT eh.par,
               COUNT(*)                            AS holes,
               ROUND(AVG(phs.to_par), 3)           AS avg_vs_par,
               SUM(CASE WHEN phs.to_par < 0 THEN 1 ELSE 0 END) AS under,
               SUM(CASE WHEN phs.to_par = 0 THEN 1 ELSE 0 END) AS level,
               SUM(CASE WHEN phs.to_par > 0 THEN 1 ELSE 0 END) AS over
        FROM player_hole_scores phs
        JOIN players p      ON p.player_id = phs.player_id
        JOIN event_holes eh ON eh.event_id = phs.event_id AND eh.hole_num = phs.hole_num
        WHERE p.name = ? AND eh.par BETWEEN 3 AND 5
        GROUP BY eh.par
        ORDER BY eh.par
        """,
        (name,),
    ).fetchall()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Hole- and course-level analysis.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_course = sub.add_parser("course", help="hole-by-hole difficulty at a venue")
    p_course.add_argument("venue")

    p_player = sub.add_parser("player", help="a player's par-3/4/5 scoring profile")
    p_player.add_argument("player")

    args = parser.parse_args(argv)
    conn = connect(args.db)
    try:
        if args.cmd == "course":
            rows = hardest_holes(conn, args.venue)
            if not rows:
                print(f"no hole data for venue {args.venue!r}")
                return
            print(f"\nHole difficulty @ {args.venue} (hardest first)")
            print(f"  {'hole':>4}{'par':>5}{'plays':>8}{'vs par':>9}{'avg':>8}")
            for r in rows:
                print(f"  {r['hole_num']:>4}{r['par']:>5}{r['plays']:>8}"
                      f"{r['avg_vs_par']:>+9.3f}{r['avg_strokes']:>8.2f}")
        elif args.cmd == "player":
            rows = player_par_splits(conn, args.player)
            if not rows:
                print(f"no hole data for player {args.player!r}")
                return
            print(f"\n{args.player} -- scoring by hole par")
            print(f"  {'par':>4}{'holes':>8}{'vs par':>9}{'under':>7}{'level':>7}{'over':>7}")
            for r in rows:
                print(f"  {r['par']:>4}{r['holes']:>8}{r['avg_vs_par']:>+9.3f}"
                      f"{r['under']:>7}{r['level']:>7}{r['over']:>7}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
