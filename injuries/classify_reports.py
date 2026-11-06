"""Attach the shared classification to the official injury-report rows.

``injury_reports.py`` writes ``data/injury_reports.csv`` with the raw reason
string per player per report. This module adds the ``classify.py`` label
columns and the season label, writing ``data/injury_reports_classified.csv``,
which the investigation page builder reads.

Usage::

    python -m injuries.classify_reports
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import Counter
from pathlib import Path

from injuries.classify import classify, publishable_text
from injuries.pst_mirror import season_of

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
IN_CSV = DATA_DIR / "injury_reports.csv"
OUT_CSV = DATA_DIR / "injury_reports_classified.csv"
LABEL_COLUMNS = ("season", "category", "location", "region", "side", "nature", "below_knee")


def classify_rows(rows: list[dict]) -> list[dict]:
    """Pure: one output row per input row with the label columns appended."""
    out = []
    for r in rows:
        if not r.get("report_date"):
            raise ValueError(f"row without report_date: {r}")
        label = classify(r.get("reason", ""))
        new = dict(r)
        new["reason"] = publishable_text(r.get("reason", ""), label.category)
        new.update(
            {
                "season": season_of(r["report_date"]),
                "category": label.category,
                "location": label.location,
                "region": label.region,
                "side": label.side,
                "nature": label.nature,
                "below_knee": int(label.below_knee),
            }
        )
        out.append(new)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--in", dest="src", type=Path, default=IN_CSV)
    parser.add_argument("--out", dest="dst", type=Path, default=OUT_CSV)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.src.exists():
        raise FileNotFoundError(f"{args.src} is missing: run injuries.injury_reports first")
    with args.src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = classify_rows(list(reader))
        columns = list(reader.fieldnames) + [c for c in LABEL_COLUMNS if c not in reader.fieldnames]
    if not rows:
        raise ValueError(f"{args.src} has no rows")
    with args.dst.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    cats = Counter(r["category"] for r in rows)
    log.info("wrote %s (%d rows); categories %s", args.dst, len(rows), dict(cats.most_common()))
    unknown = cats["unknown"] / len(rows)
    if unknown > 0.02:
        log.warning("unknown category share is %.2f%%: review the reason vocabulary", 100 * unknown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
