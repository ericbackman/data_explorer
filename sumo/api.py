"""
sumo-api.com client + pure parsers
==================================
Thin wrapper over the free community API at https://sumo-api.com. Network code
(session, retry, timeout) is kept separate from the ``parse_*`` functions so the
parsers can be unit-tested against captured JSON without touching the network.

Endpoints we use (all GET, all JSON):

  /api/basho/{bashoId}/torikumi/{division}/{day}  -> the bouts on one day
  /api/rikishi/{id}?measurements=true&ranks=true  -> one wrestler: bio +
                                                     measurement change-points +
                                                     full rank history

``bashoId`` is ``YYYYMM`` for the six annual honbasho (odd months: Jan, Mar,
May, Jul, Sep, Nov). ``division`` is ``Makuuchi`` or ``Juryo`` for the sekitori.

DATA-MODEL NOTE — measurements are *change-points*, not per-tournament rows.
A wrestler measured 190cm/158kg at debut and 189cm/174kg five years later has
two rows, not thirty. Attaching a weight to a specific bout therefore requires a
point-in-time ("as-of") join, handled in physical.py — never a naive join to a
single current weight, which would be silently wrong for historical bouts.
"""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# ── Endpoints ────────────────────────────────────────────────────────────────
BASE = "https://sumo-api.com/api"
TORIKUMI_URL = BASE + "/basho/{basho_id}/torikumi/{division}/{day}"
BASHO_URL = BASE + "/basho/{basho_id}"                      # summary: yusho + sansho
RIKISHI_URL = BASE + "/rikishi/{rikishi_id}?measurements=true&ranks=true"
RIKISHI_STATS_URL = BASE + "/rikishi/{rikishi_id}/stats"    # career accolade totals

USER_AGENT = "data_explorer/sumo (https://github.com/ericbackman/data_explorer)"
HTTP_TIMEOUT = 25  # seconds, per request

# The two salaried, every-tournament-measured divisions ("sekitori").
DIVISIONS = ("Makuuchi", "Juryo")

# The six honbasho each year fall in these (odd) months. Basho ids are YYYYMM.
BASHO_MONTHS = (1, 3, 5, 7, 9, 11)

# Default earliest tournament: January 2005 (~two decades). SumoDB reaches far
# further back; this is the requested window, overridable on the CLI.
DEFAULT_START_BASHO = "200501"


# ── HTTP session ─────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    """A session that retries transient failures (429 + 5xx) with backoff and
    honors Retry-After, per the workspace standard for external calls."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,                       # 0s, 1s, 2s, 4s, 8s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def get_json(session: requests.Session, url: str) -> dict:
    """GET with a hard timeout; raise loudly on a non-2xx that survived retries."""
    resp = session.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── Basho enumeration ────────────────────────────────────────────────────────

