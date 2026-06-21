"""Tier-2 collector: extract major-championship results from Wikipedia via Firecrawl.

Why Firecrawl here: 1960-2004 Wikipedia pages format their round-by-round tables
inconsistently across decades. Rather than parse 45 years of layouts, we hand
Firecrawl's v2 /scrape a JSON schema and let its model adapt per page.

Pipeline:
    1. set FIRECRAWL_API_KEY (see _load_api_key) -- key never enters the transcript
    2. python -m pga_data.tier2_firecrawl collect --start 1960 --end 2004
       -> writes data/major_history_seed.json (per-page cached, resumable)
    3. python -m pga_data.tier2 load data/major_history_seed.json
       -> validates + loads into the major_history table

Each page is one /scrape call, disk-cached, so re-runs cost zero credits.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent  # data_explorer/pga/
DEFAULT_OUT = _ROOT / "seeds" / "major_history_seed.json"  # tracked (credits to regen)
DEFAULT_CACHE = _ROOT / "data" / "firecrawl_cache"

_API = "https://api.firecrawl.dev/v2/scrape"

# Wikipedia URL templates per major (stable across 1960-2004).
MAJOR_URL_TEMPLATES = {
    "Masters": "https://en.wikipedia.org/wiki/{year}_Masters_Tournament",
    "U.S. Open": "https://en.wikipedia.org/wiki/{year}_U.S._Open_(golf)",
    "The Open": "https://en.wikipedia.org/wiki/{year}_Open_Championship",
    "PGA Championship": "https://en.wikipedia.org/wiki/{year}_PGA_Championship",
}

# Fields Firecrawl should pull from each page.
_EXTRACT_FIELDS = (
    "winner", "winning_score", "leader_36", "leader_36_score",
    "leader_54", "leader_54_score", "playoff",
)

_SCHEMA = {
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

_PROMPT = (
    "This is a Wikipedia page for a men's major golf championship. From the "
    "round-by-round leaderboard or round summaries, extract the champion and the "
    "players leading after the second round (36 holes) and third round (54 holes). "
    "If a 36- or 54-hole leader is not stated on the page, leave that field blank."
)


def _load_api_key() -> str:
    """Read FIRECRAWL_API_KEY, preferring a gitignored .env so the key stays out
    of the chat transcript. Fails loudly if absent (no silent no-op run)."""
    # Look for the key in the process env first, then a gitignored .env at the
    # project root, then one in the home dir (a common global-secrets location).
    # utf-8-sig tolerates a BOM that PowerShell redirects can prepend.
    for env_file in (_ROOT / ".env", Path.home() / ".env"):
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        raise RuntimeError(
            "FIRECRAWL_API_KEY not set. Create pga-data/.env containing "
            "FIRECRAWL_API_KEY=fc-... (it is gitignored), or set it in the environment."
        )
    return key


def _slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", url.split("/wiki/", 1)[-1]).strip("_")


# Wikipedia writes scores with the typographic minus/dashes; normalize to ASCII
# so Tier-2 scores match Tier-1 and don't choke a Windows console. Player names
# keep their real Unicode (e.g. Bjorn -> Bjorn with the o-slash).
_SCORE_FIELDS = ("winning_score", "leader_36_score", "leader_54_score")


def _clean_score(value):
    if not isinstance(value, str):
        return value
    return (value.replace("−", "-").replace("–", "-")
                 .replace("—", "-").replace(" ", " ").strip())


class FirecrawlExtractor:
    def __init__(self, api_key: str, cache_dir: Path, *, timeout: float = 120.0,
                 max_retries: int = 4, backoff: float = 2.0, polite_delay: float = 0.5) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.polite_delay = polite_delay
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_key}",
                                      "Content-Type": "application/json"})

    def extract(self, url: str) -> dict:
        """Return the extracted JSON object for one page (cached on disk)."""
        cache_path = self.cache_dir / f"{_slug(url)}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        body = {
            "url": url,
            "onlyMainContent": True,
            "formats": [{"type": "json", "schema": _SCHEMA, "prompt": _PROMPT}],
        }
        payload = self._post_with_retry(body)
        data = payload.get("data") or {}
        extracted = data.get("json") or data.get("extract") or {}
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(extracted), encoding="utf-8")
        tmp.replace(cache_path)
        time.sleep(self.polite_delay)
        return extracted

    def _post_with_retry(self, body: dict) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.post(_API, json=body, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                self._sleep(attempt, f"network error: {exc}")
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = requests.HTTPError(f"status {resp.status_code}: {resp.text[:200]}")
                self._sleep(attempt, f"transient {resp.status_code}")
                continue
            if resp.status_code >= 400:
                # 402 = out of credits, 401 = bad key -- surface immediately.
                raise RuntimeError(f"Firecrawl {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise RuntimeError(f"giving up on Firecrawl after {self.max_retries} attempts") from last_exc

    def _sleep(self, attempt: int, reason: str) -> None:
        wait = self.backoff**attempt
        logger.warning("%s (attempt %d/%d) -- retrying in %.1fs", reason, attempt, self.max_retries, wait)
        time.sleep(wait)


def collect(years: list[int], majors: dict[str, str], out_json: Path,
            cache_dir: Path, limit: int | None = None) -> dict:
    extractor = FirecrawlExtractor(_load_api_key(), cache_dir)
    records: list[dict] = []
    ok = fail = blank = 0
    for year in years:
        for major, template in majors.items():
            if limit is not None and (ok + fail) >= limit:
                break
            url = template.format(year=year)
            try:
                extracted = extractor.extract(url)
            except Exception:
                fail += 1
                logger.exception("extract failed: %s %s (%s)", year, major, url)
                continue
            if not extracted.get("winner"):
                blank += 1
                logger.warning("no winner extracted: %s %s (%s)", year, major, url)
            record = {"year": year, "major": major, "source_url": url}
            for f in _EXTRACT_FIELDS:
                v = extracted.get(f)
                record[f] = _clean_score(v) if f in _SCORE_FIELDS else v
            records.append(record)
            ok += 1
            logger.info("%s %s -> winner=%s, 54-hole leader=%s",
                        year, major, extracted.get("winner"), extracted.get("leader_54"))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"collected": ok, "failed": fail, "blank_winner": blank, "out": str(out_json)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Collect Tier-2 major history via Firecrawl.")
    parser.add_argument("cmd", choices=["collect"])
    parser.add_argument("--start", type=int, default=1960)
    parser.add_argument("--end", type=int, default=2004)
    parser.add_argument("--majors", nargs="*", choices=list(MAJOR_URL_TEMPLATES),
                        help="restrict to specific majors (default: all four)")
    parser.add_argument("--limit", type=int, default=None, help="cap pages (for a credit-safe test run)")
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
