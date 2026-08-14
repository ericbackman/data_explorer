"""
The physical deep dive
======================
Answers the question that started this: how physically-determined is sumo? Runs
off the point-in-time ``bout_wrestler`` table (build it first with physical.py).

Every analysis excludes ``fusen`` — default wins where a wrestler was absent and
no sumo happened — so we only measure actual contests. Because bout_wrestler
holds two rows per bout (one per wrestler), win-rate-by-*advantage* curves are
point-symmetric by construction: winrate(+d) = 1 - winrate(-d). That symmetry is
a built-in consistency check, and the overall win rate is exactly 50%.

    python -m sumo.analyze
"""

import logging
import sqlite3
import argparse
import pathlib

log = logging.getLogger("sumo.analyze")

DB_PATH = pathlib.Path(__file__).parent / "data" / "sumo.db"

FAIR = "kimarite != 'fusen'"   # a real contest, not a walkover


def _binned(conn: sqlite3.Connection, expr: str, width: float,
            where: str = FAIR, min_n: int = 300) -> list[tuple]:
    """Win rate bucketed by ``expr`` (rounded to the nearest ``width``).

    ROUND-to-nearest gives bins centred on multiples of width and is symmetric
    across zero — so a weight-advantage bin of 0 is [-w/2, +w/2), not skewed.
    """
    q = f"""
        SELECT CAST(ROUND(1.0 * {expr} / {width}) AS INT) * {width} AS bin,
               COUNT(*) AS n, ROUND(100.0 * AVG(is_win), 1) AS win_pct
        FROM bout_wrestler
        WHERE {expr} IS NOT NULL AND {where}
        GROUP BY bin HAVING n >= {min_n}
        ORDER BY bin
    """
    return conn.execute(q).fetchall()


def _print_curve(title: str, unit: str, rows: list[tuple]) -> None:
    print(f"\n{title}")
    print("  " + "-" * 52)
    for bin_val, n, win_pct in rows:
        bar = "#" * round(win_pct / 2)
        sign = "+" if bin_val > 0 else ""
        print(f"  {sign}{bin_val:>4}{unit:<3} {win_pct:>5.1f}%  {bar:<50}  n={n:,}")


def headline(conn: sqlite3.Connection) -> None:
    """The single number: what does outweighing your opponent buy you?"""
    print("\n=== DOES SIZE WIN?  (win rate by weight advantage) ===")
    for label, cond in [
        ("outweigh opponent by 40kg+", "weight_adv >= 40"),
        ("outweigh opponent by 20-40kg", "weight_adv >= 20 AND weight_adv < 40"),
        ("within +/-5kg (near-equal)", "ABS(weight_adv) < 5"),
        ("outweighed by 20-40kg", "weight_adv <= -20 AND weight_adv > -40"),
        ("outweighed by 40kg+", "weight_adv <= -40"),
    ]:
        row = conn.execute(
            f"SELECT COUNT(*), ROUND(100.0*AVG(is_win),1) FROM bout_wrestler "
            f"WHERE {cond} AND weight_adv IS NOT NULL AND {FAIR}"
        ).fetchone()
        print(f"  {label:<30} {row[1]:>5.1f}%   (n={row[0]:,})")


def most_lopsided_upsets(conn: sqlite3.Connection) -> None:
    """Biggest giant-killings: winning while most outweighed (career-notable)."""
    print("\n=== BIGGEST SIZE UPSETS (won while most outweighed) ===")
    rows = conn.execute(
        f"""SELECT bw.basho_id, r.shikona_en, ROUND(bw.weight_kg) AS w,
                   o.shikona_en AS opp, ROUND(bw.opp_weight_kg) AS ow,
                   ROUND(bw.opp_weight_kg - bw.weight_kg) AS deficit, bw.kimarite
            FROM bout_wrestler bw
            JOIN rikishi r ON r.id = bw.rikishi_id
            JOIN rikishi o ON o.id = bw.opp_id
            WHERE bw.is_win = 1 AND bw.weight_adv IS NOT NULL AND {FAIR}
            ORDER BY bw.weight_adv ASC LIMIT 5"""
    ).fetchall()
    for basho, name, w, opp, ow, deficit, kimarite in rows:
        print(f"  {basho}: {name} ({w}kg) beat {opp} ({ow}kg) — {deficit}kg lighter, by {kimarite}")


def main() -> None:
    argparse.ArgumentParser(description="Sumo physical deep dive").parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        headline(conn)
        _print_curve("=== Win rate by WEIGHT ADVANTAGE (own - opponent) ===",
                     "kg", _binned(conn, "weight_adv", 10))
        _print_curve("=== Win rate by absolute WEIGHT (confounded by rank) ===",
                     "kg", _binned(conn, "weight_kg", 10))
        _print_curve("=== Win rate by BMI ADVANTAGE ===",
                     "", _binned(conn, "bmi_adv", 2))
        _print_curve("=== Win rate by HEIGHT ADVANTAGE ===",
                     "cm", _binned(conn, "height_adv", 5))
        most_lopsided_upsets(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
