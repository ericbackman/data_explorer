"""Unit test for the strokes-gained derivation on a controlled tiny dataset."""
import sqlite3

from pga.db import init_db
from pga.sg import build_field_avgs, player_sg


def _setup():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute("INSERT INTO players (player_id, name) VALUES (1, 'A'), (2, 'B')")
    # event 100, round 1, two par-4 holes. Field avgs: hole1=5, hole2=4.
    conn.executemany(
        "INSERT INTO player_hole_scores (event_id, player_id, round_num, hole_num, strokes, to_par) "
        "VALUES (?,?,?,?,?,?)",
        [(100, 1, 1, 1, 4, 0), (100, 2, 1, 1, 6, 2),
         (100, 1, 1, 2, 3, -1), (100, 2, 1, 2, 5, 1)],
    )
    conn.executemany("INSERT INTO event_holes (event_id, hole_num, par) VALUES (?,?,?)",
                     [(100, 1, 4), (100, 2, 4)])
    conn.commit()
    return conn


def test_sg_math():
    conn = _setup()
    assert build_field_avgs(conn) == 2  # two (event, round, hole) baselines

    a = player_sg(conn, "A")  # beat the field by 1 on each hole
    assert a["total_sg"] == 2.0 and a["rounds"] == 1 and a["sg_per_round"] == 2.0
    b = player_sg(conn, "B")  # lost 1 on each hole
    assert b["total_sg"] == -2.0

    par4 = next(r for r in a["by_par"] if r["par"] == 4)
    assert par4["total_sg"] == 2.0 and par4["holes"] == 2
