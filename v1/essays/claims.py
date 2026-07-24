"""Turn verified data into a source-locked claim payload for the script agent.

The agent may state ONLY numbers that appear here; every headline claim carries the
data behind it. The payload also carries `allowed` -- the exact numeric allow-list
the audit (essays.script.audit_script) enforces -- so a 10-minute script can grow
by adding *verified* beats, never by inventing filler stats.
"""
from __future__ import annotations

from pga.betting import closer_rankings, worst_closers

from essays.beats import (biggest_blown, biggest_comebacks, major_eras,
                          margin_buckets, sunday_scoring)


def build_claims(conn, min_leads: int = 5) -> dict:
    rk = closer_rankings(conn, min_leads=min_leads)
    rows = rk["rows"]
    best, worst = rows[:8], worst_closers(rows)[:8]
    majors_pct = closer_rankings(conn, majors_only=True)["field_pct"]
    margins = margin_buckets(conn)
    blown = biggest_blown(conn)
    comebacks = biggest_comebacks(conn)
    sun = sunday_scoring(conn)
    me = major_eras(conn)

    claims: list[dict] = [
        {"id": "field_rate",
         "text": f"The 54-hole leader (co-leaders included) wins just {rk['field_pct']}% "
                 f"of the time on the PGA Tour, 2005-2026 (72-hole events)."},
        {"id": "majors",
         "text": f"In majors the 54-hole lead holds up better, not worse: {majors_pct}%."},
        {"id": "sunday",
         "text": f"54-hole leaders average {sun['avg_final']} in the final round vs "
                 f"{sun['avg_first3']} over the first three -- {sun['gap']:+g} strokes."},
    ]
    for label, d in margins.items():
        claims.append({"id": f"margin::{label}",
                       "text": f"Leading by {label} after 54 holes converts {d['pct']}% "
                               f"({d['won']}/{d['n']})."})
    for r in best:
        claims.append({"id": f"best::{r['player']}",
                       "text": f"{r['player']}: {r['won']} of {r['led']} 54-hole leads "
                               f"({r['convert_pct']}%), {r['above_exp']:+g} vs average."})
    for r in worst:
        claims.append({"id": f"worst::{r['player']}",
                       "text": f"{r['player']} led {r['led']} times after 54 holes, won {r['won']}."})
    for b in blown[:6]:
        claims.append({"id": f"blown::{b['year']}",
                       "text": f"{b['year']} {b['event']}: {b['leader']} led by {b['margin']} "
                               f"and lost to {b['winner']}."})
    for cb in comebacks[:4]:
        claims.append({"id": f"comeback::{cb['year']}",
                       "text": f"{cb['year']} {cb['event']}: {cb['winner']} won from "
                               f"{cb['deficit']} back after 54 holes."})
    if me:
        claims.append({"id": "majors_longrun",
                       "text": f"Across {me['combined_n']} majors, 1960-2026, the 54-hole "
                               f"leader won {me['combined_pct']}% -- era-stable "
                               f"({me['historical_pct']}% historical, {me['modern_pct']}% modern)."})
        claims.append({"id": "norman",
                       "text": f"Greg Norman held or shared the 54-hole lead at a major "
                               f"{me['norman_led']} times and won {me['norman_won']} (the 1986 Open)."})

    allowed: set[float] = {
        float(rk["field_pct"]), float(rk["total_leads"]), float(majors_pct),
        float(sun["avg_final"]), float(sun["avg_first3"]), float(sun["gap"]), float(sun["n"]),
    }
    for r in best + worst:
        allowed.update(float(v) for v in (
            r["led"], r["won"], r["convert_pct"], abs(r["above_exp"]),
            r["wilson_pct"], r["expected"]))
    for d in margins.values():
        allowed.update(float(v) for v in (d["pct"], d["n"], d["won"]))
    for b in blown:
        allowed.add(float(b["margin"]))
    for cb in comebacks:
        allowed.add(float(cb["deficit"]))
    if me:
        allowed.update(float(v) for v in (
            me["combined_n"], me["combined_won"], me["combined_pct"],
            me["historical_pct"], me["modern_pct"], me["norman_led"], me["norman_won"]))

    return {"field_pct": rk["field_pct"], "total_leads": rk["total_leads"],
            "majors_pct": majors_pct, "best": best, "worst": worst, "margins": margins,
            "blown": blown, "comebacks": comebacks, "sunday": sun, "major_eras": me,
            "claims": claims, "allowed": allowed}


def allowed_numbers(payload: dict) -> set[float]:
    """Every numeric value the script is permitted to state (derived stats only)."""
    return set(payload["allowed"])
