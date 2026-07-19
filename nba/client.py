"""nba_api wrapper: rate-limited, retrying, disk-cached.

stats.nba.com is free but throttles aggressive clients and occasionally times
out. This wraps nba_api endpoint calls with:
  - a minimum interval between requests (politeness),
  - exponential-backoff retries on transient failures (timeouts / throttling),
  - a JSON disk cache so re-runs and crashes never re-hit the network,
  - loud failure: after exhausting retries we RAISE, never return a silent None.

This is the NBA analogue of pga-data's espn_client.py. The whole point of going
through nba_api is that it sets the browser-like headers stats.nba.com requires;
we only add resilience on top.
"""

from __future__ import annotations

import json
import logging
import pathlib
import time

import pandas as pd
import requests
from nba_api.stats.endpoints import (
    drafthistory, leaguegamelog, playbyplayv3, playerawards,
)

log = logging.getLogger(__name__)

# Politeness / resilience knobs. stats.nba.com publishes no rate limit; these are
# conservative values that have proven stable for bulk pulls.
DEFAULT_MIN_INTERVAL_S = 0.7   # min wall-clock seconds between network calls
DEFAULT_TIMEOUT_S = 60         # per-request socket timeout
DEFAULT_MAX_RETRIES = 5        # attempts before giving up and raising
BACKOFF_BASE_S = 1.5           # exponential backoff: BACKOFF_BASE_S ** attempt


class NBAClientError(RuntimeError):
    """Raised when an endpoint cannot be fetched after exhausting retries."""


class NBAClient:
    def __init__(
        self,
        cache_dir: pathlib.Path,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.cache_dir = pathlib.Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._last_call_ts = 0.0

    # ── cache ────────────────────────────────────────────────────────────────
    def _cache_path(self, key: str) -> pathlib.Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> pd.DataFrame | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return pd.DataFrame(json.load(f))

    def _write_cache(self, key: str, df: pd.DataFrame) -> None:
        with open(self._cache_path(key), "w", encoding="utf-8") as f:
            json.dump(df.to_dict(orient="records"), f)

    # ── throttle ─────────────────────────────────────────────────────────────
    def _throttle(self) -> None:
        wait = self.min_interval_s - (time.monotonic() - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    # ── core call with retry ─────────────────────────────────────────────────
    def _fetch_df(self, build_endpoint, desc: str) -> pd.DataFrame:
        """Call an nba_api endpoint builder, return its first dataframe.

        `build_endpoint` is a zero-arg callable that *constructs* the endpoint
        (deferred so each retry rebuilds it). Raises NBAClientError after
        max_retries — we never swallow the failure and carry on.
        """
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                return build_endpoint().get_data_frames()[0]
            except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                last_err = e
                backoff = BACKOFF_BASE_S ** attempt
                log.warning(
                    "fetch failed (%s) attempt %d/%d: %s — retrying in %.1fs",
                    desc, attempt, self.max_retries, e, backoff,
                )
                time.sleep(backoff)
        raise NBAClientError(
            f"{desc}: failed after {self.max_retries} attempts"
        ) from last_err

    # ── public endpoints ─────────────────────────────────────────────────────
    def league_game_log(
        self,
        season: str,
        season_type: str,
        player_or_team: str,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """One full season of game logs in a single request.

        player_or_team: 'P' (one row per player per game) or 'T' (per team).
        Pass use_cache=False to force a network refresh (e.g. the live season).
        """
        key = f"gamelog_{season}_{season_type}_{player_or_team}".replace(" ", "-")
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                log.debug("cache hit: %s", key)
                return cached

        log.info("fetching %s", key)
        df = self._fetch_df(
            lambda: leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star=season_type,
                player_or_team_abbreviation=player_or_team,
                timeout=self.timeout_s,
            ),
            desc=key,
        )
        self._write_cache(key, df)
        return df

    def draft_history(self, season: str | None = None, use_cache: bool = True) -> pd.DataFrame:
        """Every draft pick in one request (all years), or one draft year.

        DraftHistory returns the entire draft history — every year, round and
        pick — in a single call, so the default (season=None) is one cheap,
        cached request rather than a per-year loop. Pass a four-digit start year
        (e.g. '2003') to fetch just that draft.
        """
        key = f"draft_{season or 'all'}"
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                log.debug("cache hit: %s", key)
                return cached

        log.info("fetching %s", key)
        df = self._fetch_df(
            lambda: drafthistory.DraftHistory(
                season_year_nullable=season or "", timeout=self.timeout_s),
            desc=key,
        )
        self._write_cache(key, df)
        return df

    def player_awards(self, person_id: int) -> pd.DataFrame:
        """Every award a player has won — All-Star, All-NBA, All-Defensive, MVP,
        Finals MVP, Champion, ROY, etc. — in one request. Not disk-cached: the
        player_awards table is the durable store and resumability comes from
        skipping already-fetched person_ids (an empty frame = a player with none).
        """
        return self._fetch_df(
            lambda: playerawards.PlayerAwards(
                player_id=int(person_id), timeout=self.timeout_s),
            desc=f"awards_{person_id}",
        )

    def play_by_play(self, game_id: str) -> pd.DataFrame:
        """All events for one game (PlayByPlayV3 — V2 was deprecated and now
        returns empty JSON, see nba_api #591). One request per game; no bulk
        endpoint. Not disk-cached: the play_by_play table is the durable store and
        resumability comes from skipping already-loaded game_ids.
        """
        return self._fetch_df(
            lambda: playbyplayv3.PlayByPlayV3(
                game_id=str(game_id).zfill(10), timeout=self.timeout_s),
            desc=f"pbp_{game_id}",
        )
