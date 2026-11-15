"""Fetch the NBA's official daily injury report PDFs and parse them into one CSV.

Source: https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_<slot>.pdf
Output: injuries/data/injury_reports.csv and injuries/data/injury_reports_coverage.csv

Measured facts this module relies on (2026-11-05):
  * HTTP 403 (a ~250 byte body) means "no report for that date and slot", not an
    auth failure. Any other non-200 is retried if transient and raised otherwise.
  * Slot names changed around 2025-12-22: older files are ``_05PM`` (header
    "05:30 PM"), newer ones are ``_05_30PM`` / ``_05_00PM`` / ``_04_30PM``.
  * The PDF layout changed several times (see the parsing section). nbainjuries
    was tried first and rejected: it drives tabula-py and needs a Java runtime,
    which this machine does not have. pdfplumber is pure Python.

Nothing here runs on import. Run: python injury_reports.py [--start D --end D]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import re
import sys
import time
from pathlib import Path

import pdfplumber
import requests

log = logging.getLogger("injury_reports")

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / ".cache" / "reports"
PROBE_CACHE = HERE / ".cache" / "probe_403.json"
DATA_DIR = HERE / "data"
OUT_CSV = DATA_DIR / "injury_reports.csv"
COVERAGE_CSV = DATA_DIR / "injury_reports_coverage.csv"

BASE_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{slot}.pdf"
# An honest client string: the fetch is a one-off research pull, throttled, and
# never scheduled (the legal review of 2026-11-05 turns RED if it is).
USER_AGENT = "data_explorer-injuries/1.0 (+https://github.com/ericbackman/data_explorer; research, manual runs only)"
START_DATE = dt.date(2018, 10, 16)
END_DATE = dt.date(2026, 11, 4)
REQUEST_TIMEOUT_S = 30
MAX_ATTEMPTS = 5
RETRY_STATUS = {429, 500, 502, 503, 504}
MIN_REQUEST_GAP_S = 0.5  # about 2 requests per second
NO_REPORT_STATUS = 403

OLD_SLOTS = ["05PM", "01PM", "04PM", "06PM"]
NEW_SLOTS = ["05_30PM", "05_00PM", "04_30PM", "05PM", "01PM"]
SLOT_SWITCH_START = dt.date(2025, 12, 15)  # both families probed from here ...
SLOT_SWITCH_END = dt.date(2025, 12, 24)  # ... until here; new family only after

OUT_FIELDS = [
    "report_date", "slot", "game_date", "game_time", "matchup", "team",
    "player", "status", "reason",
]
COVERAGE_FIELDS = [
    "season", "days_probed", "days_with_report", "rows_parsed",
    "first_report_date", "last_report_date", "parse_failures", "failed_dates",
]

VALID_STATUS = {"Out", "Available", "Questionable", "Doubtful", "Probable"}
# Team-level rows with no player; they carry a team but yield no output row.
TEAM_MARKERS = {"NOT YET SUBMITTED", "ALL PLAYERS AVAILABLE"}

# Team name -> accepted matchup abbreviations (the NBA has used both spellings).
TEAM_ABBR = {
    "Atlanta Hawks": {"ATL"}, "Boston Celtics": {"BOS"},
    "Brooklyn Nets": {"BKN", "BRK"}, "Charlotte Hornets": {"CHA", "CHO"},
    "Chicago Bulls": {"CHI"}, "Cleveland Cavaliers": {"CLE"},
    "Dallas Mavericks": {"DAL"}, "Denver Nuggets": {"DEN"},
    "Detroit Pistons": {"DET"}, "Golden State Warriors": {"GSW", "GS"},
    "Houston Rockets": {"HOU"}, "Indiana Pacers": {"IND"},
    "LA Clippers": {"LAC"}, "Los Angeles Clippers": {"LAC"},
    "Los Angeles Lakers": {"LAL"}, "Memphis Grizzlies": {"MEM"},
    "Miami Heat": {"MIA"}, "Milwaukee Bucks": {"MIL"},
    "Minnesota Timberwolves": {"MIN"}, "New Orleans Pelicans": {"NOP", "NO"},
    "New York Knicks": {"NYK", "NY"}, "Oklahoma City Thunder": {"OKC"},
    "Orlando Magic": {"ORL"}, "Philadelphia 76ers": {"PHI"},
    "Phoenix Suns": {"PHX", "PHO"}, "Portland Trail Blazers": {"POR"},
    "Sacramento Kings": {"SAC"}, "San Antonio Spurs": {"SAS", "SA"},
    "Toronto Raptors": {"TOR"}, "Utah Jazz": {"UTA", "UTH"},
    "Washington Wizards": {"WAS"},
}

FRAGMENT_MAX_DIST = 20.0  # pt: a wrapped reason line sits within this of its player line
STATUS_PAIR_DIST = 4.0    # pt: status cell must sit this close to its player cell
CELL_GAP = 2.5            # pt: words closer than this vertically are one cell
TEAM_WRAP_GAP = 10.0
X_SLACK = 3.0
FOOTER_RE = re.compile(r"^Page\d*$|^Page$")


class ParseError(Exception):
    """A PDF could not be parsed into rows that pass validation."""


# ---------------------------------------------------------------- dates, slots

def iter_dates(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def slots_for(day: dt.date) -> list[str]:
    """Slot names to probe for a date, in order."""
    if day < SLOT_SWITCH_START:
        return list(OLD_SLOTS)
    if day < SLOT_SWITCH_END:
        return NEW_SLOTS + [s for s in OLD_SLOTS if s not in NEW_SLOTS]
    return list(NEW_SLOTS)


def season_of(day: dt.date) -> str:
    """Season label; a season starts 1 October (July to September belong to the one just ended)."""
    start = day.year if day.month >= 10 else day.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def report_path(day: dt.date, slot: str) -> Path:
    return CACHE_DIR / f"Injury-Report_{day.isoformat()}_{slot}.pdf"


# ---------------------------------------------------------------------- fetch

class Fetcher:
    """Downloads report PDFs into a restartable on-disk cache."""

    def __init__(self, session: requests.Session | None = None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._sleep = sleep
        self._last_request = 0.0
        self.misses: dict[str, int] = self._load_misses()
        self.network_calls = 0

    @staticmethod
    def _load_misses() -> dict[str, int]:
        if not PROBE_CACHE.exists():
            return {}
        return json.loads(PROBE_CACHE.read_text(encoding="utf-8"))

    def save_misses(self) -> None:
        PROBE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROBE_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.misses, sort_keys=True), encoding="utf-8")
        tmp.replace(PROBE_CACHE)

    def _throttle(self) -> None:
        wait = MIN_REQUEST_GAP_S - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def _get(self, url: str) -> requests.Response:
        last_err: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._throttle()
            self.network_calls += 1
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT_S)
            except requests.RequestException as exc:
                last_err = exc
                log.warning("attempt %d/%d failed for %s: %s", attempt, MAX_ATTEMPTS, url, exc)
            else:
                if resp.status_code not in RETRY_STATUS:
                    return resp
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                log.warning("attempt %d/%d got HTTP %d for %s", attempt, MAX_ATTEMPTS,
                            resp.status_code, url)
            self._sleep(min(60, 2 ** attempt))
        raise RuntimeError(f"giving up on {url} after {MAX_ATTEMPTS} attempts: {last_err}")

    def fetch_date(self, day: dt.date) -> str | None:
        """Return the slot that has a cached/downloaded report for `day`, or None."""
        for slot in slots_for(day):
            path = report_path(day, slot)
            if path.exists() and path.stat().st_size > 0:
                return slot
            key = f"{day.isoformat()}_{slot}"
            if key in self.misses:
                continue
            resp = self._get(BASE_URL.format(date=day.isoformat(), slot=slot))
            if resp.status_code == NO_REPORT_STATUS:
                self.misses[key] = NO_REPORT_STATUS
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"unexpected HTTP {resp.status_code} for {key}")
            if not resp.content.startswith(b"%PDF"):
                raise RuntimeError(f"HTTP 200 but not a PDF for {key} ({len(resp.content)} bytes)")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(resp.content)
            tmp.replace(path)
            return slot
        return None


# ------------------------------------------------------------------- parsing
# Layouts seen: (a) 2018-19 with separate Category and Reason columns and a
# Previous Status column, (b) 2019-20 with one combined Reason column, with Reason
# before or after Current Status, (c) 2020-21 onward with Current Status then
# Reason. Column starts are read from each page's header row, so order is free.

HEADER_WORDS = {
    ("Game", "Date"): "date", ("Game", "Time"): "time", ("Player", "Name"): "player",
    ("Current", "Status"): "status", ("Previous", "Status"): "prev",
    ("Previous", "Reason"): "prev",
}
HEADER_SINGLE = {"Matchup": "matchup", "Team": "team", "Reason": "reason", "Category": "category"}


def header_columns(words: list[dict]) -> list[tuple[str, float]]:
    """Column (name, x0) pairs, left to right, from the page's header row."""
    anchor = [w for w in words if w["text"] == "Matchup"]
    if not anchor:
        raise ParseError("no header row (no 'Matchup' word on page)")
    top = anchor[0]["top"]
    row = sorted((w for w in words if abs(w["top"] - top) <= 3), key=lambda w: w["x0"])
    cols: list[tuple[str, float]] = []
    i = 0
    while i < len(row):
        pair = (row[i]["text"], row[i + 1]["text"]) if i + 1 < len(row) else None
        if pair in HEADER_WORDS:
            cols.append((HEADER_WORDS[pair], row[i]["x0"]))
            i += 2
        elif row[i]["text"] in HEADER_SINGLE:
            cols.append((HEADER_SINGLE[row[i]["text"]], row[i]["x0"]))
            i += 1
        else:
            raise ParseError(f"unrecognised header word {row[i]['text']!r}")
    names = {n for n, _ in cols}
    need = {"date", "time", "matchup", "team", "player", "status", "reason"}
    if not need <= names:
        raise ParseError(f"header missing columns {sorted(need - names)}; saw {sorted(names)}")
    return cols


