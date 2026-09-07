"""Export one game's field-goal attempts as shot-field JSON.

    python -m nba.shotfield.export_shots --game-id 0020500591 -o /tmp/game.json
    python -m nba.shotfield.export_shots --player "Kobe Bryant" --pts 81 -o /tmp/kobe81.json

Reads nba.db read-only. The Blender scene never touches sqlite: the database is
3.6 GB and lives on Windows, the renderer runs on homebase, and a JSON file is
the whole contract between them.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

from . import archetypes

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "nba.db"
PERIOD_SECONDS = 720


def connect(db_path=None):
    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        raise FileNotFoundError("nba.db not found at %s" % path)
    return sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)


def elapsed_seconds(period, clock):
    """PBP clock is an ISO-8601 duration REMAINING in the period ('PT09M49.00S')."""
    match = re.match(r"PT(\d+)M([\d.]+)S", clock or "")
    if not match:
        return 0.0
    remaining = int(match.group(1)) * 60 + float(match.group(2))
    return (int(period) - 1) * PERIOD_SECONDS + (PERIOD_SECONDS - remaining)


def resolve_game(conn, game_id=None, player=None, pts=None):
    """Return (game_id, player_id, player_name). Raises rather than guessing."""
    if game_id and player:
        row = conn.execute(
            "select player_id, player_name from players where player_name = ?",
            (player,)).fetchone()
        if not row:
            raise LookupError("no player named %r" % player)
        return game_id, row[0], row[1]
    if player and pts is not None:
        rows = conn.execute(
            """select pg.game_id, p.player_id, p.player_name
               from player_game pg join players p using(player_id)
               where p.player_name = ? and pg.pts = ?""", (player, pts)).fetchall()
        if not rows:
            raise LookupError("no game where %s scored %s" % (player, pts))
        if len(rows) > 1:
            raise LookupError("%s scored %s in %d games; pass --game-id"
                              % (player, pts, len(rows)))
        return rows[0]
    raise ValueError("need --game-id plus --player, or --player plus --pts")


def export(conn, game_id, player_id, player_name):
    meta = conn.execute(
        "select game_date, home_pts, away_pts from games where game_id = ?",
        (game_id,)).fetchone()
    if not meta:
        raise LookupError("no game %r" % game_id)
    game_date, home_pts, away_pts = meta

    rows = conn.execute(
        """select period, clock, sub_type, shot_result, shot_value,
                  shot_x, shot_y, shot_distance, description
           from play_by_play
           where game_id = ? and is_field_goal = 1 and person_id = ?
           order by action_number""", (game_id, player_id)).fetchall()
    if not rows:
        raise LookupError("no field-goal attempts for %s in %s" % (player_name, game_id))

    shots = []
    for period, clock, sub_type, result, value, x, y, dist, desc in rows:
        made = result == "Made"
        shots.append(archetypes.classify({
            "period": period,
            "t": round(elapsed_seconds(period, clock), 1),
            "sub_type": sub_type,
            "made": made,
            "value": value,
            # PBP coordinates are tenths of a foot, origin at the basket
            "x": x / 10.0,
            "y": y / 10.0,
            "dist": dist,
            # assists exist only on makes; a miss carries no signal either way
            "assisted": ("AST)" in (desc or "")) if made else None,
        }))

    # Cross-check against the box score. If these disagree, the PBP feed is
    # incomplete for this game and the render would quietly omit shots.
    box = conn.execute(
        "select fga, fgm, pts from player_game where game_id = ? and player_id = ?",
        (game_id, player_id)).fetchone()
    made_count = sum(1 for s in shots if s["made"])
    if box and box[0] != len(shots):
        log.warning("PBP has %d attempts but the box score says %d; PBP may be incomplete",
                    len(shots), box[0])

    return {
        "game_id": game_id,
        "player": player_name,
        "date": game_date,
        "final": "%s - %s" % (home_pts, away_pts),
        "pts": box[2] if box else None,
        "box_fga": box[0] if box else None,
        "box_fgm": box[1] if box else None,
        "made": made_count,
        "missing_labels": archetypes.missing_labels(game_date),
        "shots": shots,
    }


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id")
    parser.add_argument("--player")
    parser.add_argument("--pts", type=int)
    parser.add_argument("--db")
    parser.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)

    conn = connect(args.db)
    game_id, player_id, player_name = resolve_game(conn, args.game_id, args.player, args.pts)
    payload = export(conn, game_id, player_id, player_name)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)

    counts = archetypes.summarise(payload["shots"])
    print("%s, %s (%s)" % (payload["player"], payload["date"], payload["final"]))
    print("  shots %d (box fga %s), made %d (box fgm %s)"
          % (len(payload["shots"]), payload["box_fga"], payload["made"], payload["box_fgm"]))
    for signal in ("archetype", "motion", "entry"):
        print("  %-10s %s" % (signal, dict(sorted(counts[signal].items()))))
    if payload["missing_labels"]:
        print("  ⚠ labels not yet recorded on this date: %s"
              % ", ".join(payload["missing_labels"]))
    print("  -> %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
