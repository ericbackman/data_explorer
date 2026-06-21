"""Tier 2: deep major-championship history (1960-2004) from Wikipedia.

Unlike Tier 1, this isn't a self-contained scraper: WebFetch is an agent tool,
not a Python library. The agent fetches each Wikipedia major-year page, extracts
winner + 36/54-hole leaders, and writes records to a JSON file shaped like:

    [
      {"year": 2003, "major": "Masters", "winner": "Mike Weir",
       "winning_score": "281 (-7)", "leader_36": "Mike Weir",
       "leader_36_score": "138 (-6)", "leader_54": "Jeff Maggert",
       "leader_54_score": "211 (-5)", "playoff": true,
       "source_url": "https://en.wikipedia.org/wiki/2003_Masters_Tournament"},
      ...
    ]

This module validates those records, derives ``leader_54_won``, and loads them.

    python -m pga_data.tier2 load data/major_history_seed.json
"""
from __future__ import annotations

import argparse
import json
import logging
import unicodedata
from pathlib import Path

from .db import connect, init_db

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_DB = _ROOT / "data" / "pga.db"

VALID_MAJORS = {"Masters", "U.S. Open", "The Open", "PGA Championship"}

_FIELDS = (
    "year", "major", "winner", "winning_score", "leader_36", "leader_36_score",
    "leader_54", "leader_54_score", "playoff", "source_url",
)

# Shared by both Tier-2 collectors (scrapekit = primary/free, firecrawl = fallback).
# Wikipedia URL templates per major (stable across 1960-2004).
MAJOR_URL_TEMPLATES = {
    "Masters": "https://en.wikipedia.org/wiki/{year}_Masters_Tournament",
    "U.S. Open": "https://en.wikipedia.org/wiki/{year}_U.S._Open_(golf)",
    "The Open": "https://en.wikipedia.org/wiki/{year}_Open_Championship",
    "PGA Championship": "https://en.wikipedia.org/wiki/{year}_PGA_Championship",
}

# Fields each collector pulls from a page (besides year/major/source_url).
EXTRACT_FIELDS = (
    "winner", "winning_score", "leader_36", "leader_36_score",
    "leader_54", "leader_54_score", "playoff",
)

# JSON schema + prompt for the LLM extraction paths (Firecrawl; scrapekit's
# Ollama fallback). The scrapekit table parser doesn't need these.
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "description": "Full name of the champion"},
        "winning_score": {"type": "string",
                          "description": "Winning total and to-par, e.g. '281 (-7)'"},
        "leader_36": {"type": "string",
                      "description": "Full name(s) leading after 36 holes (round 2). "
                                     "Comma-separate co-leaders."},
        "leader_36_score": {"type": "string", "description": "36-hole leader's score, e.g. '138 (-6)'"},
        "leader_54": {"type": "string",
                      "description": "Full name(s) leading after 54 holes (round 3). "
                                     "Comma-separate co-leaders."},
        "leader_54_score": {"type": "string", "description": "54-hole leader's score, e.g. '211 (-5)'"},
        "playoff": {"type": "boolean",
                    "description": "True if the championship was decided by a playoff"},
    },
    "required": ["winner"],
}

EXTRACT_PROMPT = (
    "This is a Wikipedia page for a men's major golf championship. From the "
    "round-by-round leaderboard or round summaries, extract the champion and the "
    "players leading after the second round (36 holes) and third round (54 holes). "
    "If a 36- or 54-hole leader is not stated on the page, leave that field blank."
)


def _norm_name(name: str | None) -> str:
    """Lowercase, strip accents/punctuation so 'José M. Olazábal' matches itself
    regardless of how each Wikipedia table renders it."""
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return "".join(c for c in n.lower() if c.isalnum() or c.isspace()).strip()


def derive_leader_won(record: dict, leader_field: str) -> int | None:
    """Did the named leader (leader_36 or leader_54) win? None if undeterminable.

    Co-leaders are listed as "A and B" / "A, B"; the robust check is whether the
    winner is among the listed leaders.
    """
    leader = record.get(leader_field)
    winner = record.get("winner")
    if not leader or not winner:
        return None
    leaders = [_norm_name(x) for x in leader.replace(" and ", ",").split(",")]
    return int(_norm_name(winner) in [l for l in leaders if l])


def derive_leader_54_won(record: dict) -> int | None:
    return derive_leader_won(record, "leader_54")


def validate(record: dict) -> list[str]:
    problems = []
    if not isinstance(record.get("year"), int) or not (1860 <= record["year"] <= 2026):
        problems.append(f"bad year: {record.get('year')!r}")
    if record.get("major") not in VALID_MAJORS:
        problems.append(f"major must be one of {sorted(VALID_MAJORS)}, got {record.get('major')!r}")
    if not record.get("winner"):
        problems.append("missing winner")
    return problems


def load_records(conn, records: list[dict]) -> dict:
    # major_history is fully derived from the seed, so rebuild it each load --
    # this also picks up schema changes (e.g. the leader_36_won column) without
    # a migration, and leaves the Tier-1 tables untouched.
    conn.execute("DROP TABLE IF EXISTS major_history")
    init_db(conn)
    loaded = skipped = 0
    for rec in records:
        problems = validate(rec)
        if problems:
            logger.warning("skipping %s %s: %s", rec.get("year"), rec.get("major"), "; ".join(problems))
            skipped += 1
            continue
        row = {f: rec.get(f) for f in _FIELDS}
        row["playoff"] = int(bool(rec.get("playoff")))
        row["leader_36_won"] = derive_leader_won(rec, "leader_36")
        row["leader_54_won"] = derive_leader_won(rec, "leader_54")
        cols = list(row.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO major_history ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})",
            tuple(row[c] for c in cols),
        )
        loaded += 1
    conn.commit()
    return {"loaded": loaded, "skipped": skipped}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load Tier-2 major history from a JSON file.")
    parser.add_argument("cmd", choices=["load"])
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    records = json.loads(args.json_path.read_text(encoding="utf-8"))
    conn = connect(args.db)
    try:
        stats = load_records(conn, records)
    finally:
        conn.close()
    logger.info("major_history: %s", stats)


if __name__ == "__main__":
    main()
