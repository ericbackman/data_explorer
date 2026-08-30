#!/usr/bin/env python3
"""
build_data.py -- Build data.js for the Canadian fiscal ledger investigation.

Pulls three Statistics Canada tables through the Web Data Service (no API key),
caches the raw CSVs, and emits a single `const LEDGER_DATA = {...}` for the page
to load via a plain <script> tag.

    python build_data.py            # use cache when present
    python build_data.py --refresh  # re-download everything

The two halves of the ledger are deliberately drawn on the SAME consolidation
basis so they can sit side by side:

    revenue   36-10-0450, "General governments"
    spending  10-10-0005, "Consolidated Canadian general government"

They are still not expected to net to zero -- CCOFOG excludes capital
acquisition and consumption of fixed capital. The `bridge` block carries those
two lines explicitly so the page can show the gap rather than hide it.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("build_data")

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
OUT = HERE / "data.js"

WDS_CSV = "https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/{pid}/en"
WDS_META = "https://www150.statcan.gc.ca/t1/wds/rest/getCubeMetadata"

# Product IDs. Keep the human title next to each so a failure names the table.
TBL_FISCAL = 36100450  # Revenue, expenditure -- provincial & territorial economic accounts
TBL_CCOFOG = 10100005  # Functions of government (CCOFOG) by consolidated component
TBL_POP = 17100009     # Population estimates, quarterly

# The distributional layer comes from the CRA, not Statistics Canada: Table 2 of
# the annual individual income tax statistics, "all returns by income range".
#
# Its URLs cannot be constructed. The filename drifts by edition (t02ca / tbl2 /
# tbl2ac / table2_ac / tbl2_ac / tbl2_ac_en) and canada.ca answers a wrong guess
# with an HTTP 200 carrying an HTML page, so a status check alone will happily
# cache a web page as a data file. Every URL is therefore resolved from the open
# data catalogue, and every download is sniffed for HTML before it is kept.
CKAN_SEARCH = (
    "https://open.canada.ca/data/en/api/3/action/package_search"
    "?q=title:(%22T1%20Final%20Statistics%22%20OR%20"
    "%22Individual%20Income%20Tax%20Return%20Statistics%22)&rows=40"
)

# The table was renamed in the 2022 edition; both spellings must match.
CRA_TABLE2 = re.compile(r"income range|total income class", re.I)
# Provincial resources cannot be identified by name: in the 2024 edition every
# per-province file is simply called "Alberta", whether it is Table 2 (income
# ranges) or Table 4 (age and gender), and in 2021 they are "Final Table 2 -
# Alberta" and "Final Table 3 - Alberta". Only the filename reliably says which
# table it is, so match on that and let the name identify the geography.
CRA_TABLE2_FILE = re.compile(r"/(tbl|table)0?2[_-]", re.I)
# French editions sit beside the English ones under several spellings, and the
# catalogue's `format` field is not trustworthy -- at least one French PDF
# (2021 Alberta) is registered as a CSV -- so the URL must end in .csv too.
CRA_FRENCH = re.compile(r"[_-]fra?[._-]|/fr/|[_-]fr\.", re.I)
# Exclude the per-province cuts and Table 2A, which covers taxable returns only.
CRA_EXCLUDE = re.compile(
    r"alberta|british columbia|manitoba|new brunswick|newfoundland|nova scotia|"
    r"nunavut|ontario|prince edward|quebec|saskatchewan|yukon|northwest|"
    r"non.?resident|taxable returns", re.I
)

# Line items to lift out of each edition. These are matched by NAME, because the
# CRA renumbers its rows between editions -- row 104 is "Net provincial or
# territorial tax" in the 2022 file and "Eligible educator school supply tax
# credit" in the 2023 one. (Statistics Canada is the opposite: stable ids,
# duplicated names. Neither source can be joined the way the other one must be.)
CRA_LINES = {
    "filers": "Total number of returns",
    "income": "Total income assessed",
    "tax": "Total tax payable",
    # Carried only to detect separately-administered provincial tax; see
    # SELF_ADMIN_SHARE below.
    "provincial": "Net provincial or territorial tax",
}

# Quebec collects its own income tax through Revenu Quebec, so a Quebec return
# filed with the CRA carries essentially no provincial tax: $0.1B in 2024
# against Ontario's $54.0B on a base 54% as large. "Total tax payable" for
# Quebec is therefore close to federal tax alone, and putting it beside the
# other provinces makes Quebec look like the lowest-taxing province in Canada,
# which is the opposite of the truth. The condition is derived from the data
# rather than hardcoded to one province, so that if another province ever left
# the collection agreement it would be caught the same way.
SELF_ADMIN_SHARE = 0.05

# Header layouts also drift. Through the 2021 edition the paired columns are
# suffixed "<band> #" and "<band> $ (000)"; from 2022 they read "<band> (Number /
# Nombre)" and "<band> (Thousands of Dollars / ...)". The total column is
# "Grand total/Total global" in the old style and plain "Total" in the new.
CRA_COUNT_COL = re.compile(r"\(\s*number|#\s*$", re.I)
CRA_TOTAL_BAND = re.compile(r"^(grand\s+)?total", re.I)

# The dimension members we slice to. A change in these strings upstream should
# fail loudly (see `_require_rows`) rather than silently produce an empty chart.
#
# Why the ledger is national-only:
#   CCOFOG publishes "Consolidated Canadian general government" for Canada alone;
#   every province carries only the provincial-territorial-and-local component.
#   The revenue table, meanwhile, offers no consolidated provincial+local level --
#   summing "Provincial and territorial" and "Local" would double-count the
#   transfers running between them. So there is exactly one pairing of the two
#   tables that sits on a single consolidation basis, and it is Canada-wide.
#   Provinces therefore get the spending half only, which StatCan documents as
#   cross-province comparable (table 10-10-0005, footnote 5).
LEVEL_GENERAL = "General governments"
COMPONENT_NATIONAL = "Consolidated Canadian general government"
COMPONENT_SUBNATIONAL = "Consolidated provincial-territorial and local governments"
NATIONAL = "Canada"

# Reconciliation lines, taken from 36-10-0450's own estimate list.
BRIDGE_LINES = {
    "revenue": "General governments revenue",
    "expenditure": "General governments expenditure",
    "balance": "General governments surplus or deficit",
    "cfc": "Plus: consumption of fixed capital",
    "capital": "Less: non-financial capital acquisition",
}

# Province ordering: west to east, territories last, Canada first. Statistics
# Canada emits alphabetically, which reads as noise on a map-shaped page.
GEO_ORDER = [
    "Canada",
    "British Columbia", "Alberta", "Saskatchewan", "Manitoba", "Ontario", "Quebec",
    "New Brunswick", "Nova Scotia", "Prince Edward Island",
    "Newfoundland and Labrador",
    "Yukon", "Northwest Territories", "Nunavut",
]

GEO_ABBR = {
    "Canada": "CAN", "British Columbia": "BC", "Alberta": "AB",
    "Saskatchewan": "SK", "Manitoba": "MB", "Ontario": "ON", "Quebec": "QC",
    "New Brunswick": "NB", "Nova Scotia": "NS", "Prince Edward Island": "PE",
    "Newfoundland and Labrador": "NL", "Yukon": "YT",
    "Northwest Territories": "NT", "Nunavut": "NU",
}


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #

# An explicit empty ProxyHandler skips urllib's system-proxy lookup per request.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Download URLs are not written here -- they are read out of the open data
# catalogue's JSON, so their host and scheme come from a response rather than
# from this file. That is fine while the catalogue is honest, and this pins it:
# a redirected or tampered entry pointing somewhere else fails instead of being
# fetched and cached as data.
ALLOWED_HOSTS = frozenset({
    "www150.statcan.gc.ca",
    "open.canada.ca",
    "www.canada.ca",
    "donnees-data.tpsgc-pwgsc.gc.ca",
})


def _check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise RuntimeError(f"refusing non-HTTPS URL: {url}")
    if parts.hostname not in ALLOWED_HOSTS:
        raise RuntimeError(
            f"refusing {parts.hostname!r}: not one of the expected open data hosts "
            f"({', '.join(sorted(ALLOWED_HOSTS))}). If Statistics Canada or the CRA "
            f"has genuinely moved, add the host here deliberately."
        )


def _http(url: str, *, data: bytes | None = None, timeout: int = 120) -> bytes:
    """GET/POST with a timeout and a bounded retry on transient failures.

    The Accept header is load-bearing, not decoration. canada.ca stalls a request
    that omits it until the socket times out, while the same URL fetched by curl
    -- which always sends `Accept: */*` -- returns in about two seconds. urllib
    sends no Accept header of its own, so without this line every CRA download
    fails with a read timeout that looks like the server being down.
    """
    headers = {
        "User-Agent": "canada-fiscal-ledger/1.0 (+data_explorer)",
        "Accept": "*/*",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    _check_url(url)

    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with _OPENER.open(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status} from {url}")
                return resp.read()
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            wait = 2 ** attempt
            log.warning("request failed (%s), retrying in %ss: %s", exc, wait, url)
            time.sleep(wait)
    raise RuntimeError(f"gave up on {url}") from last


def fetch_table(pid: int, *, refresh: bool) -> list[dict]:
    """Download a full StatCan table as rows of dicts, cached as CSV on disk."""
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"{pid}.csv"

    if cached.exists() and not refresh:
        log.info("table %s: using cache (%.1f MB)", pid, cached.stat().st_size / 1e6)
    else:
        log.info("table %s: asking WDS for the download link", pid)
        payload = json.loads(_http(WDS_CSV.format(pid=pid)).decode("utf-8"))
        if payload.get("status") != "SUCCESS":
            raise RuntimeError(f"table {pid}: WDS refused the request: {payload}")

        url = payload["object"]
        log.info("table %s: downloading %s", pid, url)
        blob = _http(url, timeout=600)

        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            name = f"{pid}.csv"
            if name not in zf.namelist():
                raise RuntimeError(f"table {pid}: {name} missing from zip ({zf.namelist()})")
            cached.write_bytes(zf.read(name))
        log.info("table %s: cached %.1f MB", pid, cached.stat().st_size / 1e6)

    with cached.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def fetch_meta(pid: int, *, refresh: bool) -> dict:
    """Cube metadata -- needed for the parent/child hierarchy and release date."""
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"{pid}.meta.json"

    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))

    log.info("table %s: fetching cube metadata", pid)
    body = json.dumps([{"productId": pid}]).encode("utf-8")
    payload = json.loads(_http(WDS_META, data=body).decode("utf-8"))
    if payload[0].get("status") != "SUCCESS":
        raise RuntimeError(f"table {pid}: metadata request failed: {payload}")

    obj = payload[0]["object"]
    cached.write_text(json.dumps(obj), encoding="utf-8")
    return obj


def resolve_cra_tables(*, refresh: bool) -> dict[str, dict[str, str]]:
    """Map tax year -> {geography -> URL} for Table 2, from the open data catalogue.

    Every edition publishes an all-Canada cut plus one file per province and
    territory. Resource naming differs across the 2022 rebrand ("Final Table 2 -
    Alberta" against a bare "Alberta"), so provinces are matched on the name
    ending rather than an exact string.
    """
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / "cra_urls_by_geo.json"
    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))

    log.info("CRA: resolving Table 2 URLs from the open data catalogue")
    payload = json.loads(_http(CKAN_SEARCH).decode("utf-8"))
    if not payload.get("success"):
        raise RuntimeError(f"CKAN search failed: {payload}")

    def name_of(res: dict) -> str:
        n = res.get("name")
        return (n.get("en") if isinstance(n, dict) else n) or ""

    provinces = [g for g in GEO_ORDER if g != NATIONAL]
    found: dict[str, dict[str, str]] = {}

    for pkg in payload["result"]["results"]:
        title = pkg.get("title")
        title = title.get("en") if isinstance(title, dict) else title
        match = re.search(r"(\d{4})\s*[Tt]ax [Yy]ear", str(title))
        if not match:
            continue
        year = match.group(1)
        by_geo: dict[str, str] = {}

        for res in pkg.get("resources", []):
            if res.get("format") != "CSV":
                continue
            if CRA_FRENCH.search(res["url"]) or not res["url"].lower().endswith(".csv"):
                continue
            label = name_of(res).strip()

            if (CRA_TABLE2.search(label) and not CRA_EXCLUDE.search(label)):
                by_geo.setdefault(NATIONAL, res["url"])
                continue

            if not CRA_TABLE2_FILE.search(res["url"]):
                continue
            for prov in provinces:
                # the province is the whole name, or trails a "Table 2 -" prefix
                if re.search(r"(^|[-–—:]\s*)" + re.escape(prov) + r"\s*$",
                             label, re.I):
                    by_geo.setdefault(prov, res["url"])
                    break

        if by_geo:
            found[year] = by_geo

    if not found:
        raise RuntimeError("CRA: the catalogue returned no Table 2 resources")

    cached.write_text(json.dumps(found, indent=1), encoding="utf-8")
    log.info("CRA: resolved %s tax years (%s-%s), %s geographies at the newest",
             len(found), min(found), max(found), len(found[max(found)]))
    return found


def fetch_cra_year(year: str, url: str, *, geo: str = NATIONAL,
                   refresh: bool) -> list[list[str]]:
    """Download one edition's Table 2, refusing anything that is not a CSV."""
    CACHE.mkdir(exist_ok=True)
    suffix = "" if geo == NATIONAL else "_" + GEO_ABBR.get(geo, geo[:2]).lower()
    cached = CACHE / f"cra_{year}{suffix}.csv"
    # Several archived editions have rotted catalogue links that answer with a
    # web page. Remember that verdict so a rebuild does not re-fetch them.
    tombstone = CACHE / f"cra_{year}{suffix}.dead"

    if tombstone.exists() and not refresh:
        raise RuntimeError(f"CRA {year}: {tombstone.read_text(encoding='utf-8').strip()}")

    if not cached.exists() or refresh:
        log.info("CRA %s %s: downloading %s", year, GEO_ABBR.get(geo, geo),
                 url.rsplit("/", 1)[-1])
        blob = _http(url, timeout=180)
        head = blob[:400].lstrip()
        lower = head.lower()

        reason = None
        if lower.startswith(b"<!doctype") or b"<html" in lower:
            reason = (f"{url} returned an HTML page, not a CSV -- canada.ca answers "
                      f"unknown paths with a styled 200, so this edition's catalogue "
                      f"link has rotted")
        elif head.startswith(b"%PDF"):
            # The catalogue mislabels at least one PDF as a CSV; without this the
            # failure surfaces as an unrelated character-decoding error.
            reason = f"{url} is a PDF, though the catalogue registers it as a CSV"
        if reason:
            tombstone.write_text(reason, encoding="utf-8")
            raise RuntimeError(f"CRA {year} {geo}: {reason}")
        tombstone.unlink(missing_ok=True)
        cached.write_bytes(blob)

    # These files are Windows-encoded and carry French labels in every row.
    with cached.open(encoding="cp1252", newline="") as fh:
        return list(csv.reader(fh))


def parse_cra_table(rows: list[list[str]], year: str) -> dict:
    """Pull filers / income / tax per income band out of one edition.

    Amount columns are thousands of dollars and are converted to millions to
    match the Statistics Canada tables; counts stay as counts.
    """
    header = rows[0]

    # The leading metadata columns are "#, Item, Poste, Tax year" -- and that
    # first one is literally "#", which the old-style count-column pattern would
    # otherwise match, shifting every band by one. Start after the tax-year cell.
    start = next((i for i, c in enumerate(header) if re.search(r"tax year", c, re.I)), 3) + 1

    bands, pairs = [], []
    for i, cell in enumerate(header):
        if i < start or not CRA_COUNT_COL.search(cell):
            continue
        # strip either the " (Number / Nombre)" or the trailing " #"
        label = re.split(r"\s*\(|\s*#\s*$", cell)[0].strip()
        if not label:
            continue
        bands.append(label)
        pairs.append((i, i + 1))
    if not bands:
        raise RuntimeError(
            f"CRA {year}: no count columns found -- the header layout has changed "
            f"again. First cells: {header[:6]}"
        )

    items: dict[str, list[str]] = {}
    for row in rows[1:]:
        if len(row) > 2 and row[1].strip():
            items.setdefault(row[1].strip().lower(), row)

    def read(line_key: str, col: int, *, required: bool = True) -> float:
        label = CRA_LINES[line_key]
        row = items.get(label.lower())
        if row is None:
            if not required:
                return 0.0
            raise RuntimeError(
                f"CRA {year}: line item {label!r} is missing -- the CRA renames "
                f"items between editions, so this needs a look, not a default."
            )
        raw = row[col].strip().replace(",", "") if col < len(row) else ""
        return float(raw) if raw else 0.0

    out = {"bands": [], "filers": [], "income": [], "tax": []}
    for band, (n_col, d_col) in zip(bands, pairs):
        if is_total_band(band):
            continue                                  # the "Total" column, kept separately
        out["bands"].append(clean_band(band))
        out["filers"].append(round(read("filers", n_col)))
        out["income"].append(round(read("income", d_col) / 1000))   # $000 -> $M
        out["tax"].append(round(read("tax", d_col) / 1000))

    total_col = next((p for b, p in zip(bands, pairs) if is_total_band(b)), None)
    if total_col is None:
        raise RuntimeError(f"CRA {year}: no Total column found")
    out["total"] = {
        "filers": round(read("filers", total_col[0])),
        "income": round(read("income", total_col[1]) / 1000),
        "tax": round(read("tax", total_col[1]) / 1000),
    }
    # Diagnostic only -- a missing provincial line must not fail the build.
    has_prov = CRA_LINES["provincial"].lower() in items
    prov = round(read("provincial", total_col[1], required=False) / 1000)
    out["total"]["provincial"] = prov
    # A province whose provincial tax barely appears is collecting it elsewhere.
    out["selfAdmin"] = bool(has_prov and out["total"]["tax"]
                            and prov / out["total"]["tax"] < SELF_ADMIN_SHARE)
    return out


def is_total_band(label: str) -> bool:
    return bool(CRA_TOTAL_BAND.match(label.strip()))


def clean_band(label: str) -> str:
    """'4999 and under/Moins de 4 999' -> 'Under $5,000'; ranges -> '$5,000-9,999'."""
    en = label.split("/")[0].strip()
    money = lambda n: "$" + f"{int(n):,}"

    m = re.match(r"^([\d\s]+)\s*and under$", en, re.I)
    if m:
        return "Under " + money(int(re.sub(r"\s", "", m.group(1))) + 1)

    m = re.match(r"^([\d\s]+)\s*and over$", en, re.I)
    if m:
        return money(re.sub(r"\s", "", m.group(1))) + "+"

    m = re.match(r"^([\d\s]+)\s*-\s*([\d\s]+)$", en)
    if m:
        lo = re.sub(r"\s", "", m.group(1))
        hi = re.sub(r"\s", "", m.group(2))
        return f"{money(lo)}–{int(hi):,}"

    return en


# --------------------------------------------------------------------------- #
# shaping
# --------------------------------------------------------------------------- #

def _require_rows(rows: list, what: str) -> list:
    """A filter that returns nothing means an upstream label moved. Say so."""
    if not rows:
        raise RuntimeError(
            f"no rows matched for {what} -- a dimension label almost certainly "
            f"changed upstream. Inspect the cached CSV before trusting any output."
        )
    return rows


def hierarchy(meta: dict, dim_match: str, *, under: str | None = None,
              levels: int = 2) -> tuple[list[str], list[int], list[int], int]:
    """Return (names, parent_index, member_ids, coord_position) for a dimension.

    Parent index is -1 for a root of the returned set.

    `under` restricts the result to the descendants of one named member -- used
    to pull just the revenue subtree out of a cube that also holds expenditure.
    `levels` counts how many generations below that root to keep, so the page
    gets a category and its children and nothing deeper.

    Member IDs come back because names are NOT unique: table 36-10-0450 carries
    "Capital transfers" and "From households" twice each, once under revenue and
    once under expenditure. Joining the CSV on the label silently pairs a revenue
    line with an expenditure value, so the join key must be the member id.
    `coord_position` is this dimension's 1-based slot in the COORDINATE column.
    """
    dims = [(i, d) for i, d in enumerate(meta["dimension"], start=1)
            if dim_match in d["dimensionNameEn"]]
    if not dims:
        raise RuntimeError(f"no dimension matching {dim_match!r} in cube {meta['productId']}")

    coord_position, dim = dims[0]
    members = dim["member"]
    by_id = {m["memberId"]: m for m in members}

    root_id = None
    if under is not None:
        match = [m for m in members if m["memberNameEn"] == under]
        if not match:
            raise RuntimeError(f"member {under!r} is no longer in cube {meta['productId']}")
        root_id = match[0]["memberId"]

    def chain(m: dict) -> list[int]:
        """Ancestor ids, nearest first."""
        out, p = [], m["parentMemberId"]
        while p is not None and p in by_id:
            out.append(p)
            p = by_id[p]["parentMemberId"]
        return out

    def keep(m: dict) -> bool:
        anc = chain(m)
        if root_id is None:
            return len(anc) < levels
        # depth relative to the named root; the root itself is excluded
        return root_id in anc and anc.index(root_id) < levels

    kept = [m for m in members if keep(m)]
    if not kept:
        raise RuntimeError(f"no members kept for {dim_match!r} (under={under!r})")

    pos = {m["memberId"]: i for i, m in enumerate(kept)}
    names = [m["memberNameEn"] for m in kept]
    parents = [pos.get(m["parentMemberId"], -1) for m in kept]
    member_ids = [m["memberId"] for m in kept]
    return names, parents, member_ids, coord_position


def strip_code(name: str) -> str:
    """CCOFOG names carry their classification codes: 'Defence [702]'."""
    return name.split(" [")[0].strip()


def to_millions(raw: str) -> int | None:
    """Values arrive as dollars in millions; keep them as ints, nulls stay null."""
    if raw in ("", None):
        return None
    try:
        return round(float(raw))
    except ValueError:
        return None


def series_matrix(rows: list[dict], *, member_ids: list[int], coord_position: int,
                  years: list[str], geos: list[str], what: str) -> dict:
    """Build {geo: {year: [value per member]}} from long-format StatCan rows.

    Rows are keyed on the member id read out of COORDINATE, never on the label
    -- see `hierarchy` for why the labels cannot be trusted as a join key.
    """
    idx = {mid: i for i, mid in enumerate(member_ids)}
    year_set, geo_set = set(years), set(geos)

    out: dict[str, dict[str, list]] = {
        g: {y: [None] * len(member_ids) for y in years} for g in geos
    }

    hits = 0
    for r in rows:
        y, g = r["REF_DATE"], r["GEO"]
        if y not in year_set or g not in geo_set:
            continue

        parts = r["COORDINATE"].split(".")
        if len(parts) < coord_position:
            raise RuntimeError(f"COORDINATE {r['COORDINATE']!r} has no slot {coord_position}")
        try:
            member = int(parts[coord_position - 1])
        except ValueError as exc:
            raise RuntimeError(f"bad COORDINATE {r['COORDINATE']!r}") from exc

        i = idx.get(member)
        if i is None:
            continue
        out[g][y][i] = to_millions(r["VALUE"])
        hits += 1

    _require_rows([1] if hits else [], f"{what} matrix")
    log.info("  %s: matched %s values across %s geos x %s years",
             what, hits, len(geos), len(years))
    return out


def build_population(rows: list[dict], years: list[str], geos: list[str]) -> dict:
    """Annual population = the Q3 (July 1) estimate, StatCan's own annual anchor."""
    pop: dict[str, dict[str, int]] = {g: {} for g in geos}
    geo_set = set(geos)

    for r in rows:
        ref = r["REF_DATE"]              # e.g. "2024-07"
        if not ref.endswith("-07"):
            continue
        year = ref[:4]
        if year not in years or r["GEO"] not in geo_set:
            continue
        val = to_millions(r["VALUE"])    # persons, scalar "units" -- not millions
        if val is not None:
            pop[r["GEO"]][year] = val

    missing = [g for g in geos if not pop[g]]
    if missing:
        raise RuntimeError(f"no population estimates for {missing}")
    return pop


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def build(refresh: bool) -> dict:
    log.info("fetching source tables")
    fiscal_meta = fetch_meta(TBL_FISCAL, refresh=refresh)
    ccofog_meta = fetch_meta(TBL_CCOFOG, refresh=refresh)

    fiscal_rows = fetch_table(TBL_FISCAL, refresh=refresh)
    ccofog_rows = fetch_table(TBL_CCOFOG, refresh=refresh)
    pop_rows = fetch_table(TBL_POP, refresh=refresh)

    # Years: the overlap of the two fiscal tables, so every year renders both halves.
    fy = {r["REF_DATE"] for r in fiscal_rows}
    cy = {r["REF_DATE"] for r in ccofog_rows}
    years = sorted(fy & cy)
    if not years:
        raise RuntimeError("the two fiscal tables share no reference years")
    log.info("overlapping years: %s -> %s (%s)", years[0], years[-1], len(years))

    geos = [g for g in GEO_ORDER if g in {r["GEO"] for r in fiscal_rows}]
    _require_rows(geos, "geographies")

    # ---- revenue + expenditure, consolidated general government --------------
    fiscal_general = _require_rows(
        [r for r in fiscal_rows if r["Levels of government"] == LEVEL_GENERAL],
        f"level of government == {LEVEL_GENERAL!r}",
    )

    # Top-level revenue categories plus one generation of detail beneath them,
    # so "Taxes on incomes" opens into households / corporations / non-residents.
    rev_names, rev_parents, rev_ids, est_pos = hierarchy(
        fiscal_meta, "Estimates", under=BRIDGE_LINES["revenue"], levels=2,
    )
    log.info("revenue categories: %s (incl. %s sub-lines)",
             sum(1 for p in rev_parents if p == -1),
             sum(1 for p in rev_parents if p != -1))
    rev_matrix = series_matrix(
        fiscal_general, member_ids=rev_ids, coord_position=est_pos,
        years=years, geos=[NATIONAL], what="revenue",
    )

    # ---- spending by function ----------------------------------------------
    fn_names_raw, fn_parents, fn_ids, fn_pos = hierarchy(ccofog_meta, "CCOFOG")
    fn_names = [strip_code(n) for n in fn_names_raw]
    log.info("functions (divisions + groups): %s", len(fn_names))

    # The ledger half: all levels of government, Canada only.
    national_rows = _require_rows(
        [r for r in ccofog_rows if r["Public sector components"] == COMPONENT_NATIONAL],
        f"public sector component == {COMPONENT_NATIONAL!r}",
    )
    fn_national = series_matrix(
        national_rows, member_ids=fn_ids, coord_position=fn_pos,
        years=years, geos=[NATIONAL], what="functions (national)",
    )

    # The comparison half: provincial + local, every province, no federal money.
    sub_rows = _require_rows(
        [r for r in ccofog_rows if r["Public sector components"] == COMPONENT_SUBNATIONAL],
        f"public sector component == {COMPONENT_SUBNATIONAL!r}",
    )
    fn_sub = series_matrix(
        sub_rows, member_ids=fn_ids, coord_position=fn_pos,
        years=years, geos=geos, what="functions (provincial)",
    )

    # ---- the bridge: why the two halves do not balance ----------------------
    all_names, _, all_ids, _ = hierarchy(fiscal_meta, "Estimates", levels=1)
    bridge_ids = []
    for key in ("revenue", "expenditure", "balance", "cfc", "capital"):
        name = BRIDGE_LINES[key]
        if name not in all_names:
            raise RuntimeError(f"bridge line {name!r} is no longer in table {TBL_FISCAL}")
        bridge_ids.append(all_ids[all_names.index(name)])

    bridge_matrix = series_matrix(
        fiscal_general, member_ids=bridge_ids, coord_position=est_pos,
        years=years, geos=[NATIONAL], what="bridge",
    )

    population = build_population(pop_rows, years, geos)

    # ---- the distributional layer: who actually paid the income tax --------
    cra_urls = resolve_cra_tables(refresh=refresh)

    # Editions differ more than they look. Through 2010 the item vocabulary is
    # different enough that the lines we need are absent; 2011 carries an extra
    # income band and its bands do not reconcile to its own published total.
    # Parse every edition, then keep the largest set that agrees on band shape --
    # first-wins would let one odd early year discard all the good ones.
    # The all-Canada cut decides which years are usable; provinces are then
    # loaded only for those years.
    parsed_by_year: dict[str, dict] = {}
    for year in sorted(cra_urls):
        url = cra_urls[year].get(NATIONAL)
        if not url:
            log.warning("CRA %s: no all-Canada resource in the catalogue", year)
            continue
        try:
            rows = fetch_cra_year(year, url, refresh=refresh)
            parsed_by_year[year] = parse_cra_table(rows, year)
        except RuntimeError as exc:
            log.warning("CRA %s: skipped -- %s", year, exc)

    if not parsed_by_year:
        raise RuntimeError("no CRA edition could be parsed")

    shapes: dict[tuple, list[str]] = {}
    for year, parsed in parsed_by_year.items():
        shapes.setdefault(tuple(parsed["bands"]), []).append(year)
    best = max(shapes.values(), key=len)
    band_shape = list(parsed_by_year[best[0]]["bands"])

    for shape, years_ in shapes.items():
        if years_ is not best:
            log.warning("CRA: dropping %s -- %s income bands, not the %s the rest share",
                        ", ".join(sorted(years_)), len(shape), len(band_shape))

    dist_years = sorted(best)

    def pack(parsed: dict) -> dict:
        out = {k: parsed[k] for k in ("filers", "income", "tax")}
        out["total"] = parsed["total"]
        out["selfAdmin"] = parsed["selfAdmin"]
        return out

    dist: dict[str, dict[str, dict]] = {NATIONAL: {}}
    for year in dist_years:
        dist[NATIONAL][year] = pack(parsed_by_year[year])

    # ---- the same table, one file per province and territory ---------------
    for geo in (g for g in GEO_ORDER if g != NATIONAL):
        per_year: dict[str, dict] = {}
        for year in dist_years:
            url = cra_urls[year].get(geo)
            if not url:
                log.warning("CRA %s %s: not in the catalogue", year, GEO_ABBR.get(geo, geo))
                continue
            try:
                parsed = parse_cra_table(
                    fetch_cra_year(year, url, geo=geo, refresh=refresh), f"{year} {geo}")
            except RuntimeError as exc:
                log.warning("CRA %s %s: skipped -- %s", year, GEO_ABBR.get(geo, geo), exc)
                continue
            if parsed["bands"] != band_shape:
                log.warning("CRA %s %s: %s income bands, not the %s Canada uses -- skipped",
                            year, GEO_ABBR.get(geo, geo), len(parsed["bands"]), len(band_shape))
                continue
            per_year[year] = pack(parsed)

        if per_year:
            dist[geo] = per_year
            if len(per_year) < len(dist_years):
                gaps = [y for y in dist_years if y not in per_year]
                log.warning("CRA %s: no Table 2 CSV for %s -- kept with %s of %s "
                            "years, and the page offers only the years it has",
                            GEO_ABBR.get(geo, geo), ", ".join(gaps),
                            len(per_year), len(dist_years))

    dist_geos = [g for g in GEO_ORDER if g in dist]
    log.info("distribution: %s tax years (%s-%s), %s geographies, %s income bands",
             len(dist_years), dist_years[0], dist_years[-1], len(dist_geos), len(band_shape))

    return {
        "meta": {
            "generated": time.strftime("%Y-%m-%d"),
            "basis": (
                "The ledger is Canada-wide and covers every level of government "
                "at once: revenue from table 36-10-0450 at the 'General "
                "governments' level, spending from table 10-10-0005 for "
                "'Consolidated Canadian general government'. The provincial "
                "comparison is spending only, on the provincial-territorial-and-"
                "local basis, because no consolidated provincial+local revenue "
                "series exists to pair with it."
            ),
            "sources": [
                {
                    "pid": "36-10-0450",
                    "title": fiscal_meta["cubeTitleEn"],
                    "released": fiscal_meta.get("releaseTime", "")[:10],
                    "url": f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={TBL_FISCAL}01",
                },
                {
                    "pid": "10-10-0005",
                    "title": ccofog_meta["cubeTitleEn"],
                    "released": ccofog_meta.get("releaseTime", "")[:10],
                    "url": f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={TBL_CCOFOG}01",
                },
                {
                    "pid": "17-10-0009",
                    "title": "Population estimates, quarterly",
                    "released": "",
                    "url": f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={TBL_POP}01",
                },
                {
                    "pid": "CRA Table 2",
                    "title": ("Individual income tax return statistics, all returns "
                              f"by income range ({dist_years[0]}-{dist_years[-1]} tax "
                              f"years, Canada and {len(dist_geos) - 1} provinces "
                              f"and territories)"),
                    "released": "",
                    "url": ("https://www.canada.ca/en/revenue-agency/programs/"
                            "about-canada-revenue-agency-cra/income-statistics-gst-hst-"
                            "statistics/t1-final-statistics.html"),
                },
            ],
            "caveats": [
                "Consolidated figures: transfers between governments are already "
                "netted out, so federal, provincial and local cannot be added together.",
                "The function totals exclude capital acquisition and consumption of "
                "fixed capital, which is why they fall short of total expenditure.",
                "CPP and QPP are outside the consolidated general government here.",
                "Federal Indigenous programs were reclassified into Housing and "
                "community amenities in 2023, breaking that series.",
                "The CRA income bands are nominal dollars and are never re-indexed, "
                "so movement between bands across years is partly inflation rather "
                "than real income growth.",
            ],
        },
        "geos": [{"name": g, "abbr": GEO_ABBR.get(g, g[:3].upper())} for g in geos],
        "years": years,
        "population": population,
        "revenue": {"names": rev_names, "parents": rev_parents, "series": rev_matrix},
        "spending": {
            "names": fn_names,
            "parents": fn_parents,
            "national": fn_national,
            "provincial": fn_sub,
        },
        "bridge": {"names": ["revenue", "expenditure", "balance", "cfc", "capital"],
                   "series": bridge_matrix},
        "distribution": {
            "years": dist_years,
            "bands": band_shape,
            "geos": [{"name": g, "abbr": GEO_ABBR.get(g, g[:3].upper()),
                       "years": sorted(dist[g]),
                       "selfAdmin": all(dist[g][y]["selfAdmin"] for y in dist[g])}
                      for g in dist_geos],
            "series": dist,
            "note": (
                "Personal income tax only, from individual returns filed and "
                "assessed for each tax year. This is one slice of the ledger's "
                "'Taxes on incomes', not the whole of it -- sales, payroll, "
                "corporate and property taxes are elsewhere. Administrative "
                "counts on a tax-year basis do not reconcile line-for-line with "
                "the national accounts."
            ),
        },
    }


def write_data_js(payload: dict) -> None:
    """Emit the plain-<script> module the page loads (no fetch, no CORS)."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    header = (
        "// GENERATED by build_data.py -- do not edit by hand.\n"
        "//\n"
        "// Statistics Canada tables 36-10-0450, 10-10-0005 and 17-10-0009,\n"
        "// reproduced and distributed on an 'as is' basis with the permission\n"
        "// of Statistics Canada. Values are millions of current dollars.\n"
        "//\n"
        f"// Built {payload['meta']['generated']}. Rebuild: python build_data.py --refresh\n\n"
    )
    OUT.write_text(f"{header}const LEDGER_DATA = {body};\n\n"
                   'if (typeof window !== "undefined") window.LEDGER_DATA = LEDGER_DATA;\n',
                   encoding="utf-8")
    log.info("wrote %s (%.0f KB)", OUT.name, OUT.stat().st_size / 1024)


def validate(payload: dict) -> None:
    """Check the output against facts known independently of this pipeline.

    A silent shape change upstream is the failure mode that matters here, so
    this asserts on magnitudes rather than just on structure.
    """
    years, geos = payload["years"], [g["name"] for g in payload["geos"]]
    latest = years[-1]

    bi = payload["bridge"]["names"].index
    rev = payload["bridge"]["series"][NATIONAL][latest][bi("revenue")]
    exp = payload["bridge"]["series"][NATIONAL][latest][bi("expenditure")]
    pop = payload["population"][NATIONAL][latest]

    # Consolidated Canadian general government revenue is on the order of a
    # trillion dollars a year; population is in the low tens of millions.
    if not (700_000 < rev < 2_000_000):
        raise RuntimeError(f"Canada {latest} revenue of ${rev}M is outside a sane range")
    if not (700_000 < exp < 2_000_000):
        raise RuntimeError(f"Canada {latest} expenditure of ${exp}M is outside a sane range")
    if not (30_000_000 < pop < 50_000_000):
        raise RuntimeError(f"Canada {latest} population of {pop} is outside a sane range")

    # Both ledger halves must be present nationally, and every province must
    # carry the spending comparison, or the page renders an empty panel.
    if not any(payload["revenue"]["series"][NATIONAL][latest]):
        raise RuntimeError(f"no national revenue data for {latest}")
    if not any(payload["spending"]["national"][NATIONAL][latest]):
        raise RuntimeError(f"no national spending data for {latest}")
    for g in geos:
        if not any(payload["spending"]["provincial"][g][latest]):
            raise RuntimeError(f"no provincial spending data for {g} in {latest}")

    # The revenue tree must add up to the published revenue line. This is the
    # check that catches a mis-joined category: table 36-10-0450 reuses the
    # labels "Capital transfers" and "From households" on both sides of the
    # ledger, and joining on the label instead of the member id pairs a revenue
    # row with an expenditure value -- which reads as a plausible number, not an
    # error. Every year should reconcile to within a rounding residual.
    for year in years:
        roots = sum(
            v for v, p in zip(payload["revenue"]["series"][NATIONAL][year],
                              payload["revenue"]["parents"]) if p == -1 and v
        )
        published = payload["bridge"]["series"][NATIONAL][year][bi("revenue")]
        drift = abs(roots - published) / published
        if drift > 0.005:
            raise RuntimeError(
                f"{year}: revenue categories sum to ${roots}M but the published "
                f"total is ${published}M ({drift:.2%} apart) -- check the join"
            )

    # The ledger's headline claim is that the function totals fall short of
    # total expenditure by roughly the excluded capital. If that stops being
    # true the page's central explanation is wrong, so check it here.
    fn_total = sum(
        v for v, p in zip(payload["spending"]["national"][NATIONAL][latest],
                          payload["spending"]["parents"]) if p == -1 and v
    )
    if not (0.75 < fn_total / exp < 1.0):
        raise RuntimeError(
            f"function total ${fn_total}M is {fn_total / exp:.1%} of expenditure "
            f"${exp}M -- outside the expected shortfall, re-check the exclusions"
        )

    log.info(
        "validated: Canada %s revenue $%.0fB, expenditure $%.0fB, functions $%.0fB "
        "(%.0f%% of expenditure), population %.1fM, $%s revenue per person",
        latest, rev / 1000, exp / 1000, fn_total / 1000, 100 * fn_total / exp,
        pop / 1e6, f"{round(rev * 1e6 / pop):,}",
    )

    # ---- the distributional layer ------------------------------------------
    dist = payload["distribution"]
    dist_geo_names = [g["name"] for g in dist["geos"]]

    # Every cell is rounded before publication -- counts to the nearest 10, money
    # to the nearest $1M once converted -- so a band sum never lands exactly on
    # the published total. Across 19 bands that rounding is bounded, and on a
    # base as small as Nunavut's it is worth more than 1% on its own. The test is
    # therefore a percentage OR that absolute rounding bound, whichever is looser.
    n_bands = len(dist["bands"])
    floors = {"filers": 5 * n_bands, "income": n_bands, "tax": n_bands}

    for geo in dist_geo_names:
        for year in dist["series"][geo]:
            d = dist["series"][geo][year]
            for key in ("filers", "income", "tax"):
                banded, published = sum(d[key]), d["total"][key]
                if not published:
                    raise RuntimeError(f"CRA {year} {geo}: published total for {key} is zero")
                gap = abs(banded - published)
                if gap > max(0.01 * published, floors[key]):
                    raise RuntimeError(
                        f"CRA {year} {geo}: {key} bands sum to {banded:,} but the "
                        f"published total is {published:,} (off by {gap:,}, "
                        f"{gap / published:.2%}) -- check the parse"
                    )

    # The provinces are separate files, so their agreeing with the all-Canada
    # file is real evidence the right column was read from each of 91 downloads.
    # They will not match exactly: the national table also counts non-residents
    # and filers with no province of residence.
    provinces = [g for g in dist_geo_names if g != NATIONAL]
    for year in dist["years"]:
        have = [g for g in provinces if year in dist["series"][g]]
        if len(have) < len(provinces):
            continue                    # an incomplete year cannot be summed
        summed = sum(dist["series"][g][year]["total"]["filers"] for g in have)
        national = dist["series"][NATIONAL][year]["total"]["filers"]
        gap = (national - summed) / national
        if not (-0.005 < gap < 0.02):
            raise RuntimeError(
                f"CRA {year}: the {len(have)} provincial files sum to {summed:,} "
                f"filers against {national:,} nationally ({gap:+.2%}) -- outside "
                f"the non-resident residual, so a file is mismatched"
            )
        log.info("CRA %s: %s provincial files sum to %.2f%% of the national filer "
                 "count (the rest are non-residents)", year, len(have),
                 100 * summed / national)

    flagged = [g["name"] for g in dist["geos"] if g.get("selfAdmin")]
    if flagged:
        log.info("provincial income tax is collected outside the CRA in %s -- "
                 "excluded from the cross-province rate comparison",
                 ", ".join(flagged))

    newest = dist["years"][-1]
    d = dist["series"][NATIONAL][newest]
    filers, income, tax = d["total"]["filers"], d["total"]["income"], d["total"]["tax"]
    if not (20e6 < filers < 40e6):
        raise RuntimeError(f"CRA {newest}: {filers:,} filers is outside a sane range")
    if not (0.05 < tax / income < 0.35):
        raise RuntimeError(
            f"CRA {newest}: overall effective rate of {tax / income:.1%} is implausible")

    top_share = 100 * d["tax"][-1] / tax
    top_filers = 100 * d["filers"][-1] / filers
    log.info(
        "distribution: %s tax year -- %.1fM filers, $%.0fB income tax, %.1f%% "
        "effective rate; the top band is %.1f%% of filers and %.1f%% of the tax",
        newest, filers / 1e6, tax / 1000, 100 * tax / income, top_filers, top_share,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true",
                        help="re-download the source tables instead of using the cache")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    payload = build(refresh=args.refresh)
    validate(payload)
    write_data_js(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