def column_of(cols: list[tuple[str, float]], x0: float) -> str | None:
    found = None
    for name, start in cols:
        if start <= x0 + X_SLACK:
            found = name
    return found


def _cells(words: list[dict], gap: float = CELL_GAP) -> list[dict]:
    """Cluster one column's words into vertical cells: {top, text}."""
    out: list[dict] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(w["top"] - out[-1]["top"]) <= gap:
            out[-1]["text"] += " " + w["text"]
        else:
            out.append({"top": w["top"], "text": w["text"]})
    return out


def parse_page(words: list[dict], cols: list[tuple[str, float]] | None = None) -> list[dict]:
    """Parse one page's words into raw rows (context fields None when blank).

    Raw row: game_date, game_time, matchup, team (str or None), player, status,
    reason, marker. marker is False for a player row, True for a team-level
    marker row ("NOT YET SUBMITTED"), None for a context-only row and
    "continuation" for reason text that wrapped onto the next page.
    """
    header_top = next((w["top"] for w in words if w["text"] == "Matchup"), None)
    if header_top is not None:
        cols = header_columns(words)
    elif cols is None:
        raise ParseError("no header row on the first page")
    else:
        # Later pages of the 2022+ layout repeat only the title line, not the header.
        header_top = next((w["top"] for w in words if w["text"] == "Report:"), None)
        if header_top is None:
            raise ParseError("page has neither a header row nor a title line")
    footer_top = [w["top"] for w in words if FOOTER_RE.match(w["text"])]
    body = [w for w in words if w["top"] > header_top + 3
            and not any(abs(w["top"] - t) <= 3 for t in footer_top)]
    by_col: dict[str, list[dict]] = {}
    for w in body:
        c = column_of(cols, w["x0"])
        if c is None or c == "prev":
            continue
        by_col.setdefault(c, []).append(w)
    # A long team name wraps onto a second line about 8 pt below the first.
    cell = {c: _cells(ws, TEAM_WRAP_GAP if c == "team" else CELL_GAP) for c, ws in by_col.items()}

    statuses = cell.get("status", [])
    anchors: list[dict] = []
    fragments_player: list[dict] = []
    for p in cell.get("player", []):
        st = min(statuses, key=lambda s: abs(s["top"] - p["top"]), default=None)
        if st is not None and abs(st["top"] - p["top"]) <= STATUS_PAIR_DIST:
            if st["text"] not in VALID_STATUS:
                raise ParseError(f"unknown status {st['text']!r} for {p['text']!r}")
            anchors.append({"top": p["top"], "player": p["text"], "status": st["text"],
                            "cat": [], "reason": []})
        else:
            fragments_player.append(p)
    anchors.sort(key=lambda a: a["top"])
    for st in statuses:
        if not any(abs(st["top"] - a["top"]) <= STATUS_PAIR_DIST for a in anchors):
            raise ParseError(f"status {st['text']!r} with no player at top {st['top']:.0f}")

    def nearest(top: float) -> dict | None:
        if not anchors:
            return None
        best = min(anchors, key=lambda a: abs(a["top"] - top))
        return best if abs(best["top"] - top) <= FRAGMENT_MAX_DIST else None

    for f in fragments_player:
        if f["text"].strip() == ",":
            continue  # empty placeholder row of a "Non-NBA Team" game
        a = nearest(f["top"])
        if a is None:
            raise ParseError(f"orphan player-column text {f['text']!r}")
        a["player"] += " " + f["text"]

    markers: list[dict] = []
    continuations: list[str] = []
    first_anchor_top = anchors[0]["top"] if anchors else float("inf")
    for colname in ("category", "reason"):
        for frag in cell.get(colname, []):
            text = frag["text"].strip()
            if text.upper() in TEAM_MARKERS:
                markers.append({"top": frag["top"], "marker": text.upper()})
                continue
            if text in ("-", ","):
                continue  # placeholder cells of "Non-NBA Team" games
            a = nearest(frag["top"])
            if a is not None:
                a["cat" if colname == "category" else "reason"].append((frag["top"], frag["text"]))
            elif frag["top"] < first_anchor_top and colname == "reason":
                # The tail of a reason whose player line is the last row of the previous page.
                continuations.append(frag["text"])
            else:
                raise ParseError(f"orphan {colname} text {frag['text']!r} at top {frag['top']:.0f}")

    events: list[tuple[float, int, dict]] = []
    for field in ("date", "time", "matchup", "team"):
        for c in cell.get(field, []):
            events.append((c["top"], 0, {"ctx": field, "text": c["text"]}))
    for a in anchors:
        events.append((a["top"], 1, {"anchor": a}))
    for m in markers:
        events.append((m["top"], 1, {"marker": m["marker"]}))
    events.sort(key=lambda e: (e[0], e[1]))

    rows: list[dict] = []
    if continuations:
        rows.append({"game_date": None, "game_time": None, "matchup": None, "team": None,
                     "player": None, "status": None, "reason": " ".join(continuations),
                     "marker": "continuation"})
    pending: dict[str, str] = {}
    for _top, _order, ev in events:
        if "ctx" in ev:
            pending[ev["ctx"]] = ev["text"]
            continue
        raw = {"game_date": pending.get("date"), "game_time": pending.get("time"),
               "matchup": pending.get("matchup"), "team": pending.get("team")}
        pending = {}
        if "marker" in ev:
            rows.append({**raw, "player": None, "status": None, "reason": ev["marker"],
                         "marker": True})
            continue
        a = ev["anchor"]
        reason = " ".join(t for _, t in sorted(a["reason"]))
        cat = " ".join(t for _, t in sorted(a["cat"]))
        rows.append({**raw, "player": a["player"], "status": a["status"],
                     "reason": join_category_reason(cat, reason), "marker": False})
    if pending:
        # Context cells after the page's last row carry into the next page.
        rows.append({"game_date": pending.get("date"), "game_time": pending.get("time"),
                     "matchup": pending.get("matchup"), "team": pending.get("team"),
                     "player": None, "status": None, "reason": None, "marker": None})
    return rows


