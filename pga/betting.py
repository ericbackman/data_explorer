"""Derived betting intel for tournaments -- especially majors.

Everything here is computed from the Tier-1 tables; there are no extra data
sources. The four angles that actually move a pre-tournament read:

  * course_history  -- how players have fared at THIS venue (Augusta is the same
                       course every year, so this is the single best major signal)
  * player_form     -- recent finishes and scoring
  * major_record    -- career major track record
  * closers         -- who converts the 54-hole lead vs who wilts

Usage:
    python -m pga_data.betting course "Augusta National Golf Club"
    python -m pga_data.betting form "Scottie Scheffler"
    python -m pga_data.betting majors --name "Masters Tournament"
    python -m pga_data.betting closers
"""
from __future__ import annotations

import argparse
import math
import sqlite3
from pathlib import Path

from .analysis import leaders_after_round
from .db import connect

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"

# Aggregate a player's record over a filtered set of events.
_RECORD_SQL = """
SELECT p.player_id, p.name,
    COUNT(*)                                              AS apps,
    SUM(r.made_cut)                                       AS cuts_made,
    SUM(CASE WHEN r.position_numeric = 1  THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN r.position_numeric <= 5  THEN 1 ELSE 0 END) AS top5,
    SUM(CASE WHEN r.position_numeric <= 10 THEN 1 ELSE 0 END) AS top10,
    MIN(r.position_numeric)                              AS best,
    ROUND(AVG(CASE WHEN r.position_numeric IS NOT NULL
                   THEN r.position_numeric END), 1)      AS avg_finish,
    ROUND(AVG(CASE WHEN r.made_cut = 1 THEN r.total_to_par END), 1) AS avg_to_par
FROM player_results r
JOIN tournaments t ON t.event_id = r.event_id
JOIN players p     ON p.player_id = r.player_id
WHERE {where}
GROUP BY p.player_id
HAVING apps >= ?
ORDER BY top10 DESC, wins DESC, avg_finish ASC
"""


def course_history(conn, venue: str, min_apps: int = 3) -> list[sqlite3.Row]:
    sql = _RECORD_SQL.format(where="t.venue = ?")
    return conn.execute(sql, (venue, min_apps)).fetchall()


def major_record(conn, name: str | None = None, min_apps: int = 4) -> list[sqlite3.Row]:
    if name:
        sql = _RECORD_SQL.format(where="t.is_major = 1 AND t.name = ?")
        return conn.execute(sql, (name, min_apps)).fetchall()
    sql = _RECORD_SQL.format(where="t.is_major = 1")
    return conn.execute(sql, (min_apps,)).fetchall()


