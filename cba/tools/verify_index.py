"""Sanity checks for the generated CBA index — run after build_index.py.

Confirms all 42 Articles are present, prints any gaps, and dumps a target article's
section map so we can eyeball correctness. Usage: python verify_index.py 2023-nba-cba [VII]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "semantic"
EXPECTED = 42  # ARTICLE I .. ARTICLE XLII


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "2023-nba-cba"
    focus = sys.argv[2] if len(sys.argv) > 2 else "VII"
    arts = json.loads((OUT_DIR / f"{stem}.toc.json").read_text(encoding="utf-8"))

    nums = sorted(a["number"] for a in arts)
    missing = [n for n in range(1, EXPECTED + 1) if n not in nums]
    print(f"{stem}: {len(arts)} articles parsed; missing article numbers: {missing or 'none'}")

    # Articles with zero sections are suspicious (every real article has >=1).
    empty = [f"{a['roman']}({a['title'][:30]})" for a in arts if not a["sections"]]
    print(f"articles with 0 sections: {empty or 'none'}")

    a = next((x for x in arts if x["roman"] == focus), None)
    if a:
        print(f"\nArticle {focus} — {a['title']}  p.{a['page']}  line {a['line']}")
        for s in a["sections"]:
            print(f"  S{s['number']}. {s['title']}  p.{s['page']} L{s['line']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
