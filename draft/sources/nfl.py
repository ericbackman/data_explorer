"""NFL draft — nflverse `draft_picks` release CSV (1980+).

Pulled straight from the nflverse-data GitHub release (one CSV, all years) rather
than through nflreadpy: it's a few thousand rows, needs no polars/pyarrow, and
mirrors how nfl/historical.py already fetches a CSV. nflverse's draft floor is
1980 (pre-1980 lives only on anti-bot-walled Pro Football Reference). `gsis_id` is
the same id used in nfl.db's player_game, so modern picks join to a career (older
players predate gsis ids and get NULL — expected, not an error).
"""
from __future__ import annotations

import csv
import io
import logging
import urllib.request

log = logging.getLogger(__name__)

SOURCE = "nflverse"
SPORT = "NFL"
URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
       "draft_picks/draft_picks.csv")
# Columns we rely on; if the release drops one, fail loud rather than emit blanks.
REQUIRED = {"season", "round", "pick", "team"}


def _int(v) -> int | None:
    try:
        return int(float(v))  # some numeric cells arrive as "12.0"
    except (TypeError, ValueError):
        return None


def _clean(v) -> str | None:
    s = (v or "").strip() if isinstance(v, str) else (str(v).strip() if v is not None else "")
    return s or None


def fetch(years=None, url: str = URL) -> list[dict]:
    """Normalized NFL draft rows. `years` = optional iterable of ints to keep."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    missing = REQUIRED - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"nflverse draft_picks CSV missing columns {missing}; "
                         f"got {reader.fieldnames}")

    want = set(years) if years else None
    rows = []
    for r in reader:
        year = _int(r.get("season"))
        if year is None or (want is not None and year not in want):
            continue
        rows.append({
            "sport": SPORT,
            "draft_year": year,
            "draft_type": "regular",  # nflverse draft_picks is the regular draft
            "round": _int(r.get("round")),
            "pick_in_round": None,    # nflverse gives overall pick only
            "overall_pick": _int(r.get("pick")) or 0,
            "team_abbr": _clean(r.get("team")),
            "team_name": None,        # CSV carries the code, not a full name
            "native_team_id": None,
            "player_name": _clean(r.get("pfr_player_name")),
            "native_player_id": _clean(r.get("gsis_id")),
            "position": _clean(r.get("position")),
            "origin": _clean(r.get("college")),
            "origin_type": None,
            "source": SOURCE,
        })
    log.info("NFL: %d picks%s", len(rows), f" ({min(years)}-{max(years)})" if years else "")
    return rows
