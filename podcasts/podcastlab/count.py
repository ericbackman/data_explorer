"""Lexical analysis over transcripts — the mention-rate metric.

Eric's chosen metric: **raw mention count, averaged per episode, grouped by
publish year.** The aggregation below is fixed. The one decision that actually
moves the numbers — *what counts as a single mention* — lives in
``count_mentions()``, which is intentionally left for you to write.

Once it's implemented:
    python -m podcastlab.count lonely-island Quaid
    python -m podcastlab.count bill-simmons Boston
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict

from podcastlab import db

logger = logging.getLogger(__name__)


def count_mentions(text: str, term: str) -> int:
    """Return how many times `term` is mentioned in `text`.   <<<  YOU WRITE THIS

    This one function defines every stat this project produces, so the choices
    here matter more than anything else in the codebase:

      * Case — "Boston" vs "boston". Almost certainly case-INsensitive.
      * Word boundaries — should "Boston" match inside "Bostonian" or "Bostons"?
        The naive `text.lower().count(term.lower())` says yes, and that's the
        classic trap: it also counts "Bostonians", "reboston", etc. Use \\b.
      * Plurals / possessives — should "Quaid" catch "Quaids" and "Quaid's"?
        For a fanbase nickname, probably yes; for a proper noun, maybe not.
      * Multi-word terms — "Digital Short" as one phrase (mind the whitespace).

    Keep it ~5-10 lines and return an int. Suggested starting point: compile a
    regex with re.IGNORECASE and \\b word boundaries, then len(re.findall(...)).
    Decide the plural/possessive question deliberately — it's the interesting one.
    """
    raise NotImplementedError(
        "Eric to implement count_mentions() — see the docstring. "
        "This is the metric-defining decision, deliberately left to you."
    )


def mentions_by_year(show_slug: str, term: str) -> list[dict]:
    """Raw mentions of `term`, averaged per episode, grouped by publish year."""
    with db.connect(read_only=True) as conn:
        rows = conn.execute(
            "SELECT e.published_at AS pub, t.text AS text "
            "FROM episodes e "
            "JOIN transcripts t ON t.episode_id = e.episode_id "
            "JOIN shows s ON s.show_id = e.show_id "
            "WHERE s.slug = ? AND e.published_at IS NOT NULL",
            (show_slug,),
        ).fetchall()

    if not rows:
        raise RuntimeError(
            f"no transcribed episodes for {show_slug!r}; run feeds + transcribe first"
        )

    by_year: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        year = row["pub"][:4]
        by_year[year].append(count_mentions(row["text"], term))

    report = []
    for year in sorted(by_year):
        counts = by_year[year]
        report.append({
            "year": year,
            "episodes": len(counts),
            "total_mentions": sum(counts),
            "avg_per_episode": round(sum(counts) / len(counts), 2),
        })
    return report


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Mention rate for a term, by year.")
    ap.add_argument("slug", help="show slug (see podcastlab/shows.py)")
    ap.add_argument("term", help="the term to count, e.g. Boston or Quaid")
    args = ap.parse_args(argv)

    report = mentions_by_year(args.slug, args.term)
    print(f"\n'{args.term}' mentions on {args.slug}, by year:\n")
    print(f"{'year':6}{'eps':>5}{'total':>8}{'avg/ep':>9}")
    for r in report:
        print(f"{r['year']:6}{r['episodes']:>5}{r['total_mentions']:>8}{r['avg_per_episode']:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