def join_category_reason(category: str, reason: str) -> str:
    """Old layout has Category and Reason columns; merge as 'Category - Reason'."""
    category, reason = category.strip(), reason.strip()
    if not category:
        return reason
    if reason in ("", "-"):
        return category
    return f"{category} - {reason}"


def carry_forward(rows: list[dict]) -> list[dict]:
    """Fill blank game_date/game_time/matchup/team from the row above.

    Pure function. Context-only rows (marker is None) update the state and are
    dropped; team-marker rows update the state and are kept (marker=True) so the
    caller can drop them. Raises ParseError when a player row has nothing to
    inherit for a field.
    """
    state: dict[str, str | None] = {"game_date": None, "game_time": None, "matchup": None, "team": None}
    out: list[dict] = []
    for r in rows:
        if r.get("marker") == "continuation":
            if not out or out[-1]["marker"] is not False:
                raise ParseError(f"continuation text {r['reason']!r} with no player row above it")
            out[-1] = {**out[-1], "reason": f"{out[-1]['reason']} {r['reason']}".strip()}
            continue
        for k in state:
            if r.get(k):
                state[k] = r[k]
        if r.get("marker") is None:
            continue
        if r["marker"] is False:
            missing = [k for k, v in state.items() if not v]
            if missing:
                raise ParseError(f"no value to carry forward for {missing} at player {r['player']!r}")
        out.append({**r, **state})
    return out


