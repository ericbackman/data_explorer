"""OSRS Hiscores API client: polite, retrying, loud on failure.

The official OSRS Hiscores expose every player's skills/levels/XP as a public,
auth-free endpoint — the same data the in-game/website Hiscores lookup shows. We
read it read-only; there is no game automation here.

  GET .../index_lite.json?player=<rsn>  ->  {"skills": [...], "activities": [...]}

Resilience (same shape as nba/client.py):
  - a minimum interval between requests (politeness; Jagex publishes no limit),
  - exponential-backoff retries on transient failures (timeouts / 429 / 5xx),
  - loud failure: after exhausting retries we RAISE, never return a silent None,
  - a 404 (name not on the Hiscores / typo'd) is a distinct, non-retried
    PlayerNotFound so a caller can skip that one friend and keep going.

Snapshots are intentionally NOT cached: the whole point is a fresh point-in-time
reading each run. (Contrast nba/client.py, which caches immutable past seasons.)
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

HISCORES_URL = "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json"

DEFAULT_MIN_INTERVAL_S = 1.0   # be a good citizen; this is someone else's server
DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 4
BACKOFF_BASE_S = 1.5
# A descriptive User-Agent is courteous (the OSRS Wiki API explicitly asks for
# one); identify the project, not a browser.
USER_AGENT = "osrs-clan-companion/0.1 (personal clan stats project)"

# Statuses worth retrying — transient server/throttle conditions only.
RETRY_STATUS = {429, 500, 502, 503, 504}


class HiscoresError(RuntimeError):
    """Raised when a lookup cannot be completed after exhausting retries."""


class PlayerNotFound(HiscoresError):
    """The RSN is not on the Hiscores (never ranked, or misspelled)."""


class HiscoresClient:
    def __init__(
        self,
        *,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        session: requests.Session | None = None,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        # Session is injectable so tests can pass a fake (no real network).
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._last_call_ts = 0.0

    def _throttle(self) -> None:
        wait = self.min_interval_s - (time.monotonic() - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def lookup(self, rsn: str) -> dict:
        """Return the raw Hiscores JSON for one player.

        Raises PlayerNotFound on 404 (no point retrying a bad name) and
        HiscoresError after max_retries on transient failures. Never returns None.
        """
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._session.get(
                    HISCORES_URL, params={"player": rsn}, timeout=self.timeout_s,
                )
            except requests.exceptions.RequestException as e:
                last_err = e
            else:
                if resp.status_code == 404:
                    raise PlayerNotFound(rsn)
                if resp.status_code in RETRY_STATUS:
                    last_err = HiscoresError(f"{rsn}: HTTP {resp.status_code}")
                else:
                    try:
                        resp.raise_for_status()
                        return resp.json()
                    except (requests.exceptions.HTTPError, ValueError) as e:
                        last_err = e  # unexpected 4xx or malformed body -> retry

            backoff = BACKOFF_BASE_S ** attempt
            log.warning(
                "lookup %s attempt %d/%d failed (%s) — retrying in %.1fs",
                rsn, attempt, self.max_retries, last_err, backoff,
            )
            time.sleep(backoff)

        raise HiscoresError(
            f"{rsn}: failed after {self.max_retries} attempts"
        ) from last_err
