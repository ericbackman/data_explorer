"""Build machine-readable navigation artifacts from an extracted NBA CBA text file.

Given the raw `pdftotext` output of a CBA, this produces (in ../semantic/):
  1. <stem>.toc.json         - structural index: Articles -> Sections, with the line number
                               in the .raw.txt corpus AND the printed page, so an agent can
                               jump straight to a provision.
  2. <stem>.toc.md           - human-readable table of contents.
  3. <stem>.definitions.json - every defined term from Article I, Section 1 (the master
                               glossary) with the Articles it cross-references.

Section boundaries come from the *body* headers, not the table of contents: the TOC wraps
and nests deeply for the big articles (VII especially), whereas body headers are clean and
carry a line number. The CBA cites itself by Article + Section number, so that pairing --
not the page -- is the canonical navigation key.

Paths resolve relative to this file (no hard-coded user paths), so the same tool parses the
2017 and 2023 documents on any machine.

Usage:
    python build_index.py 2023-nba-cba
    python build_index.py 2017-nba-cba
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("build_index")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = PROJECT_ROOT / "corpus" / "text"
OUT_DIR = PROJECT_ROOT / "semantic"

ROMAN = r"[IVXLC]+"

# A body article header: roman alone ("ARTICLE VII") or roman + inline title
# ("ARTICLE VIII ROOKIE SCALE"). The inline title is validated as all-caps before use.
ARTICLE_HDR = re.compile(rf"^ARTICLE ({ROMAN})(?:\s+(.*))?$")
# A section header opener: "Section 8." — the title may follow inline or on a nearby line.
SECTION_HDR = re.compile(r"^Section (\d+)\.(.*)$")
# An all-caps title line (article titles, and their wrapped continuations).
CAPS_TITLE = re.compile(r"^[A-Z0-9][A-Z0-9 ,/&'()-]{2,}$")
# Leading sub-clause markers to strip from a scrambled section header: "(a) (i) ".
SUBCLAUSE_LEAD = re.compile(r"^(?:\([0-9a-z]{1,4}\)\s*)+")
# A running header carrying the printed page: "Article VII 131" or "132 Article VII".
RUNNING_PAGE = re.compile(rf"^(?:Article {ROMAN} (\d+)|(\d+) Article {ROMAN})$")
# TOC article line: "ARTICLE VII BASKETBALL ... .. 131" -> roman + printed start page.
TOC_ARTICLE = re.compile(rf"^ARTICLE ({ROMAN}) .*?\.{{2,}}\s*(\d+)\s*$")


@dataclass
class Section:
    number: str
    title: str
    line: int   # line in the .raw.txt corpus (1-indexed, matches the Read tool)
    page: str | None  # printed page in the PDF


@dataclass
class Article:
    roman: str
    number: int
    title: str
    line: int
    page: str | None
    sections: list[Section] = field(default_factory=list)


def roman_to_int(roman: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, prev = 0, 0
    for ch in reversed(roman):
        cur = values[ch]
        total += -cur if cur < prev else cur
        prev = cur
    return total


def toc_article_pages(lines: list[str]) -> dict[str, str]:
    """Printed start page per article, read from the (reliable) TOC article lines."""
    pages: dict[str, str] = {}
    for ln in lines:
        m = TOC_ARTICLE.match(ln.strip())
        if m and m.group(1) not in pages:  # first hit is the TOC entry
            pages[m.group(1)] = m.group(2)
    return pages


def body_start_index(lines: list[str]) -> int:
    for i, ln in enumerate(lines):
        if ln.strip() == "ARTICLE I":
            return i
    raise ValueError("Could not locate body start (standalone 'ARTICLE I').")


def _clean_section_title(inline: str, lines: list[str], i: int) -> str:
    """Resolve a section's title, which may be inline ("Section 8. Trade Rules.") or,
    when pdftotext interleaves sub-clause markers, sit on a nearby line ("Scope.")."""
    candidate = SUBCLAUSE_LEAD.sub("", inline.strip())
    candidate = candidate.split(".")[0].strip()
    if len(candidate) >= 3 and candidate[:1].isupper():
        return candidate
    # Title wasn't inline: look at the next few non-empty lines for a short Title-Case label.
    for j in range(i + 1, min(i + 6, len(lines))):
        nxt = lines[j].strip()
        if not nxt:
            continue
        m = re.match(r"^([A-Z][A-Za-z ,/&'-]{2,70})\.", nxt)
        if m:
            return m.group(1).strip()
        break
    return candidate or "(untitled)"


def parse_structure(lines: list[str]) -> list[Article]:
    """Walk the body once, collecting article + section headers with line/page.

    Articles must be strictly increasing (rejecting prose cross-references), and sections
    are accepted only in monotonically increasing order within an article (rejecting
    mid-paragraph references like '... in accordance with Section 8 ...').
    """
    art_pages = toc_article_pages(lines)
    start = body_start_index(lines)

    articles: list[Article] = []
    current: Article | None = None
    printed_page: str | None = None
    expected_section = 1
    collecting_title = False
    title_parts: list[str] = []

    def finish_title() -> None:
        nonlocal collecting_title
        if current is not None and title_parts:
            current.title = " ".join(title_parts).title()
        collecting_title = False

    for i in range(start, len(lines)):
        stripped = lines[i].strip()

        rp = RUNNING_PAGE.match(stripped)
        if rp:
            printed_page = rp.group(1) or rp.group(2)
            continue

        am = ARTICLE_HDR.match(stripped)
        inline_title = am.group(2).strip() if (am and am.group(2)) else ""
        if am and (not inline_title or CAPS_TITLE.match(inline_title)):
            num = roman_to_int(am.group(1))
            if not articles or num > articles[-1].number:  # strictly increasing
                finish_title()
                current = Article(roman=am.group(1), number=num, title="",
                                  line=i + 1, page=art_pages.get(am.group(1)))
                articles.append(current)
                expected_section = 1
                collecting_title = True
                title_parts = [inline_title] if inline_title else []
                continue

        if collecting_title:
            if stripped and CAPS_TITLE.match(stripped) and not stripped.startswith("Section"):
                title_parts.append(stripped)
                continue
            finish_title()  # first non-caps line ends the title; fall through to section check

        sm = SECTION_HDR.match(stripped)
        if sm and current is not None and int(sm.group(1)) == expected_section:
            current.sections.append(
                Section(number=sm.group(1),
                        title=_clean_section_title(sm.group(2), lines, i),
                        line=i + 1, page=printed_page))
            expected_section += 1

    return articles


def parse_definitions(lines: list[str]) -> list[dict]:
    """Extract Article I, Section 1 lettered definitions and their cross-references.

    Markers are a single letter repeated 1-5x -- (a), (bb), (ccc), (dddd) -- which
    distinguishes them from mixed-letter Roman-numeral sub-clauses like (ii)/(iv). We
    require the marker to be immediately followed by an opening quote.
    """
    body = "\n".join(lines)
    m = re.search(r"(?m)^ARTICLE I$", body)
    start = m.end() if m else 0
    m2 = re.search(r"(?m)^ARTICLE II$", body[start:])
    region = body[start: start + m2.start()] if m2 else body[start:]

    marker_re = re.compile(r'\(([a-z])\1{0,4}\)\s+(?=[“"])')
    first_term_re = re.compile(r'[“"]([^”"]+)[”"]')
    xref_re = re.compile(rf"Article ({ROMAN})\b")

    marks = list(marker_re.finditer(region))
    out: list[dict] = []
    for i, mk in enumerate(marks):
        chunk_end = marks[i + 1].start() if i + 1 < len(marks) else len(region)
        chunk = re.sub(r"\s+", " ", region[mk.end(): chunk_end]).strip()
        tm = first_term_re.match(chunk)
        if not tm:
            continue
        xrefs = sorted({xm.group(1) for xm in xref_re.finditer(chunk)}, key=roman_to_int)
        out.append(
            {
                "letter": mk.group(0).strip("() "),
                "term": tm.group(1).strip(),
                "cross_refs": xrefs,
                "definition": chunk[:600],
            }
        )
    return out


def render_toc_md(articles: list[Article], stem: str) -> str:
    out = [f"# {stem} — Structural Index", "",
           f"{len(articles)} Articles. `line` = line in `corpus/text/{stem}.raw.txt`; "
           f"`p` = printed PDF page. Cite as *Article <roman>, Section <n>*.", ""]
    for a in articles:
        out.append(f"## Article {a.roman} — {a.title}  ·  p.{a.page}  ·  line {a.line}")
        for s in a.sections:
            out.append(f"- §{s.number}. {s.title}  ·  p.{s.page}  ·  line {s.line}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) != 2:
        log.error("usage: python build_index.py <text-stem, e.g. 2023-nba-cba>")
        return 2
    stem = sys.argv[1]
    src = TEXT_DIR / f"{stem}.raw.txt"
    if not src.exists():
        log.error("missing source text: %s", src)
        return 1

    lines = src.read_text(encoding="utf-8").split("\n")
    articles = parse_structure(lines)
    definitions = parse_definitions(lines)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{stem}.toc.json").write_text(
        json.dumps([asdict(a) for a in articles], indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / f"{stem}.toc.md").write_text(render_toc_md(articles, stem), encoding="utf-8")
    (OUT_DIR / f"{stem}.definitions.json").write_text(
        json.dumps(definitions, indent=2, ensure_ascii=False), encoding="utf-8")

    total_sections = sum(len(a.sections) for a in articles)
    log.info("parsed %d articles, %d sections, %d definitions from %s",
             len(articles), total_sections, len(definitions), stem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
