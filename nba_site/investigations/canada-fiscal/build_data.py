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
import sys
import time
import urllib.error
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

def _http(url: str, *, data: bytes | None = None, timeout: int = 120) -> bytes:
    """GET/POST with a timeout and a bounded retry on transient failures."""
    headers = {"User-Agent": "canada-fiscal-ledger/1.0 (+data_explorer)"}
    if data is not None:
        headers["Content-Type"] = "application/json"

    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            ],
            "caveats": [
                "Consolidated figures: transfers between governments are already "
                "netted out, so federal, provincial and local cannot be added together.",
                "The function totals exclude capital acquisition and consumption of "
                "fixed capital, which is why they fall short of total expenditure.",
                "CPP and QPP are outside the consolidated general government here.",
                "Federal Indigenous programs were reclassified into Housing and "
                "community amenities in 2023, breaking that series.",
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