def player_form(conn, name: str, last_n: int = 12) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT t.start_date, t.name, t.is_major, r.position, r.total_to_par, r.made_cut
        FROM player_results r
        JOIN tournaments t ON t.event_id = r.event_id
        JOIN players p     ON p.player_id = r.player_id
        WHERE p.name = ?
        ORDER BY t.start_date DESC
        LIMIT ?
        """,
        (name, last_n),
    ).fetchall()


def _lead_counts(
    conn, through: int, majors_only: bool,
    exclude_staggered: bool = True, min_field: int = 30,
) -> tuple[dict[int, int], dict[int, int]]:
    """(led, won) per player: how many times each (co-)led after `through` rounds,
    and how many of those they went on to win.

    Events excluded so the record isn't silently polluted:
      * events with an unknown winner (can't attribute a conversion),
      * staggered-start finales (Tour Championship since 2019), whose raw-stroke
        "leader" is a scoring artifact rather than a real 54-hole lead, and
      * unofficial / limited-field exhibitions below `min_field` players (e.g. the
        18-player Hero World Challenge) -- leading an 18-man silly-season event is
        not a tour front-runner situation. Events with unknown field size are kept.
    """
    # num_rounds = 4 keeps standard 72-hole events; a "54-hole leader" only means
    # "entering the final round" at 72 holes (excludes the 90-hole Bob Hope, etc.).
    where = "num_rounds = 4" + (" AND is_major = 1" if majors_only else "")
    events = conn.execute(
        f"SELECT event_id, winner_player_id, name, calendar_year, field_size "
        f"FROM tournaments WHERE {where}"
    ).fetchall()

    led: dict[int, int] = {}
    won: dict[int, int] = {}
    for ev in events:
        if ev["winner_player_id"] is None:
            continue
        if ev["field_size"] is not None and ev["field_size"] < min_field:
            continue
        if exclude_staggered and _is_staggered_start(ev["name"], ev["calendar_year"]):
            continue
        for pid in leaders_after_round(conn, ev["event_id"], through):
            led[pid] = led.get(pid, 0) + 1
            if pid == ev["winner_player_id"]:
                won[pid] = won.get(pid, 0) + 1
    return led, won


def _wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for a conversion rate (0-1).

    This is the volume-accountability knob: a 5-for-5 record has a wide interval
    and thus a low floor, so it cannot outrank a proven high-volume closer.
    z=1.96 -> 95% confidence.
    """
    if n == 0:
        return 0.0
    phat = wins / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return (centre - margin) / denom


def closers(conn, through: int = 3, min_leads: int = 4, majors_only: bool = False) -> list[dict]:
    """Per-player: how often they won when (co-)leading after `through` rounds.
    Sorted by raw conversion rate; see `closer_rankings` for the volume-aware sort."""
    led, won = _lead_counts(conn, through, majors_only)
    names = {r["player_id"]: r["name"] for r in conn.execute("SELECT player_id, name FROM players")}
    rows = []
    for pid, n_led in led.items():
        if n_led < min_leads:
            continue
        n_won = won.get(pid, 0)
        rows.append({
            "player": names.get(pid, str(pid)),
            "led": n_led,
            "won": n_won,
            "convert_pct": round(n_won / n_led * 100, 1),
        })
    rows.sort(key=lambda r: (-r["convert_pct"], -r["led"]))
    return rows


def closer_rankings(
    conn, through: int = 3, min_leads: int = 5, majors_only: bool = False
) -> dict:
    """Volume-accountable 54-hole closer records -- the video's data stage.

    Policy (Eric, 2026-07): co-leaders included; >= `min_leads` appearances to be
    ranked; ranked by the Wilson lower bound so small samples can't top the chart;
    `above_exp` = conversions above what an average front-runner (the field base
    rate) would manage from the same number of leads -- the volume-rewarding stat.

    Returns {field_pct, total_leads, rows} with rows sorted best-closer first.
    """
    led, won = _lead_counts(conn, through, majors_only)
    total_led = sum(led.values())
    total_won = sum(won.values())
    field_rate = total_won / total_led if total_led else 0.0

    names = {r["player_id"]: r["name"] for r in conn.execute("SELECT player_id, name FROM players")}
    rows = []
    for pid, n_led in led.items():
        if n_led < min_leads:
            continue
        n_won = won.get(pid, 0)
        rows.append({
            "player": names.get(pid, str(pid)),
            "led": n_led,
            "won": n_won,
            "convert_pct": round(n_won / n_led * 100, 1),
            "wilson_pct": round(_wilson_lower_bound(n_won, n_led) * 100, 1),
            "expected": round(field_rate * n_led, 1),
            "above_exp": round(n_won - field_rate * n_led, 1),
        })
    rows.sort(key=lambda r: -r["wilson_pct"])
    return {
        "field_pct": round(field_rate * 100, 1),
        "total_leads": total_led,
        "rows": rows,
    }


def worst_closers(rows: list[dict]) -> list[dict]:
    """Order closer rows worst-first for the "who folds" segment.

    The Wilson lower bound saturates at 0 for any winless player, so it can't
    separate 0-for-7 from 0-for-5. Rank instead by conversions above expected
    (most negative first), so the most-failed lead tops the list.
    """
    return sorted(rows, key=lambda r: (r["above_exp"], -r["led"]))


# Events using a staggered / starting-strokes format, where a 54-hole "deficit"
# is a scoring artifact, not a real comeback (FedEx Cup finale since 2019).
_STAGGERED_START_EVENTS = ("tour championship",)


def _is_staggered_start(name: str, year: int | None) -> bool:
    n = (name or "").lower()
    return bool(year and year >= 2019 and any(s in n for s in _STAGGERED_START_EVENTS))


def _leader_total(conn, event_id: int, through: int) -> int | None:
    # made_cut=1 + strokes>0 exclude phantom post-cut rounds (see analysis._LEADERS_SQL).
    return conn.execute(
        "SELECT MIN(s) FROM (SELECT SUM(pr.strokes) s, COUNT(*) n FROM player_rounds pr "
        "JOIN player_results r ON r.event_id=pr.event_id AND r.player_id=pr.player_id "
        "WHERE pr.event_id=? AND pr.round_num<=? AND pr.is_playoff=0 "
        "AND pr.strokes IS NOT NULL AND pr.strokes>0 AND r.made_cut=1 "
        "GROUP BY pr.player_id HAVING n>=?)",
        (event_id, through, through),
    ).fetchone()[0]


def comebacks(conn, name: str, through: int = 3) -> list[dict] | None:
    """A player's wins, each flagged by whether they trailed the lead after
    `through` rounds (a come-from-behind win) and by how many strokes. Returns
    None if the player isn't in the DB."""
    row = conn.execute("SELECT player_id FROM players WHERE name = ?", (name,)).fetchone()
    if not row:
        return None
    pid = row["player_id"]
    wins = conn.execute(
        "SELECT event_id, calendar_year, name, is_major FROM tournaments "
        "WHERE winner_player_id = ? AND num_rounds >= 4 ORDER BY start_date",
        (pid,),
    ).fetchall()
    out = []
    for w in wins:
        eid = w["event_id"]
        led = pid in leaders_after_round(conn, eid, through)
        lead_total = _leader_total(conn, eid, through)
        own = conn.execute(
            "SELECT SUM(strokes) s FROM player_rounds WHERE event_id=? AND player_id=? "
            "AND round_num<=? AND is_playoff=0 AND strokes IS NOT NULL",
            (eid, pid, through),
        ).fetchone()["s"]
        deficit = (own - lead_total) if (own is not None and lead_total is not None) else None
        out.append({
            "year": w["calendar_year"], "event": w["name"], "is_major": bool(w["is_major"]),
            "led": led, "deficit": deficit,
            "staggered": _is_staggered_start(w["name"], w["calendar_year"]),
        })
    return out


# -- pretty printers --------------------------------------------------------

def _print_record(rows, title):
    print(f"\n{title}")
    print(f"  {'player':<24}{'apps':>5}{'cut':>5}{'win':>5}{'t5':>4}{'t10':>5}"
          f"{'best':>6}{'avgFin':>8}{'avgPar':>8}")
    for r in rows[:25]:
        best = r["best"] if r["best"] is not None else "-"
        af = r["avg_finish"] if r["avg_finish"] is not None else "-"
        ap = r["avg_to_par"] if r["avg_to_par"] is not None else "-"
        print(f"  {r['name'][:23]:<24}{r['apps']:>5}{r['cuts_made']:>5}{r['wins']:>5}"
              f"{r['top5']:>4}{r['top10']:>5}{str(best):>6}{str(af):>8}{str(ap):>8}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Betting intel from pga-data.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_course = sub.add_parser("course", help="player history at a venue")
    p_course.add_argument("venue")
    p_course.add_argument("--min-apps", type=int, default=3)

    p_majors = sub.add_parser("majors", help="player major track record")
    p_majors.add_argument("--name", default=None, help="restrict to one major, e.g. 'Masters Tournament'")
    p_majors.add_argument("--min-apps", type=int, default=4)

    p_form = sub.add_parser("form", help="recent results for a player")
    p_form.add_argument("player")
    p_form.add_argument("--last", type=int, default=12)

    p_close = sub.add_parser("closers", help="54-hole lead conversion by player")
    p_close.add_argument("--through", type=int, default=3)
    p_close.add_argument("--majors-only", action="store_true")

    p_back = sub.add_parser("comebacks", help="a player's come-from-behind wins (trailing after 54)")
    p_back.add_argument("player")
    p_back.add_argument("--through", type=int, default=3)

    args = parser.parse_args(argv)
    conn = connect(args.db)
    try:
        if args.cmd == "course":
            _print_record(course_history(conn, args.venue, args.min_apps),
                          f"Course history @ {args.venue}")
        elif args.cmd == "majors":
            label = args.name or "all majors"
            _print_record(major_record(conn, args.name, args.min_apps),
                          f"Major record: {label}")
        elif args.cmd == "form":
            print(f"\nRecent form: {args.player}")
            for r in player_form(conn, args.player, args.last):
                tag = " *major*" if r["is_major"] else ""
                par = f"{r['total_to_par']:+d}" if r["total_to_par"] is not None else "  -"
                print(f"  {r['start_date'][:10]}  {r['position'] or 'CUT':>4}  {par}  {r['name']}{tag}")
        elif args.cmd == "closers":
            rows = closers(conn, args.through, majors_only=args.majors_only)
            scope = "majors" if args.majors_only else "all events"
            print(f"\n54-hole closers ({scope}): won / led after R{args.through}")
            print(f"  {'player':<24}{'led':>5}{'won':>5}{'conv%':>7}")
            for r in rows[:25]:
                print(f"  {r['player'][:23]:<24}{r['led']:>5}{r['won']:>5}{r['convert_pct']:>7}")
        elif args.cmd == "comebacks":
            rows = comebacks(conn, args.player, args.through)
            if rows is None:
                print(f"no player named {args.player!r} in the DB")
            else:
                real = [r for r in rows if not r["led"] and not r["staggered"]]
                print(f"\n{args.player}: {len(real)} come-from-behind wins of {len(rows)} total "
                      f"(trailing outright after R{args.through})")
                for r in rows:
                    if r["led"]:
                        continue
                    tag = " *major*" if r["is_major"] else ""
                    note = "  [staggered start - not a true comeback]" if r["staggered"] else ""
                    print(f"  {r['year']}  from {r['deficit']} back  {r['event']}{tag}{note}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
