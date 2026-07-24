"""Extra data-backed segments for the closer video -- everything a 10-minute essay
needs beyond the headline ranking, each COMPUTED (and thus verifiable) from pga.db.

Beats: conversion by 54-hole lead MARGIN, the biggest BLOWN leads (named events),
whether leaders TIGHTEN UP on Sunday, majors vs regular, and biggest COMEBACKS.
All built on the made-cut-guarded leader logic (post phantom-round fix), so a
missed-cut phantom can never sneak into a "leader" here either.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pga.analysis import majors_all_eras
from pga.betting import DEFAULT_DB, _is_staggered_start, closer_rankings
from pga.db import connect

logger = logging.getLogger(__name__)

_EVENTS_SQL = """
SELECT event_id, winner_player_id, name, calendar_year, is_major
FROM tournaments
WHERE num_rounds = 4 AND winner_player_id IS NOT NULL
  AND (field_size IS NULL OR field_size >= 30)
"""

_CUM_SQL = """
SELECT pr.player_id, SUM(pr.strokes) cum, COUNT(*) n
FROM player_rounds pr
JOIN player_results r ON r.event_id = pr.event_id AND r.player_id = pr.player_id
WHERE pr.event_id = ? AND pr.round_num <= ? AND pr.is_playoff = 0
  AND pr.strokes IS NOT NULL AND pr.strokes > 0 AND r.made_cut = 1
GROUP BY pr.player_id HAVING n >= ?
ORDER BY cum
"""


def _events(conn):
    return [e for e in conn.execute(_EVENTS_SQL)
            if not _is_staggered_start(e["name"], e["calendar_year"])]


def _name(conn, pid):
    row = conn.execute("SELECT name FROM players WHERE player_id=?", (pid,)).fetchone()
    return row["name"] if row else str(pid)


def _standing(conn, event_id, through=3):
    """Leaders, their cumulative, sole-leader margin over the best chaser, and all
    (player_id -> cum) for made-cut players through `through` rounds."""
    rows = conn.execute(_CUM_SQL, (event_id, through, through)).fetchall()
    if len(rows) < 2:
        return None
    lead = rows[0]["cum"]
    leaders = [r["player_id"] for r in rows if r["cum"] == lead]
    second = next((r["cum"] for r in rows if r["cum"] > lead), None)
    margin = 0 if len(leaders) > 1 or second is None else second - lead
    return {"leaders": leaders, "lead_cum": lead, "margin": margin,
            "cum": {r["player_id"]: r["cum"] for r in rows}}


def margin_buckets(conn) -> dict:
    """PER-PLAYER conversion by 54-hole margin. Every (co-)leader is charged an
    appearance (only one of them can win), consistent with closer_rankings -- so the
    co-lead bucket is an individual's odds when tied, NOT the event-level "did anyone
    tied win". This keeps the ladder honest: tied is the weakest leading position."""
    order = ["co-lead", "1 shot", "2 shots", "3 shots", "4+ shots"]
    buckets = {k: [0, 0] for k in order}
    for e in _events(conn):
        st = _standing(conn, e["event_id"])
        if not st:
            continue
        m = st["margin"]
        label = ("co-lead" if m == 0 else "1 shot" if m == 1 else "2 shots" if m == 2
                 else "3 shots" if m == 3 else "4+ shots")
        buckets[label][0] += len(st["leaders"])   # charge every (co-)leader an appearance
        if e["winner_player_id"] in st["leaders"]:
            buckets[label][1] += 1                  # exactly one of them can convert
    return {k: {"n": v[0], "won": v[1], "pct": round(100 * v[1] / v[0], 1) if v[0] else 0.0}
            for k, v in buckets.items()}


def biggest_blown(conn, min_margin=3, limit=12) -> list:
    out = []
    for e in _events(conn):
        st = _standing(conn, e["event_id"])
        if not st or st["margin"] < min_margin or e["winner_player_id"] in st["leaders"]:
            continue
        out.append({"year": e["calendar_year"], "event": e["name"],
                    "leader": _name(conn, st["leaders"][0]), "margin": st["margin"],
                    "winner": _name(conn, e["winner_player_id"]), "is_major": e["is_major"]})
    out.sort(key=lambda r: -r["margin"])
    return out[:limit]


