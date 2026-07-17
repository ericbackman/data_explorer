"""Capture a point-in-time Hiscores snapshot for every tracked clan member.

Usage (run from the data_explorer repo root):
  python -m osrs.snapshot --add "Zezima"     # start tracking a friend
  python -m osrs.snapshot --list             # show who's tracked
  python -m osrs.snapshot                     # snapshot everyone now

Run it on a schedule (Windows Task Scheduler); daily is plenty. Gains are
computed later as the diff between any two snapshots, so the cadence only sets
the finest window you can ask about.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pathlib

from osrs import db, parse
from osrs.client import HiscoresClient, HiscoresError, PlayerNotFound

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent   # data_explorer/osrs/
DATA_DIR = PKG_DIR / "data"                          # gitignored: db lives here
DB_PATH = DATA_DIR / "osrs.db"


def _now_iso() -> str:
    """One UTC timestamp for the whole run (so a capture is a single instant)."""
    return (datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0).isoformat())


def capture_all(client: HiscoresClient, conn, captured_at: str) -> dict:
    """Snapshot every tracked player. One bad name never aborts the run."""
    counts = {"ok": 0, "not_found": 0, "failed": 0}
    for rsn, display in db.tracked_players(conn):
        try:
            payload = client.lookup(display)        # API takes the display name
            skills = parse.parse_hiscores(payload)
        except PlayerNotFound:
            log.warning("not on hiscores, skipping: %s", display)
            counts["not_found"] += 1
            continue
        except HiscoresError as e:
            log.error("lookup failed for %s: %s — skipping (re-run to retry)",
                      display, e)
            counts["failed"] += 1
            continue
        db.insert_snapshot(conn, rsn, captured_at, skills)
        conn.commit()
        ov = parse.overall(skills)
        log.info("snapshotted %s — total level %s, %s xp",
                 display, ov["level"], f'{ov["xp"]:,}')
        counts["ok"] += 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot OSRS clan members' hiscores")
    ap.add_argument("--add", metavar="RSN", help="start tracking this RuneScape name")
    ap.add_argument("--note", help="optional note stored with --add")
    ap.add_argument("--list", action="store_true", help="list tracked players and exit")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)

    if args.add:
        added = db.add_player(conn, args.add, _now_iso(), args.note)
        conn.commit()
        log.info("now tracking: %s" if added else "already tracking: %s", args.add)
        conn.close()
        return

    if args.list:
        players = db.tracked_players(conn)
        log.info("%d tracked player(s):", len(players))
        for _, display in players:
            log.info("  %s", display)
        conn.close()
        return

    players = db.tracked_players(conn)
    if not players:
        log.warning('no players tracked yet — add some: '
                    'python -m osrs.snapshot --add "<RSN>"')
        conn.close()
        return

    counts = capture_all(HiscoresClient(), conn, _now_iso())
    conn.close()
    log.info("done: %d ok, %d not-found, %d failed",
             counts["ok"], counts["not_found"], counts["failed"])


if __name__ == "__main__":
    main()
