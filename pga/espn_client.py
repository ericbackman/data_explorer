"""HTTP client for ESPN's public golf JSON API.

Two endpoints carry everything we need:
  * scoreboard?dates=YYYY0101-YYYY1231  -> the season's event list (ids + metadata)
  * leaderboard?event={id}              -> one event's full field, round-by-round

Design notes (see STANDARDS.md):
  * Every request has an explicit timeout and retries on transient 429/5xx.
  * Raw responses are cached to disk, so a re-run never re-fetches an event that
    already succeeded -- the backfill is resumable and we stay polite to ESPN.
  * Failures are loud: after exhausting retries we raise, we never return a
    plausible-but-empty payload that would silently corrupt the DB.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_SITE = "https://site.api.espn.com/apis/site/v2/sports/golf"
_SCOREBOARD = f"{_SITE}/pga/scoreboard"
_LEADERBOARD = f"{_SITE}/leaderboard"
_ATHLETE = "https://site.api.espn.com/apis/common/v3/sports/golf/pga/athletes"

# ESPN's golf data only returns events from 2005 onward (verified empirically).
EARLIEST_SEASON = 2005


class EspnClient:
    """Thin, cached, retrying wrapper around the two endpoints we use."""

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
            {"User-Agent": "pga-data/0.1 (personal research; contact via github.com/ericbackman)"}
        )
        for sub in ("schedule", "events", "athletes"):
            (self.cache_dir / sub).mkdir(parents=True, exist_ok=True)

    # -- public API ---------------------------------------------------------

    def season_events(self, year: int) -> list[dict]:
        """Return the raw event stubs for a season (id, name, date, season)."""
        cache_path = self.cache_dir / "schedule" / f"{year}.json"
        data = self._cached_get(
            cache_path,
            _SCOREBOARD,
            params={"dates": f"{year}0101-{year}1231", "limit": 1000},
        )
        events = data.get("events", [])
        logger.info("season %s: %d events", year, len(events))
        return events

    def leaderboard(self, event_id: str | int) -> dict:
        """Return one event's full leaderboard JSON (cached)."""
        cache_path = self.cache_dir / "events" / f"{event_id}.json"
        return self._cached_get(cache_path, _LEADERBOARD, params={"event": event_id})

    def athlete(self, athlete_id: str | int) -> dict:
        """Return one athlete's bio JSON (cached). Note the common/v3 base URL."""
        cache_path = self.cache_dir / "athletes" / f"{athlete_id}.json"
        return self._cached_get(cache_path, f"{_ATHLETE}/{athlete_id}", params={})

    # -- internals ----------------------------------------------------------

    def _cached_get(self, cache_path: Path, url: str, params: dict) -> dict:
        if cache_path.exists():
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
