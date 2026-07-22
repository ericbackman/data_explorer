"""The PRESS layer — contemporaneous local-newspaper evidence for draft narration.

sleep-sports scripts want RECEPTION claims ("the pick was booed in the Salt
Palace", "local coverage treated him as an unknown") — claims no stat row can
carry. This table is their verified home: each clip is a dated, sourced,
human-read piece of period coverage, stored as METADATA + a paraphrased
summary. Copyright rules (all 1984-2003 papers are in copyright):

  - facts and paraphrase only — NEVER article text in this table or any script;
  - private OCR/screenshots used during verification stay OUTSIDE the repo
    (they are working notes, not data);
  - every clip carries provenance (paper, date, page, url) so the claim gate
    and Eric can re-read the source.

Clips are added by a HUMAN (or an agent that actually read the page) via the
CLI — there is no blind scraper writing summaries. Acquisition routes and
per-market feasibility: sleep-sports/PRESS.md.

Usage
-----
  python -m nba.press_clips add --season 1984 --team UTA \
      --paper "Salt Lake Tribune" --date 1984-06-20 --url "https://..." \
      --players "John Stockton" \
      --summary "Draft-morning coverage described the crowd reaction ..."
  python -m nba.press_clips list --season 1984
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pathlib
import sqlite3

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent
DB_PATH = PKG_DIR / "data" / "nba.db"

DDL = """
CREATE TABLE IF NOT EXISTS press_clips (
    clip_id INTEGER PRIMARY KEY,
    draft_season INT NOT NULL,      -- the draft this clip is evidence about
    team_id INT,                    -- franchise the coverage is local to (nullable: national)
    players TEXT,                   -- comma-separated exact DB spellings, for roster vouching
    paper TEXT NOT NULL,
    pub_date TEXT NOT NULL,         -- ISO YYYY-MM-DD
    page TEXT,                      -- e.g. 'D1' when known
    url TEXT NOT NULL,              -- archive URL where the page was read
    summary TEXT NOT NULL           -- PARAPHRASE, never article text
);
"""


def connect(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.execute(DDL)
    return conn


def add_clip(conn: sqlite3.Connection, season: int, team_abbrev: str | None,
             players: str, paper: str, date: str, page: str | None,
             url: str, summary: str) -> int:
    datetime.date.fromisoformat(date)          # fail loud on a malformed date
    if not summary.strip() or not url.strip():
        raise ValueError("summary and url are required — a clip is evidence, not a stub")
    team_id = None
    if team_abbrev:
        row = conn.execute(
            "SELECT team_id FROM teams WHERE abbreviation = ? ORDER BY team_id DESC",
            (team_abbrev,)).fetchone()
        if row is None:
            raise ValueError(f"unknown team abbreviation: {team_abbrev}")
        team_id = int(row[0])
    cur = conn.execute(
        "INSERT INTO press_clips (draft_season, team_id, players, paper, pub_date, "
        "page, url, summary) VALUES (?,?,?,?,?,?,?,?)",
        (season, team_id, players, paper, date, page, url, summary))
    conn.commit()
    return int(cur.lastrowid)


def main() -> None:
    ap = argparse.ArgumentParser(description="Curate verified press clips for draft narration")
    ap.add_argument("--db", default=str(DB_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add one human-read clip")
    a.add_argument("--season", type=int, required=True)
    a.add_argument("--team", default=None, help="franchise abbreviation, e.g. UTA")
    a.add_argument("--players", default="", help="comma-separated exact DB spellings")
    a.add_argument("--paper", required=True)
    a.add_argument("--date", required=True, help="ISO publication date")
    a.add_argument("--page", default=None)
    a.add_argument("--url", required=True)
    a.add_argument("--summary", required=True, help="paraphrase only, never article text")
    ls = sub.add_parser("list", help="show clips")
    ls.add_argument("--season", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    conn = connect(args.db)
    if args.cmd == "add":
        cid = add_clip(conn, args.season, args.team, args.players, args.paper,
                       args.date, args.page, args.url, args.summary)
        log.info("clip %d added (%s, %s)", cid, args.paper, args.date)
    else:
        q = "SELECT clip_id, draft_season, paper, pub_date, players, summary FROM press_clips"
        rows = (conn.execute(q + " WHERE draft_season = ?", (args.season,))
                if args.season else conn.execute(q)).fetchall()
        for r in rows:
            log.info("#%d [%d] %s %s | %s | %s", *r)
        log.info("%d clips", len(rows))


if __name__ == "__main__":
    main()
