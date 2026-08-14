"""
Point-in-time physical join + derived features
==============================================
Turns the raw tables into ``bout_wrestler``: the analysis-ready, *tidy* table
with one row per (bout, wrestler) — i.e. two rows per bout, each from one man's
point of view. That shape makes "win rate by <physical attribute>" a one-line
GROUP BY, and "win rate by size *mismatch*" (own minus opponent) trivial too.

The hard part is honesty about time. Measurements are change-points, so a bout
in 2011 must be joined to the wrestler's size *as recorded by 2011* — not their
career-latest weight. That resolution is :func:`resolve_measurement`, the one
piece left for you to define, because the policy is a real analytical choice.

Run (after build.py has populated the DB):
    python -m sumo.physical --verify
"""

import logging
import sqlite3
import argparse
import pathlib
from collections import defaultdict

log = logging.getLogger("sumo.physical")

DB_PATH = pathlib.Path(__file__).parent / "data" / "sumo.db"

DERIVED_SCHEMA = """
DROP TABLE IF EXISTS bout_wrestler;
CREATE TABLE bout_wrestler (
    basho_id        TEXT NOT NULL,
    division        TEXT NOT NULL,
    day             INTEGER NOT NULL,
    match_no        INTEGER NOT NULL,
    rikishi_id      INTEGER NOT NULL,   -- the wrestler this row is "about"
    opp_id          INTEGER NOT NULL,
    is_win          INTEGER NOT NULL,   -- did rikishi_id win this bout?
    -- own physicals, resolved as-of basho_id
    height_cm       REAL,
    weight_kg       REAL,
    bmi             REAL,
    age_years       REAL,
    rank_value      INTEGER,            -- lower = higher rank (Yokozuna 1E = 101)
    -- opponent physicals, resolved as-of basho_id
    opp_height_cm   REAL,
    opp_weight_kg   REAL,
    opp_bmi         REAL,
    opp_age_years   REAL,
    opp_rank_value  INTEGER,
    -- matchup differentials (own minus opponent; the "advantage" this man had)
    weight_adv      REAL,
    height_adv      REAL,
    bmi_adv         REAL,
    age_adv         REAL,
    rank_adv        INTEGER,            -- opp_rank_value - rank_value (>0 = you outrank him)
    kimarite        TEXT,
    PRIMARY KEY (basho_id, division, day, match_no, rikishi_id)
);
CREATE INDEX IF NOT EXISTS idx_bw_rikishi ON bout_wrestler(rikishi_id);
CREATE INDEX IF NOT EXISTS idx_bw_weight  ON bout_wrestler(weight_kg);
"""


# ═══════════════════════════════════════════════════════════════════════════
#  YOUR CONTRIBUTION — the point-in-time measurement policy
# ═══════════════════════════════════════════════════════════════════════════

def resolve_measurement(measurements: list[dict], basho_id: str) -> tuple[float | None, float | None]:
    """Return this wrestler's (height_cm, weight_kg) AS OF ``basho_id``.

    ``measurements`` is the wrestler's change-point history, PRE-SORTED ascending
    by basho_id. Each item is ``{'basho_id': 'YYYYMM', 'height_cm': float|None,
    'weight_kg': float|None}``. basho_id strings compare chronologically, so
    ``m['basho_id'] <= basho_id`` means "recorded at or before this tournament".

    WHY THIS MATTERS — the policy silently shapes every conclusion downstream:

      • Most-recent-at-or-before (strict point-in-time): only use what was known
        by then. Causally clean, but a bout *before* a wrestler's first recorded
        measurement gets nothing — you lose early-career bouts.

      • Nearest overall (before OR after): if nothing was recorded before the
        bout, borrow the closest *later* measurement. Weight moves slowly, so
        this recovers those early bouts at the cost of a little hindsight.

      • What to return when the history is empty or all-after with a strict
        policy: (None, None) drops the bout from physical analysis (unbiased but
        smaller n); borrowing the earliest keeps it (fuller but slightly biased).

    Return ``(None, None)`` when you truly can't resolve it — callers treat that
    as "unknown" and simply omit those physicals (never a fake 0).

    RECOMMENDATION (say the word and I'll drop this in): most-recent-at-or-before,
    and if none exists, fall back to the earliest recorded measurement — maximizes
    usable bouts while staying point-in-time wherever the data allows.
    """
    # POLICY: most-recent-at-or-before, with earliest-recorded as the fallback.
    # (Claude filled this in with the recommended default so the deep dive isn't
    #  blocked — swap the body to change the policy; everything else re-derives.)
    if not measurements:
        return (None, None)
    best = None
    for m in measurements:                     # ascending by basho_id
        if m["basho_id"] <= basho_id:
            best = m                            # keep advancing to the latest ≤ bout
        else:
            break                              # sorted: nothing later can qualify
    if best is None:                           # bout precedes the first measurement
        best = measurements[0]                 # fall back to earliest recorded
    return (best.get("height_cm"), best.get("weight_kg"))


# ═══════════════════════════════════════════════════════════════════════════
#  Everything below is wired and ready; it uses your function above.
# ═══════════════════════════════════════════════════════════════════════════

