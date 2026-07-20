"""
MLB StatsAPI draft client + pure parsers
=========================================
Thin, testable wrapper over the free, no-key MLB Stats API draft endpoint:

    https://statsapi.mlb.com/api/v1/draft/{year}

Verified against 1965 (first-ever draft, Rick Monday #1 overall, Athletics),
1988 (round 62, Mike Piazza, Dodgers — the classic draft-steal), 2009
(Stephen Strasburg #1, Nationals) and 2025 (Eli Willits #1, Nationals).

Key shape facts confirmed against live data (not assumed):
  * ``drafts.rounds`` is a list of round-groups in pick order (round-number
    order interleaved with competitive-balance rounds in their real slot).
  * Each round-group has ``round`` (native label: "1".."80"+, or "C-A"/"C-B"
    for competitive-balance rounds) and ``picks``.
  * Each pick already carries a **global** ``pickNumber`` /
    ``displayPickNumber`` (identical in every sample checked) that is
    continuous across the whole draft, including CB rounds — so "overall
    pick" does NOT need to be computed from round+round-pick, the API hands
    it to us directly. ``roundPickNumber`` is the pick's position within its
    own round.
  * Every pick sampled across 1965/1975/1988/1996/2007/2009/2025 had
    ``isPass: false`` and a populated ``person`` block — the endpoint only
    lists picks that were actually made; it does not emit placeholder rows
    for forfeited/passed slots. The ``is_pass``/``mlbam_id is NULL`` columns
    in the DB exist defensively in case a future/unsampled year differs, but
    every draft checked so far has no such rows.
  * Unsigned-then-redrafted players are real and expected: J.D. Drew was
    pick #2 in 1997 (Phillies, unsigned) and pick #5 in 1998 (Cardinals,
    signed) — same ``person.id`` (136770) in both years. Duplicates by
    person id across years are legitimate, not a scrape bug.
"""

from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DRAFT_URL = "https://statsapi.mlb.com/api/v1/draft/{year}"
USER_AGENT = "data_explorer/mlb (https://github.com/ericbackman/data_explorer)"
HTTP_TIMEOUT = 30  # seconds, per request

FIRST_DRAFT_YEAR = 1965  # the first-ever MLB First-Year Player Draft


def make_session() -> requests.Session:
    """A session that retries transient failures (429 + 5xx) with backoff,
    per the workspace standard for external calls."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,  # 0s, 1s, 2s, 4s, 8s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_draft_year(session: requests.Session, year: int) -> dict:
    """Raw draft JSON for one year. Raises loudly on a non-2xx that survived
    retries (fail loud, per workspace standard — no silent empty-year)."""
    resp = session.get(DRAFT_URL.format(year=year), timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── Pure parsers (no network) ────────────────────────────────────────────────

def parse_draft_year(raw: dict) -> list[dict]:
    """Flatten one year's raw draft JSON into flat pick records.

    ``round_sort`` is the 1-based index of the round-group as the API
    returns it — this already interleaves competitive-balance rounds in
    their correct pick-order slot, so it sorts correctly without having to
    parse/guess the "C-A" / "C-B" labeling convention.
    """
    drafts = raw.get("drafts", {})
    year = drafts.get("draftYear")
    rounds = drafts.get("rounds", [])

    records = []
    for round_sort, round_group in enumerate(rounds, start=1):
        round_label = round_group.get("round")
        for pick in round_group.get("picks", []):
            records.append(parse_pick(pick, year, round_label, round_sort))
    return records


def parse_pick(pick: dict, year, round_label, round_sort: int) -> dict:
    """One pick JSON object -> a flat record ready for SQLite insertion."""
    person = pick.get("person") or {}
    team = pick.get("team") or {}
    school = pick.get("school") or {}
    position = person.get("primaryPosition") or {}
    draft_type = pick.get("draftType") or {}

    return {
        "year": int(year),
        "overall_pick": pick.get("pickNumber"),
        "round": round_label,
        "round_sort": round_sort,
        "round_pick": pick.get("roundPickNumber"),
        "bis_player_id": pick.get("bisPlayerId"),
        "mlbam_id": person.get("id"),
        "player_name": person.get("fullName"),
        "birth_date": person.get("birthDate"),
        "position": position.get("abbreviation"),
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "school_name": school.get("name"),
        "school_class": school.get("schoolClass"),
        "draft_type_code": draft_type.get("code"),
        "is_drafted": 1 if pick.get("isDrafted") else 0,
        "is_pass": 1 if pick.get("isPass") else 0,
    }