def parse_game_time(raw: str) -> str:
    """'07:30 (ET)' -> '19:30'. Hours 1-11 are afternoon/evening ET (no NBA game starts before noon)."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*\(ET\)", raw.strip())
    if not m:
        raise ParseError(f"unexpected game time {raw!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if h < 12:
        h += 12
    return f"{h:02d}:{mi:02d}"


def parse_game_date(raw: str) -> str:
    try:
        return dt.datetime.strptime(raw.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError as exc:
        raise ParseError(f"unexpected game date {raw!r}") from exc


def check_team_matchup(team: str, matchup: str) -> None:
    abbrs = TEAM_ABBR.get(team)
    if abbrs is None:
        raise ParseError(f"unknown team {team!r}")
    codes = matchup.split("@")
    if len(codes) != 2 or not (abbrs & set(codes)):
        raise ParseError(f"team {team!r} not in matchup {matchup!r} (carry-forward error?)")


def finish_rows(raw_rows: list[dict], report_date: dt.date, slot: str) -> list[dict]:
    """carry_forward, validate, convert to output rows (team markers dropped)."""
    out = []
    for r in carry_forward(raw_rows):
        if r["marker"]:
            continue  # team-level marker (NOT YET SUBMITTED, incl. "Non-NBA Team" games)
        check_team_matchup(r["team"], r["matchup"])
        out.append({
            "report_date": report_date.isoformat(), "slot": slot,
            "game_date": parse_game_date(r["game_date"]),
            "game_time": parse_game_time(r["game_time"]),
            "matchup": r["matchup"], "team": r["team"],
            "player": r["player"], "status": r["status"], "reason": r["reason"],
        })
    return out


def parse_pdf(path: Path, report_date: dt.date, slot: str) -> list[dict]:
    try:
        with pdfplumber.open(path) as pdf:
            raw: list[dict] = []
            cols = None
            for i, page in enumerate(pdf.pages):
                if i == 0:
                    text = page.extract_text() or ""
                    m = re.search(r"Injury\s*Report:\s*(\d\d/\d\d/\d\d)", text)
                    if not m:
                        raise ParseError("no 'Injury Report: MM/DD/YY' title on page 1")
                    hdr = dt.datetime.strptime(m.group(1), "%m/%d/%y").date()
                    if hdr != report_date:
                        raise ParseError(f"title date {hdr} != file date {report_date}")
                words = page.extract_words(x_tolerance=1.5)
                if any(w["text"] == "Matchup" for w in words):
                    cols = header_columns(words)
                raw.extend(parse_page(words, cols))
        return finish_rows(raw, report_date, slot)
    except ParseError:
        raise
    except Exception as exc:  # pdfminer raises many types; wrap so the caller sees the file
        raise ParseError(f"{type(exc).__name__}: {exc}") from exc


# ----------------------------------------------------------------------- main

def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def build_coverage(probed: dict[dt.date, str | None], rows_by_date: dict[dt.date, int],
                   failures: dict[dt.date, str]) -> list[dict]:
    seasons: dict[str, dict] = {}
    for day, slot in sorted(probed.items()):
        s = seasons.setdefault(season_of(day), {
            "season": season_of(day), "days_probed": 0, "days_with_report": 0,
            "rows_parsed": 0, "first_report_date": "", "last_report_date": "",
            "parse_failures": 0, "failed_dates": []})
        s["days_probed"] += 1
        if slot is not None:
            s["days_with_report"] += 1
            s["rows_parsed"] += rows_by_date.get(day, 0)
            s["first_report_date"] = s["first_report_date"] or day.isoformat()
            s["last_report_date"] = day.isoformat()
        if day in failures:
            s["parse_failures"] += 1
            s["failed_dates"].append(day.isoformat())
    out = []
    for s in seasons.values():
        s["failed_dates"] = ";".join(s["failed_dates"])
        out.append(s)
    return out


def run(start: dt.date, end: dt.date) -> int:
    fetcher = Fetcher()
    probed: dict[dt.date, str | None] = {}
    last_month = None
    try:
        for day in iter_dates(start, end):
            probed[day] = fetcher.fetch_date(day)
            month = (day.year, day.month)
            if month != last_month:
                if last_month is not None:
                    fetcher.save_misses()
                log.info("fetching %04d-%02d (network calls so far: %d)", *month, fetcher.network_calls)
                last_month = month
    finally:
        fetcher.save_misses()

    all_rows: list[dict] = []
    rows_by_date: dict[dt.date, int] = {}
    failures: dict[dt.date, str] = {}
    for day, slot in sorted(probed.items()):
        if slot is None:
            continue
        try:
            rows = parse_pdf(report_path(day, slot), day, slot)
        except ParseError as exc:
            log.error("PARSE FAILURE %s %s: %s", day, slot, exc)
            failures[day] = str(exc)
            continue
        rows_by_date[day] = len(rows)
        all_rows.extend(rows)
        if day.day == 1:
            log.info("parsed through %s (%d rows)", day, len(all_rows))

    coverage = build_coverage(probed, rows_by_date, failures)
    write_csv(COVERAGE_CSV, COVERAGE_FIELDS, coverage)
    write_csv(OUT_CSV, OUT_FIELDS, all_rows)
    log.info("wrote %d rows to %s and %d seasons to %s", len(all_rows), OUT_CSV,
             len(coverage), COVERAGE_CSV)
    if failures:
        log.error("%d PDFs failed to parse (listed in %s)", len(failures), COVERAGE_CSV)
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", type=dt.date.fromisoformat, default=START_DATE)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=END_DATE)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main())