def biggest_comebacks(conn, limit=8) -> list:
    out = []
    for e in _events(conn):
        st = _standing(conn, e["event_id"])
        if not st or e["winner_player_id"] in st["leaders"]:
            continue
        wcum = st["cum"].get(e["winner_player_id"])
        if wcum is None:
            continue
        out.append({"year": e["calendar_year"], "event": e["name"],
                    "winner": _name(conn, e["winner_player_id"]),
                    "deficit": wcum - st["lead_cum"], "is_major": e["is_major"]})
    out.sort(key=lambda r: -r["deficit"])
    return out[:limit]


def sunday_scoring(conn) -> dict:
    """Do 54-hole leaders tighten up? Their final round vs their first-three average."""
    r4, early = [], []
    for e in _events(conn):
        st = _standing(conn, e["event_id"])
        if not st:
            continue
        for lid in st["leaders"]:
            a = conn.execute(
                "SELECT strokes FROM player_rounds WHERE event_id=? AND player_id=? "
                "AND round_num=4 AND is_playoff=0 AND strokes>0", (e["event_id"], lid)).fetchone()
            b = conn.execute(
                "SELECT AVG(strokes) a FROM player_rounds WHERE event_id=? AND player_id=? "
                "AND round_num<=3 AND is_playoff=0 AND strokes>0", (e["event_id"], lid)).fetchone()
            if a and b and b["a"]:
                r4.append(a["strokes"])
                early.append(b["a"])
    n = len(r4)
    return {"n": n, "avg_final": round(sum(r4) / n, 2), "avg_first3": round(sum(early) / n, 2),
            "gap": round((sum(r4) - sum(early)) / n, 2)}


def major_eras(conn) -> dict | None:
    """Long-run 54-hole conversion in the four majors (1960-2026: major_history +
    Tier-1 rounds) plus the historical anti-Tiger -- Greg Norman's major
    front-running record. None if the deep major history isn't loaded."""
    eras = {e["era"]: e for e in majors_all_eras(conn)}
    if not eras:
        return None
    comb = eras["Combined 1960-2026"]
    norman = conn.execute(
        "SELECT COUNT(*) led, COALESCE(SUM(leader_54_won), 0) won "
        "FROM major_history WHERE leader_54 LIKE '%Norman%'"
    ).fetchone()
    return {
        "combined_n": comb["n_54"], "combined_won": comb["won_54"], "combined_pct": comb["rate_54"],
        "historical_pct": eras["Historical 1960-2004"]["rate_54"],
        "modern_pct": eras["Modern 2005-2026"]["rate_54"],
        "norman_led": norman["led"], "norman_won": norman["won"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args(argv)
    conn = connect(args.db)
    try:
        print("=== conversion by 54-hole lead margin ===")
        for label, d in margin_buckets(conn).items():
            print(f"  {label:<9} {d['won']:>3}/{d['n']:<3} = {d['pct']}%")

        print("\n=== majors vs everything ===")
        allf = closer_rankings(conn)["field_pct"]
        maj = closer_rankings(conn, majors_only=True)["field_pct"]
        print(f"  all events: {allf}%   majors only: {maj}%")

        print("\n=== leaders on Sunday ===")
        s = sunday_scoring(conn)
        print(f"  54-hole leaders avg final round {s['avg_final']} vs {s['avg_first3']} over "
              f"the first three (gap {s['gap']:+}), n={s['n']}")

        print("\n=== biggest BLOWN 54-hole leads (sole leader, 3+ shots, lost) ===")
        for r in biggest_blown(conn):
            tag = " [MAJOR]" if r["is_major"] else ""
            print(f"  {r['year']} {r['event'][:30]:<30} {r['leader']:<18} led by {r['margin']}, "
                  f"lost to {r['winner']}{tag}")

        print("\n=== biggest COMEBACKS (winner's 54-hole deficit) ===")
        for r in biggest_comebacks(conn):
            tag = " [MAJOR]" if r["is_major"] else ""
            print(f"  {r['year']} {r['event'][:30]:<30} {r['winner']:<18} from {r['deficit']} back{tag}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
