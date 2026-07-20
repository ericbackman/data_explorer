"""
Chadwick / Lahman career-data + id-bridge downloader
=====================================================
Fetches the three source datasets Phase A needs for career value + the
draft<->career id bridge, caching each raw file once under
``mlb/data/raw/``. All three are read-only, free, no-key downloads.

SOURCE STATUS (verified live, 2026-07-20 — do not assume the task prompt's
GitHub URL still resolves without checking):

  * ``chadwickbureau/baseballdatabank`` (the classic Lahman-successor repo
    the task named) is **GONE from GitHub** — a direct HTTP check returns
    404, and the Wayback Machine CDX index shows it was already 404 by
    2024-02-09 (last confirmed live snapshot: 2023-05-29). It has been
    missing for roughly two years, not a transient outage.

  * The current steward is **SABR** (Society for American Baseball
    Research), https://sabr.org/lahman-database/ — "Version 2025" (through
    the 2025 season), released 2026-01-02, hosted as CSV/Access/SQL zips on
    Box (``sabr.box.com``). Box's shared-link pages don't serve a plain
    file over a simple GET (they return an HTML/JS shell), but the
    embedded page state exposes each file's numeric Box file id, and Box's
    legacy ``index.php?rm=box_download_shared_file`` endpoint serves the
    raw bytes for that id with no auth needed — verified against every
    file this module downloads (byte count matches Box's own
    ``itemSize`` metadata).

  * **Gap found in the SABR Box folder**: the bundled ``readme2025.txt``
    documents ~27 CSVs (incl. AllStarFull, Appearances, the four Awards*
    tables, FieldingOF*), but the *live* folder — checked twice, once via a
    raw HTML fetch and once via the Box web app's own network calls in a
    real browser — currently serves only 20 files. Missing: AllStarFull.csv,
    Appearances.csv, AwardsManagers.csv, **AwardsPlayers.csv**,
    AwardsShareManagers.csv, AwardsSharePlayers.csv, FieldingOF.csv,
    FieldingOFsplit.csv. This looks like an incomplete upload on SABR's
    side, not a deliberate change — People/Batting/Pitching/HallOfFame
    (everything Phase A actually needs from core/) are all present and
    fresh (through 2025).

  * **Fallback for AwardsPlayers.csv**: SABR doesn't have it right now, so
    this module pulls it from ``cbwinslow/baseballdatabank`` (a GitHub
    mirror of the pre-2023 chadwickbureau layout), last pushed
    2022-10-31 -> awards data only through the **2021** season. This is
    STALE by design and documented here + in the loader's log output; swap
    back to SABR's own file the moment they fix their folder.

  * The **Chadwick register** (``chadwickbureau/register``) is still alive
    and actively maintained (pushed as recently as 2026-07-01). It bridges
    ``key_mlbam`` (what the draft API gives us) to ``key_bbref`` /
    ``key_retro`` (what Lahman's People.csv gives us via ``bbrefID`` /
    ``retroID``). It ships as 18 shards (``people-0.csv`` .. ``people-9``,
    ``people-a`` .. ``people-f``), ~4.2MB each (~75MB total) — not "too
    heavy" for a one-time local cache, so this is the primary bridge; see
    ``mlb/person_map.py`` for the name+birthyear fallback used only for
    unmatched rows.
"""

from __future__ import annotations

import logging
import pathlib
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) data_explorer/mlb"
HTTP_TIMEOUT = 60  # seconds — these are multi-MB files, not tiny API calls
POLITE_DELAY = 0.5  # seconds between downloads, we're hitting shared infra

# ── SABR Box distribution (Lahman "Version 2025") ───────────────────────────
SABR_SHARED_NAME = "y1prhc795jk8zvmelfd3jq7tl389y6cd"
SABR_BOX_HOST = "https://sabr.box.com/index.php"

# filename -> Box file id, hand-verified against the shared folder's own
# embedded metadata (itemSize matched the downloaded byte count for each).
SABR_FILES = {
    "People.csv": "2084263017537",
    "Batting.csv": "2084272468053",
    "Pitching.csv": "2084261668691",
    "HallOfFame.csv": "2084268925644",
}

# AwardsPlayers.csv is missing from the live SABR folder (see module
# docstring) — fall back to a GitHub mirror of the pre-2023 repo layout.
# STALE: this mirror was last pushed 2022-10-31, so awards data stops after
# the 2021 season. Replace with SABR's own file once they backfill it.
AWARDS_PLAYERS_FALLBACK_URL = (
    "https://raw.githubusercontent.com/cbwinslow/baseballdatabank"
    "/master/contrib/AwardsPlayers.csv"
)
AWARDS_PLAYERS_STALE_THROUGH_YEAR = 2021

# ── Chadwick register (id bridge) ───────────────────────────────────────────
REGISTER_SHARD_NAMES = [f"people-{c}" for c in "0123456789abcdef"]
REGISTER_BASE_URL = "https://raw.githubusercontent.com/chadwickbureau/register/master/data/{name}.csv"


def make_session() -> requests.Session:
    """Retry transient failures (429 + 5xx) with backoff, per workspace standard."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def box_download_url(shared_name: str, file_id: str) -> str:
    """Box's legacy anonymous-download URL for one file in a shared folder.
    Verified: byte-identical to the file's Box-reported ``itemSize`` for
    every SABR_FILES entry."""
    return f"{SABR_BOX_HOST}?rm=box_download_shared_file&shared_name={shared_name}&file_id=f_{file_id}"


def fetch_to_cache(session: requests.Session, url: str, dest: pathlib.Path) -> pathlib.Path:
    """Download ``url`` to ``dest`` unless already cached (resumable — safe
    to re-run the whole build). Fails loudly on a non-2xx after retries."""
    if dest.exists() and dest.stat().st_size > 0:
        log.info("cached: %s (%d bytes)", dest.name, dest.stat().st_size)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = session.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    if len(resp.content) == 0:
        raise RuntimeError(f"empty response body for {url!r} — refusing to cache")
    dest.write_bytes(resp.content)
    log.info("fetched: %s -> %s (%d bytes)", url, dest.name, len(resp.content))
    time.sleep(POLITE_DELAY)
    return dest


def fetch_lahman_csvs(session: requests.Session, raw_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    """Download the 4 SABR-hosted Lahman CSVs + the AwardsPlayers.csv
    fallback. Returns {table_name: cached_path}."""
    paths = {}
    for filename, file_id in SABR_FILES.items():
        url = box_download_url(SABR_SHARED_NAME, file_id)
        paths[filename] = fetch_to_cache(session, url, raw_dir / filename)

    log.warning(
        "AwardsPlayers.csv missing from live SABR Box folder — using stale "
        "GitHub fallback (through %d season only): %s",
        AWARDS_PLAYERS_STALE_THROUGH_YEAR, AWARDS_PLAYERS_FALLBACK_URL,
    )
    paths["AwardsPlayers.csv"] = fetch_to_cache(
        session, AWARDS_PLAYERS_FALLBACK_URL, raw_dir / "AwardsPlayers.csv"
    )
    return paths


def fetch_register(session: requests.Session, raw_dir: pathlib.Path) -> list[pathlib.Path]:
    """Download all 18 Chadwick register shards (~75MB total, one-time cache)."""
    paths = []
    for name in REGISTER_SHARD_NAMES:
        url = REGISTER_BASE_URL.format(name=name)
        paths.append(fetch_to_cache(session, url, raw_dir / f"{name}.csv"))
    return paths
