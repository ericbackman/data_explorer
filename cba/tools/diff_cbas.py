"""Structural diff between two indexed CBAs — what changed article-by-article.

Compares the toc.json (section structure) and definitions.json (glossary) of two CBAs and
prints the high-signal changes: added/removed sections, renamed section titles, and
added/removed defined terms. This grounds the "what changed" analysis in the primary text
instead of relying on memory. Titles are normalized before comparison so trivial
whitespace/case differences don't register as changes.

Usage:
    python tools/diff_cbas.py 2017-nba-cba 2023-nba-cba
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "semantic"


def load(stem: str) -> tuple[list[dict], list[dict]]:
    toc = json.loads((OUT_DIR / f"{stem}.toc.json").read_text(encoding="utf-8"))
    defs = json.loads((OUT_DIR / f"{stem}.definitions.json").read_text(encoding="utf-8"))
    return toc, defs


def norm(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def diff_sections(a_toc: list[dict], b_toc: list[dict]) -> None:
    a_by_roman = {art["roman"]: art for art in a_toc}
    b_by_roman = {art["roman"]: art for art in b_toc}

    print("## Article-by-article section changes\n")
    for roman in sorted(b_by_roman, key=lambda r: b_by_roman[r]["number"]):
        a_art, b_art = a_by_roman.get(roman), b_by_roman[roman]
        if a_art is None:
            print(f"### Article {roman} — {b_art['title']}  [NEW ARTICLE]\n")
            continue

        a_secs = {s["number"]: s["title"] for s in a_art["sections"]}
        b_secs = {s["number"]: s["title"] for s in b_art["sections"]}
        lines: list[str] = []

        # Article title change
        if norm(a_art["title"]) != norm(b_art["title"]):
            lines.append(f"  - TITLE: '{a_art['title']}' -> '{b_art['title']}'")
        # Section count delta
        if len(a_secs) != len(b_secs):
            lines.append(f"  - sections: {len(a_secs)} -> {len(b_secs)}")
        # Added / removed sections
        for num in sorted(set(b_secs) - set(a_secs), key=int):
            lines.append(f"  - + §{num}. {b_secs[num]}  [added]")
        for num in sorted(set(a_secs) - set(b_secs), key=int):
            lines.append(f"  - − §{num}. {a_secs[num]}  [removed]")
        # Renamed sections (same number, different title)
        for num in sorted(set(a_secs) & set(b_secs), key=int):
            if norm(a_secs[num]) != norm(b_secs[num]):
                lines.append(f"  - §{num}: '{a_secs[num]}' -> '{b_secs[num]}'")

        if lines:
            print(f"### Article {roman} — {b_art['title']}")
            print("\n".join(lines) + "\n")


def diff_definitions(a_defs: list[dict], b_defs: list[dict]) -> None:
    a_terms = {d["term"] for d in a_defs}
    b_terms = {d["term"] for d in b_defs}
    print("## Glossary (Article I) term changes\n")
    added = sorted(b_terms - a_terms)
    removed = sorted(a_terms - b_terms)
    print("**Added terms:** " + (", ".join(added) if added else "none"))
    print("\n**Removed terms:** " + (", ".join(removed) if removed else "none") + "\n")


def main() -> int:
    # The corpus uses typographic dashes/quotes; force UTF-8 so Windows' cp1252 console
    # doesn't choke when printing them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 3:
        print("usage: python diff_cbas.py <old-stem> <new-stem>")
        return 2
    old, new = sys.argv[1], sys.argv[2]
    a_toc, a_defs = load(old)
    b_toc, b_defs = load(new)
    print(f"# Structural diff: {old} -> {new}\n")
    diff_sections(a_toc, b_toc)
    diff_definitions(a_defs, b_defs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
