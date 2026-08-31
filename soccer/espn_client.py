"""HTTP client for ESPN's public soccer JSON API.

Soccer is just one more sport on the same host that already feeds pga/ and the
NBA work; this is the structural twin of pga/espn_client.py. Two endpoints carry
the broad ("Tier 1") layer for ANY competition, identified by an ESPN league
code (e.g. ``fifa.world``, ``uefa.euro``, ``uefa.champions``, ``eng.1``):

  * scoreboard?dates=YYYY0101-YYYY1231  -> a season/edition's match list
  * summary?event={id}                  -> one match: lineups, goals/cards/subs

Design notes (see STANDARDS.md):
  * Every request has an explicit timeout and retries on transient 429/5xx.
  * Raw responses are cached to disk under cache/{league}/..., so a re-run never
    re-fetches a match that already succeeded -- the backfill is resumable and we
    stay polite to ESPN.
  * Failures are loud: after exhausting retries we raise; we never return a
    plausible-but-empty payload that would silently corrupt the DB.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# ESPN's soccer scoreboard serves match *results* back to the first World Cup
# (1930), verified empirically. Per-match summary depth (lineups/events) only
# exists for recent decades; the scraper degrades gracefully when it's absent.
EARLIEST_WORLD_CUP = 1930


class EspnSoccerClient:
    """Thin, cached, retrying wrapper around the two endpoints we use.

    `league` is an ESPN soccer league code; it namespaces both the URL and the
    on-disk cache so multiple competitions can share one cache_dir.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 30.0,
        max_retries: int = 6,
        backoff: float = 1.8,
        polite_delay: float = 0.5,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.polite_delay = polite_delay
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "soccer-data/0.1 (personal research; contact via github.com/ericbackman)"}
        )

    # -- public API ---------------------------------------------------------

    def scoreboard(self, league: str, year: int, *, use_cache: bool = True) -> dict:
        """Return one calendar year's scoreboard JSON for a league (cached).

        A full-year window (limit 1000) captures an entire tournament edition in
        one request -- a World Cup is ~64 matches, well under the cap.
        """
        cache_path = self._cache_path(league, "scoreboard", f"{year}.json")
        return self._cached_get(
            cache_path,
            f"{_SITE}/{league}/scoreboard",
            params={"dates": f"{year}0101-{year}1231", "limit": 1000},
            use_cache=use_cache,
        )

    def summary(self, league: str, event_id: str | int, *, use_cache: bool = True) -> dict:
        """Return one match's full summary JSON (lineups, keyEvents, boxscore)."""
        cache_path = self._cache_path(league, "events", f"{event_id}.json")
        return self._cached_get(
            cache_path,
            f"{_SITE}/{league}/summary",
            params={"event": event_id},
            use_cache=use_cache,
        )

    # -- internals ----------------------------------------------------------

    def _cache_path(self, league: str, sub: str, name: str) -> Path:
        d = self.cache_dir / league / sub
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def _cached_get(self, cache_path: Path, url: str, params: dict, *, use_cache: bool) -> dict:
        if use_cache and cache_path.exists():
            with cache_path.open(encoding="utf-8") as fh:
                return json.load(fh)
        data = self._get_with_retry(url, params)
        tmp = cache_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)
        tmp.replace(cache_path)  # atomic: a half-written cache file never lingers
        time.sleep(self.polite_delay)
        return data

    def _get_with_retry(self, url: str, params: dict) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                self._sleep_retry("network error", url, attempt, exc)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = requests.HTTPError(f"status {resp.status_code}")
                self._sleep_retry(f"transient {resp.status_code}", url, attempt)
                continue
            if 400 <= resp.status_code < 500:
                # Permanent client error (404 etc.) -- retrying won't help, so
                # fail fast and let the caller decide (skip vs abort).
                resp.raise_for_status()

            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                last_exc = exc
                self._sleep_retry("bad json", url, attempt, exc)
                continue

        raise RuntimeError(
            f"giving up on {url} params={params} after {self.max_retries} attempts"
        ) from last_exc

    def _sleep_retry(self, reason: str, url: str, attempt: int, exc: Exception | None = None) -> None:
        wait = self.backoff**attempt
        logger.warning("%s on %s (attempt %d/%d)%s -- retrying in %.1fs",
                       reason, url, attempt, self.max_retries,
                       f": {exc}" if exc else "", wait)
        time.sleep(wait)