def enumerate_basho(start: str, end: str) -> list[str]:
    """Every honbasho id (YYYYMM) in ``[start, end]`` inclusive.

    >>> enumerate_basho("200501", "200507")
    ['200501', '200503', '200505', '200507']
    """
    start_i, end_i = int(start), int(end)
    out = []
    for year in range(start_i // 100, end_i // 100 + 1):
        for month in BASHO_MONTHS:
            bid = year * 100 + month
            if start_i <= bid <= end_i:
                out.append(f"{bid:06d}")
    return out


# ── Fetch (network) ──────────────────────────────────────────────────────────

def fetch_torikumi(session: requests.Session, basho_id: str, division: str, day: int) -> dict:
    """Raw JSON for one division's bouts on one day of one tournament."""
    return get_json(session, TORIKUMI_URL.format(basho_id=basho_id, division=division, day=day))


def fetch_rikishi(session: requests.Session, rikishi_id: int) -> dict:
    """Raw JSON for one wrestler, including measurementHistory + rankHistory."""
    return get_json(session, RIKISHI_URL.format(rikishi_id=rikishi_id))


def fetch_basho(session: requests.Session, basho_id: str) -> dict:
    """Tournament summary: champions (yusho) + special prizes (sansho)."""
    return get_json(session, BASHO_URL.format(basho_id=basho_id))


def fetch_rikishi_stats(session: requests.Session, rikishi_id: int) -> dict:
    """One wrestler's career totals: yusho, sansho, W-L, tournaments by division."""
    return get_json(session, RIKISHI_STATS_URL.format(rikishi_id=rikishi_id))


# ── Pure parsers (no network) ────────────────────────────────────────────────

def parse_bouts(raw: dict) -> list[dict]:
    """A torikumi payload -> flat, *completed* bout records.

    Only bouts with a real winner are kept: this drops not-yet-fought matches on
    the current in-progress tournament (so re-running the backfill picks them up
    once they happen). The winning *technique* (kimarite) is kept so the analysis
    can exclude ``fusen`` — default wins where a wrestler was absent and no actual
    sumo occurred; those are not physical contests.
    """
    bouts = []
    for r in raw.get("torikumi") or []:
        winner_id = r.get("winnerId")
        east_id, west_id = r.get("eastId"), r.get("westId")
        if not winner_id or not east_id or not west_id:
            continue
        bouts.append({
            "basho_id": r["bashoId"],
            "division": r["division"],
            "day": r["day"],
            "match_no": r["matchNo"],
            "east_id": east_id,
            "west_id": west_id,
            "east_shikona": r.get("eastShikona"),
            "west_shikona": r.get("westShikona"),
            "east_rank": r.get("eastRank"),
            "west_rank": r.get("westRank"),
            "winner_id": winner_id,
            "kimarite": r.get("kimarite") or "",
        })
    return bouts


def parse_basho_meta(raw: dict, basho_id: str) -> dict:
    """The tournament-level header carried on every torikumi payload."""
    return {
        "id": basho_id,
        "start_date": (raw.get("startDate") or "")[:10] or None,
        "end_date": (raw.get("endDate") or "")[:10] or None,
        "location": raw.get("location"),
    }


def parse_rikishi(raw: dict) -> dict:
    """One wrestler payload -> the identity/bio row for the ``rikishi`` table.

    height/weight here are the *latest* recorded values; the historical series
    lives in measurementHistory (see :func:`parse_measurements`).
    """
    return {
        "id": raw["id"],
        "sumodb_id": raw.get("sumodbId"),
        "nsk_id": raw.get("nskId"),
        "shikona_en": raw.get("shikonaEn"),
        "shikona_jp": raw.get("shikonaJp"),
        "heya": raw.get("heya"),                        # training stable
        "birth_date": (raw.get("birthDate") or "")[:10] or None,
        "shusshin": raw.get("shusshin"),                # birthplace / origin
        "debut": raw.get("debut"),                      # YYYYMM of first basho
        "height_cm": _positive(raw.get("height")),
        "weight_kg": _positive(raw.get("weight")),
    }


def parse_measurements(raw: dict) -> list[dict]:
    """measurementHistory -> ``measurements`` rows, dropping 0/absent values.

    Each row is a change-point: the wrestler's height/weight *as recorded at*
    ``basho_id``, valid until the next recorded change.
    """
    rows = []
    for m in raw.get("measurementHistory") or []:
        height, weight = _positive(m.get("height")), _positive(m.get("weight"))
        if height is None and weight is None:
            continue
        rows.append({
            "rikishi_id": raw["id"],
            "basho_id": m["bashoId"],
            "height_cm": height,
            "weight_kg": weight,
        })
    return rows


def parse_ranks(raw: dict) -> list[dict]:
    """rankHistory -> ``ranks`` rows. ``rank_value`` is numeric (lower = higher
    rank: Yokozuna 1 East = 101), which is what the analysis controls on."""
    rows = []
    for rk in raw.get("rankHistory") or []:
        rows.append({
            "rikishi_id": raw["id"],
            "basho_id": rk["bashoId"],
            "rank_value": rk.get("rankValue"),
            "rank": rk.get("rank"),
        })
    return rows


def parse_yusho(raw: dict, basho_id: str) -> list[dict]:
    """Basho summary -> ``yusho`` rows: the champion of each division.

    ``type`` is the division name (Makuuchi, Juryo, ...). A Makuuchi yusho is the
    sport's top honour; lower-division ones are kept too (free, and they mark a
    wrestler's rise). Playoff-decided titles still surface as a single champion.
    """
    rows = []
    for y in raw.get("yusho") or []:
        rid = y.get("rikishiId")
        if not rid:
            continue
        rows.append({"basho_id": basho_id, "division": y.get("type"), "rikishi_id": rid})
    return rows


def parse_sansho(raw: dict, basho_id: str) -> list[dict]:
    """Basho summary -> ``sansho`` rows: the three special prizes (Makuuchi only).

    Shukun-sho (Outstanding Performance), Kanto-sho (Fighting Spirit), Gino-sho
    (Technique). A prize can be co-awarded to two wrestlers in one basho, and a
    wrestler can take two different prizes — both are distinct rows.
    """
    rows = []
    for s in raw.get("specialPrizes") or []:
        rid = s.get("rikishiId")
        if not rid:
            continue
        rows.append({"basho_id": basho_id, "prize": s.get("type"), "rikishi_id": rid})
    return rows


def parse_stats(raw: dict, rikishi_id: int) -> dict:
    """Career-stats payload -> one flat ``rikishi_stats`` accolade card.

    Totals are career-to-date (final, for retired wrestlers). We flatten the few
    scalars that matter for accolades; the byDivision detail is derivable from
    our own bouts/ranks tables if ever needed.
    """
    ybd = raw.get("yushoByDivision") or {}
    bbd = raw.get("bashoByDivision") or {}
    wbd = raw.get("winsByDivision") or {}
    sansho = raw.get("sansho") or {}
    return {
        "rikishi_id": rikishi_id,
        "career_basho": raw.get("basho"),
        "total_matches": raw.get("totalMatches"),
        "total_wins": raw.get("totalWins"),
        "total_losses": raw.get("totalLosses"),
        "total_absences": raw.get("totalAbsences"),
        "yusho": raw.get("yusho"),                               # all divisions
        "makuuchi_yusho": ybd.get("Makuuchi", 0),               # the prestige count
        "juryo_yusho": ybd.get("Juryo", 0),
        "sansho_total": sum(sansho.values()) if isinstance(sansho, dict) else 0,
        "makuuchi_basho": bbd.get("Makuuchi", 0),               # longevity at the top
        "makuuchi_wins": wbd.get("Makuuchi", 0),
    }


def _positive(value) -> float | None:
    """Treat 0 / negative / missing measurements as unknown (NULL), not real."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None
