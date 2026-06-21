"""Tier-2 collector via scrapekit (free) — the credit-free replacement for the
Firecrawl collector, matching the data_explorer convention of preferring
pandas.read_html over paid APIs for non-hostile sites like Wikipedia.

How it works: Wikipedia major-year pages carry per-round leaderboard tables whose
Score column embeds the cumulative score ("70-68=138" after R2, "72-73-66=211"
after R3). So the 36-/54-hole leaders are *computed deterministically* from the
standings — more precise than reading prose, since the Place column distinguishes
a solo leader from co-leaders exactly. The champion comes from the infobox.

scrapekit's extract_with_fallback runs this parser first and only falls back to a
local Ollama model if the parser can't handle a page (rare). Both are $0.

    python -m pga.tier2_scrapekit collect --start 1960 --end 2004
    python -m pga.tier2 load pga/seeds/major_history_seed.json
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from scrapekit import Extractor

from .tier2 import (
    EXTRACT_FIELDS as _EXTRACT_FIELDS,
    EXTRACT_PROMPT as _PROMPT,
    EXTRACT_SCHEMA as _SCHEMA,
    MAJOR_URL_TEMPLATES,
)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_OUT = _ROOT / "seeds" / "major_history_seed.json"
DEFAULT_CACHE = _ROOT / "data" / "scrapekit_cache"


def _clean(s):
    if not isinstance(s, str):
        return s
    for ch in ("−", "–", "—"):  # minus sign, en dash, em dash
        s = s.replace(ch, "-")
    return s.replace("\xa0", " ").strip()


def _colmap(t: pd.DataFrame) -> dict:
    """Normalized column name -> actual column label (handles 'To par' variants)."""
    return {re.sub(r"\s+", "", str(c)).lower(): c for c in t.columns}


def _rounds(score) -> tuple[int, str | None]:
    """'70-68=138' -> (2,'138'); '66' -> (1,'66'); cumulative-round count + total."""
    s = str(score).strip()
    if "=" in s:
        left, total = s.split("=", 1)
        return left.count("-") + 1, total.strip()
    return (1, s) if s.replace(".", "").isdigit() else (0, None)


def _leaderboard_tables(html: str) -> list[pd.DataFrame]:
    return [t for t in pd.read_html(io.StringIO(html))
            if {"player", "score", "place"} <= set(_colmap(t))]


def _round_leaders(tables: list[pd.DataFrame], want: int) -> tuple[str | None, str | None, bool]:
    """(co-leaders joined, 'total (to-par)', playoff?) for the table whose leader
    has completed `want` rounds."""
    for t in tables:
        if t.empty:
            continue
        cm = _colmap(t)
        n, total = _rounds(t.iloc[0][cm["score"]])
        if n != want:
            continue
        topar = _clean(str(t.iloc[0][cm["topar"]])) if "topar" in cm else None
        names: list[str] = []
        playoff = False
        for _, row in t.iterrows():
            place = str(row[cm["place"]]).strip()
            if "playoff" in " ".join(str(x) for x in row.tolist()).lower():
                playoff = True
            if place in ("1", "T1"):
                names.append(_clean(str(row[cm["player"]])))
            elif names:
                break
        score = f"{total} ({topar})" if total and topar else total
        return ", ".join(names) or None, score, playoff
    return None, None, False


def _champion(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    info = soup.find("table", class_=re.compile("infobox"))
    if not info:
        return None
    for th in info.find_all("th"):
        if th.get_text(strip=True) == "Champion":
            tr = th.find_parent("tr")
            nxt = tr.find_next_sibling("tr") if tr else None
            if nxt:
                return _clean(nxt.get_text(" ", strip=True))
    return None


def parse_major_page(html: str) -> dict | None:
    """Deterministic parse of a Wikipedia major page. Returns None (-> LLM
    fallback) if the essentials (champion + 54-hole leader) aren't found."""
    tables = _leaderboard_tables(html)
    l36, l36s, _ = _round_leaders(tables, 2)
    l54, l54s, _ = _round_leaders(tables, 3)
    _, wins, playoff = _round_leaders(tables, 4)
    champ = _champion(html)
    if not champ or not l54:
        return None
    return {
        "winner": champ, "winning_score": wins,
        "leader_36": l36, "leader_36_score": l36s,
        "leader_54": l54, "leader_54_score": l54s,
        "playoff": playoff,
    }


def collect(years, majors, out_json: Path, cache_dir: Path, limit=None) -> dict:
    ex = Extractor(cache_dir)
    records, ok, fail, fellback = [], 0, 0, 0
    for year in years:
        for major, template in majors.items():
            if limit is not None and (ok + fail) >= limit:
                break
            url = template.format(year=year)
            try:
                html = ex.fetch(url)
                data = parse_major_page(html)
                if data is None:  # parser missed -> local LLM (raises if Ollama absent)
                    fellback += 1
                    logger.info("parser missed %s %s -- trying local LLM", year, major)
                    data = ex.llm_extract(html, _SCHEMA, _PROMPT)
            except Exception:
                fail += 1
                logger.exception("extract failed: %s %s (%s)", year, major, url)
                continue
            record = {"year": year, "major": major, "source_url": url}
            for f in _EXTRACT_FIELDS:
                record[f] = data.get(f)
            records.append(record)
            ok += 1
            logger.info("%s %s -> winner=%s, 54-hole leader=%s",
                        year, major, data.get("winner"), data.get("leader_54"))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"collected": ok, "failed": fail, "llm_fallbacks": fellback, "out": str(out_json)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Collect Tier-2 major history via scrapekit (free).")
    parser.add_argument("cmd", choices=["collect"])
    parser.add_argument("--start", type=int, default=1960)
    parser.add_argument("--end", type=int, default=2004)
    parser.add_argument("--majors", nargs="*", choices=list(MAJOR_URL_TEMPLATES))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    years = list(range(args.start, args.end + 1))
    majors = ({m: MAJOR_URL_TEMPLATES[m] for m in args.majors}
              if args.majors else MAJOR_URL_TEMPLATES)
    stats = collect(years, majors, args.out, args.cache, limit=args.limit)
    logger.info("done: %s", stats)


if __name__ == "__main__":
    main()
