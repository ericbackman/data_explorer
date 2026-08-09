"""Credit-free web extraction: parser-first, local-LLM fallback.

Mirrors the cached-client pattern used by nba/client.py and pga-data's
FirecrawlExtractor — a class holding a cache dir + politeness/retry knobs — but
costs nothing: structured tables go through pandas.read_html, and only pages that
defeat the parser fall back to a local Ollama model (still $0, just a one-time
install). Every fetch is disk-cached so re-runs never re-hit the site.
"""

from __future__ import annotations

import io
import json
import logging
import os
import pathlib
import re
import time
from typing import Any, Callable

import pandas as pd
import requests

log = logging.getLogger(__name__)

DEFAULT_MIN_INTERVAL_S = 0.5
DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 4
BACKOFF_BASE_S = 2.0
# Identify honestly by DEFAULT. A UA that names the project is the correct
# behaviour: it lets a site operator see who is calling and block or contact us.
USER_AGENT = "scrapekit/1.0 (+https://github.com/ericbackman/data_explorer)"

# Some sites (e.g. prosportstransactions.com) 403 anything that isn't a browser.
# Presenting as one is available, but it is OPT-IN via SCRAPEKIT_USER_AGENT
# rather than the default, because disguising a bot is a decision the operator
# of THIS tool should make deliberately for a specific site — not something the
# library does silently on every request. Check the target's robots.txt and
# terms before setting it; some sites (Sports Reference, most sportsbooks)
# prohibit automated access outright, and a spoofed UA does not change that.
BROWSER_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_INSTALL_HINT = (
    "Local LLM fallback needs Ollama (free, runs offline). Install from "
    "https://ollama.com, then run:  ollama pull " + DEFAULT_OLLAMA_MODEL +
    "  — it serves on " + DEFAULT_OLLAMA_HOST + " automatically."
)


class ParseError(Exception):
    """Raised by a caller's parser when a page doesn't match the expected shape,
    signalling extract_with_fallback() to try the local LLM instead."""


class Extractor:
    def __init__(
        self,
        cache_dir: pathlib.Path,
        *,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        ollama_host: str = DEFAULT_OLLAMA_HOST,
        ollama_model: str = DEFAULT_OLLAMA_MODEL,
        user_agent: str | None = None,
    ) -> None:
        self.cache_dir = pathlib.Path(cache_dir)
        (self.cache_dir / "html").mkdir(parents=True, exist_ok=True)
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.ollama_host = ollama_host.rstrip("/")
        self.ollama_model = ollama_model
        # Honest UA unless the caller deliberately overrides (arg wins over env).
        # See BROWSER_USER_AGENT for when overriding is and isn't appropriate.
        self.user_agent = user_agent or os.getenv("SCRAPEKIT_USER_AGENT") or USER_AGENT
        self._last_call_ts = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    # ── fetch (cached, polite, retrying) ──────────────────────────────────────
    @staticmethod
    def _slug(url: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", url)[:180].strip("_")

    def _throttle(self) -> None:
        wait = self.min_interval_s - (time.monotonic() - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def fetch(self, url: str, use_cache: bool = True) -> str:
        """Return page HTML, cached on disk. Raises after max_retries (fail loud)."""
        path = self.cache_dir / "html" / f"{self._slug(url)}.html"
        if use_cache and path.exists():
            log.debug("cache hit: %s", url)
            return path.read_text(encoding="utf-8")

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._session.get(url, timeout=self.timeout_s)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"status {resp.status_code}")
                resp.raise_for_status()
                path.write_text(resp.text, encoding="utf-8")
                return resp.text
            except requests.RequestException as e:
                last_err = e
                backoff = BACKOFF_BASE_S ** attempt
                log.warning("fetch failed (%s) attempt %d/%d: %s — retrying in %.1fs",
                            url, attempt, self.max_retries, e, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"fetch failed after {self.max_retries} attempts: {url}") from last_err

    # ── strategy 1: pandas tables ($0, no model) ──────────────────────────────
    def read_tables(self, url: str, use_cache: bool = True, **read_html_kwargs) -> list[pd.DataFrame]:
        """Every HTML <table> on the page as a list of DataFrames."""
        html = self.fetch(url, use_cache=use_cache)
        # pandas 2.x: a literal HTML string must be wrapped, else the parser
        # tries to open it as a file path.
        return pd.read_html(io.StringIO(html), **read_html_kwargs)

    # ── strategy 2: local LLM ($0 after Ollama install) ───────────────────────
    def ollama_available(self) -> bool:
        try:
            r = self._session.get(f"{self.ollama_host}/api/tags", timeout=3)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def llm_extract(self, text: str, schema: dict, prompt: str) -> dict:
        """Extract structured JSON from text with the local model, forced to the
        given JSON schema. Raises with install instructions if Ollama is absent —
        never silently returns empty (that would poison the DB)."""
        if not self.ollama_available():
            raise RuntimeError(OLLAMA_INSTALL_HINT)
        body = {
            "model": self.ollama_model,
            "messages": [{"role": "user", "content": f"{prompt}\n\n---\n{text}"}],
            "stream": False,
            "format": schema,          # Ollama structured outputs: force the schema
            "options": {"temperature": 0},
        }
        r = self._session.post(f"{self.ollama_host}/api/chat",
                               json=body, timeout=self.timeout_s * 4)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        return json.loads(content)

    # ── the "both" orchestrator: parser first, LLM only on failure ────────────
    def extract_with_fallback(
        self,
        url: str,
        parse_fn: Callable[[str], Any],
        *,
        schema: dict,
        prompt: str,
        use_cache: bool = True,
    ) -> Any:
        """Run parse_fn(html); fall back to the local LLM only if it raises
        ParseError or returns a falsy result. Both share the disk cache."""
        html = self.fetch(url, use_cache=use_cache)
        try:
            result = parse_fn(html)
            if result:
                return result
            log.info("parser returned empty for %s — falling back to local LLM", url)
        except ParseError as e:
            log.info("parser failed for %s (%s) — falling back to local LLM", url, e)
        return self.llm_extract(html, schema, prompt)
