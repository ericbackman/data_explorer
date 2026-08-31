"""Tiny resilient HTTP GET for the JSON draft feeds (NHL, MLB).

stdlib only (urllib) so the adapters carry no extra dependency. Every call has a
timeout and retries transient failures (429 / 5xx / network) with exponential
backoff, then raises loudly — it never returns a silent None.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (data_explorer draft loader)"}
_TRANSIENT = {429, 500, 502, 503, 504}


def get_json(url: str, *, timeout: int = 30, retries: int = 4, backoff: float = 1.5) -> dict:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in _TRANSIENT and attempt < retries:
                wait = backoff ** attempt
                log.warning("GET %s -> HTTP %s; retry %d/%d in %.1fs",
                            url, e.code, attempt, retries, wait)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            if attempt < retries:
                wait = backoff ** attempt
                log.warning("GET %s failed (%s); retry %d/%d in %.1fs",
                            url, e, attempt, retries, wait)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last