def _bmi(height_cm: float | None, weight_kg: float | None) -> float | None:
    if not height_cm or not weight_kg:
        return None
    return round(weight_kg / (height_cm / 100.0) ** 2, 2)


def _age_years(birth_date: str | None, basho_start: str | None) -> float | None:
    """Age (in years) on the tournament's first day."""
    if not birth_date or not basho_start:
        return None
    (by, bm, bd), (ty, tm, td) = (birth_date[:10].split("-"), basho_start[:10].split("-"))
    return round((int(ty) - int(by)) + (int(tm) - int(bm)) / 12.0 + (int(td) - int(bd)) / 365.0, 2)


def _load_lookups(conn: sqlite3.Connection):
    """Pull the dimensions into memory: measurement history, per-basho rank, bio."""
    measurements: dict[int, list[dict]] = defaultdict(list)
    for rid, bid, h, w in conn.execute(
        "SELECT rikishi_id, basho_id, height_cm, weight_kg FROM measurements ORDER BY rikishi_id, basho_id"
    ):
        measurements[rid].append({"basho_id": bid, "height_cm": h, "weight_kg": w})

    rank: dict[tuple[int, str], int] = {}
    for rid, bid, rv in conn.execute("SELECT rikishi_id, basho_id, rank_value FROM ranks"):
        rank[(rid, bid)] = rv

    birth: dict[int, str] = {}
    for rid, bdate in conn.execute("SELECT id, birth_date FROM rikishi"):
        birth[rid] = bdate

    basho_start: dict[str, str] = {}
    for bid, start in conn.execute("SELECT id, start_date FROM basho"):
        basho_start[bid] = start
    return measurements, rank, birth, basho_start


def _profile(rikishi_id: int, basho_id: str, lookups) -> dict:
    """All resolved-as-of attributes for one wrestler at one tournament."""
    measurements, rank, birth, basho_start = lookups
    height, weight = resolve_measurement(measurements.get(rikishi_id, []), basho_id)
    return {
        "height_cm": height,
        "weight_kg": weight,
        "bmi": _bmi(height, weight),
        "age_years": _age_years(birth.get(rikishi_id), basho_start.get(basho_id)),
        "rank_value": rank.get((rikishi_id, basho_id)),
    }


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 2)


def build_bout_wrestler(conn: sqlite3.Connection) -> int:
    """Expand every bout into two point-of-view rows with full physical features."""
    conn.executescript(DERIVED_SCHEMA)
    lookups = _load_lookups(conn)

    rows = []
    bouts = conn.execute(
        """SELECT basho_id, division, day, match_no, east_id, west_id, winner_id, kimarite
           FROM bouts"""
    ).fetchall()
    for basho_id, division, day, match_no, east_id, west_id, winner_id, kimarite in bouts:
        east = _profile(east_id, basho_id, lookups)
        west = _profile(west_id, basho_id, lookups)
        for me_id, me, opp_id, opp in ((east_id, east, west_id, west), (west_id, west, east_id, east)):
            rows.append({
                "basho_id": basho_id, "division": division, "day": day, "match_no": match_no,
                "rikishi_id": me_id, "opp_id": opp_id,
                "is_win": 1 if winner_id == me_id else 0,
                **me,
                "opp_height_cm": opp["height_cm"], "opp_weight_kg": opp["weight_kg"],
                "opp_bmi": opp["bmi"], "opp_age_years": opp["age_years"],
                "opp_rank_value": opp["rank_value"],
                "weight_adv": _sub(me["weight_kg"], opp["weight_kg"]),
                "height_adv": _sub(me["height_cm"], opp["height_cm"]),
                "bmi_adv": _sub(me["bmi"], opp["bmi"]),
                "age_adv": _sub(me["age_years"], opp["age_years"]),
                "rank_adv": (None if me["rank_value"] is None or opp["rank_value"] is None
                             else opp["rank_value"] - me["rank_value"]),
                "kimarite": kimarite,
            })

    conn.executemany(
        """INSERT INTO bout_wrestler VALUES
           (:basho_id, :division, :day, :match_no, :rikishi_id, :opp_id, :is_win,
            :height_cm, :weight_kg, :bmi, :age_years, :rank_value,
            :opp_height_cm, :opp_weight_kg, :opp_bmi, :opp_age_years, :opp_rank_value,
            :weight_adv, :height_adv, :bmi_adv, :age_adv, :rank_adv, :kimarite)""",
        rows,
    )
    conn.commit()
    return len(rows)


def verify(conn: sqlite3.Connection) -> None:
    n = conn.execute("SELECT COUNT(*) FROM bout_wrestler").fetchone()[0]
    with_wt = conn.execute("SELECT COUNT(*) FROM bout_wrestler WHERE weight_kg IS NOT NULL").fetchone()[0]
    log.info("bout_wrestler rows=%d  (%.1f%% have resolved weight)", n, 100.0 * with_wt / max(n, 1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the point-in-time physical table")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = sqlite3.connect(DB_PATH)
    try:
        n = build_bout_wrestler(conn)
        log.info("Built bout_wrestler: %d rows", n)
        if args.verify:
            verify(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
