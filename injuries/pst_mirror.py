"""Injured-list events from open mirrors of Pro Sports Transactions.

Pro Sports Transactions (PST) is the standard archive of NBA injured-list
moves and missed games back to the 1950s, but its site sits behind a bot
challenge and its reuse terms could not be read (see
``research/injury-datasets.md``). This module never touches the site. It reads
files other people published:

- ``elap733/NBA-Injuries-Analysis`` on GitHub, two CSVs covering 2010-08 to
  2019-12 (``missedgames`` and ``IRL`` = injured reserve list events).
- Kaggle ``loganlauton/nba-injury-stats-1951-2023`` (CC0 as labelled by the
  uploader), one CSV, which Eric downloads by hand into ``injuries/raw/``
  because Kaggle needs a login.

All share the PST columns ``Date, Team, Acquired, Relinquished, Notes``.
A ``Relinquished`` row is a player going out; ``Acquired`` is a return. Both are
kept, classified with ``classify.py``, and the per-season counts written
beside them. Nothing here is a games-missed count: PST events are dated moves,
and the box-score file is the games-missed measure.

Usage::

    python -m injuries.pst_mirror            # reads injuries/raw/*.csv
    python -m injuries.pst_mirror --fetch    # also downloads the GitHub CSVs
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from collections import Counter
from pathlib import Path

import requests

from injuries.classify import classify, publishable_text

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "raw"
DATA_DIR = HERE / "data"
EVENTS_CSV = DATA_DIR / "pst_events.csv"
SEASON_CSV = DATA_DIR / "pst_events_by_season.csv"

GITHUB_FILES = {
    "elap733_missedgames_2010_2019.csv": "https://raw.githubusercontent.com/elap733/NBA-Injuries-Analysis/master/data/01_raw/prosportstransactions_scrape_missedgames_2010_2019.csv",
    "elap733_irl_2010_2019.csv": "https://raw.githubusercontent.com/elap733/NBA-Injuries-Analysis/master/data/01_raw/prosportstransactions_scrape_IRL_2010_2019.csv",
}
TIMEOUT_S = 60
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}

STAFF_WORDS = re.compile(r"(?<![a-z])(coach|head coach|assistant|general manager|gm|executive|president|owner|trainer|scout|announcer)(?![a-z])", re.IGNORECASE)

EVENT_COLUMNS = (
    "source",
    "event_type",
    "date",
    "season",
    "team",
    "player",
    "notes",
    "category",
    "location",
    "region",
    "side",
    "nature",
    "below_knee",
)


def fetch(url: str, dest: Path) -> None:
    """GET with timeout and retry on transient status; fails loud otherwise."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT_S, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code in RETRY_STATUSES:
                raise requests.HTTPError(f"{resp.status_code} on attempt {attempt}")
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            log.info("fetched %s (%d bytes)", dest.name, len(resp.content))
            return
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as err:
            last_err = err
            log.warning("fetch %s failed (%s); retrying", url, err)
            time.sleep(2 * attempt)
    raise RuntimeError(f"fetch failed after {MAX_RETRIES} attempts: {url}") from last_err


def season_of(date_iso: str) -> str:
    """NBA season label for a date: 2024-10-22 -> '2024-25'. August and later start a season."""
    year, month = int(date_iso[:4]), int(date_iso[5:7])
    start = year if month >= 8 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def normalise_name(raw: str) -> str:
    """PST writes 'Kobe Bryant / Kobe Bean Bryant' or '(Jr.) Smith'; keep the first form, trimmed."""
    name = raw.strip()
    if "/" in name:
        name = name.split("/")[0].strip()
    return name.lstrip("• ").strip()


def parse_rows(reader, source: str) -> list[dict]:
    """Turn PST-shaped rows into events. Pure; raises on a missing column."""
    required = {"Date", "Team", "Acquired", "Relinquished", "Notes"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"{source}: missing columns {sorted(missing)}")
    out = []
    for row in reader:
        date = (row["Date"] or "").strip()[:10]
        if not date:
            continue
        for column, event_type in (("Relinquished", "out"), ("Acquired", "return")):
            name = (row[column] or "").strip()
            if not name:
                continue
            notes = (row["Notes"] or "").strip()
            if STAFF_WORDS.search(notes) or STAFF_WORDS.search(name):
                continue  # coaches, executives and staff are not the subject
            label = classify(notes)
            out.append(
                {
                    "source": source,
                    "event_type": event_type,
                    "date": date,
                    "season": season_of(date),
                    "team": (row["Team"] or "").strip(),
                    "player": normalise_name(name),
                    "notes": publishable_text(notes, label.category),
                    "category": label.category,
                    "location": label.location,
                    "region": label.region,
                    "side": label.side,
                    "nature": label.nature,
                    "below_knee": int(label.below_knee),
                }
            )
    return out


def load_raw(raw_dir: Path) -> list[dict]:
    files = sorted(raw_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no PST mirror CSVs in {raw_dir}; run with --fetch or drop the Kaggle file there")
    events: list[dict] = []
    for path in files:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            rows = parse_rows(csv.DictReader(fh), source=path.stem)
        log.info("%s: %d events", path.name, len(rows))
        events.extend(rows)
    return events


def dedupe(events: list[dict]) -> list[dict]:
    """The GitHub pair and the Kaggle file overlap; keep one row per (date, player, event_type, notes)."""
    seen = set()
    out = []
    for ev in sorted(events, key=lambda e: (e["date"], e["player"], e["event_type"], e["source"])):
        key = (ev["date"], ev["player"].lower(), ev["event_type"], ev["notes"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def season_summary(events: list[dict]) -> list[dict]:
    by_season: dict[str, Counter] = {}
    for ev in events:
        if ev["event_type"] != "out":
            continue
        c = by_season.setdefault(ev["season"], Counter())
        c["out_events"] += 1
        c[ev["category"]] += 1
        if ev["category"] == "injury":
            c[f"loc_{ev['location']}"] += 1
            if ev["below_knee"]:
                c["below_knee"] += 1
    locations = sorted({k for c in by_season.values() for k in c if k.startswith("loc_")})
    out = []
    for season in sorted(by_season):
        c = by_season[season]
        row = {"season": season, "out_events": c["out_events"], "injury": c["injury"], "illness": c["illness"], "rest": c["rest"], "personal": c["personal"], "other": c["out_events"] - c["injury"] - c["illness"] - c["rest"] - c["personal"], "below_knee": c["below_knee"]}
        for loc in locations:
            row[loc] = c[loc]
        out.append(row)
    return out


def write_csv(path: Path, rows: list[dict], columns) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)
    log.info("wrote %s (%d rows)", path, len(rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch", action="store_true", help="download the GitHub mirror CSVs into injuries/raw/")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.fetch:
        for name, url in GITHUB_FILES.items():
            fetch(url, args.raw_dir / name)
    events = dedupe(load_raw(args.raw_dir))
    summary = season_summary(events)
    write_csv(EVENTS_CSV, events, EVENT_COLUMNS)
    write_csv(SEASON_CSV, summary, summary[0].keys())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
