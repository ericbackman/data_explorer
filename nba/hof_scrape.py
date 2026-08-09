"""Build the local `hall_of_fame` table from Wikipedia's Naismith inductee list.

WHY THIS EXISTS
---------------
stats.nba.com's PlayerAwards endpoint — the source behind `player_awards` — stops
carrying "Hall of Fame Inductee" after the **2018** class. Verified live against
the endpoint: Ray Allen (2018), Tracy McGrady (2017) and Dino Rada (2018) all
return an HOF row, while Vlade Divac (2019), Kobe Bryant (2020), Tim Duncan
(2020), Paul Pierce (2021), Dirk Nowitzki (2023), Vince Carter (2024) and Carmelo
Anthony (2025) return none. It is an upstream gap, not a stale local mirror: live
row counts match the DB exactly. Re-running `nba.awards_scrape` cannot fix it.

So the Hall of Fame gets its own HOF-specific source, the same way MLB's does,
and consumers UNION it into their awards view.

HOW IT VALIDATES
----------------
The scrape is cross-checked against the 102 HOF rows nba_api already provides for
the <=2018 classes (`--validate`, on by default). Agreeing with an independent
source on the overlap is what earns trust for the 2019+ rows only this scraper
has. Any induction-year disagreement is reported loudly and fails the run.

Usage
-----
  python -m nba.hof_scrape                # fetch, resolve, load, validate
  python -m nba.hof_scrape --dry-run      # parse + resolve + report, write nothing
  python -m nba.hof_scrape --show-unmatched
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import re
import sqlite3
import time
import unicodedata

import lxml.html
import requests

from nba import db

log = logging.getLogger(__name__)

PKG_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"
DB_PATH = DATA_DIR / "nba.db"

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "List of players in the Naismith Memorial Basketball Hall of Fame"
# Wikimedia asks automated clients to identify themselves with a contact address.
USER_AGENT = "data_explorer/1.0 (https://github.com/ericbackman/data_explorer)"

DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 4
BACKOFF_BASE_S = 1.5

# Letters NFKD cannot strip to ASCII (stroke/ligature forms carry no combining
# mark), with the transliteration the NBA's own name spellings use:
# "Dino Rada" is spelled "Dino Radja" upstream, so d-with-stroke -> "dj".
_TRANSLIT = {
    "đ": "dj", "Đ": "DJ",   # d/D with stroke (Rada)
    "ø": "o", "Ø": "O",     # o/O with stroke
    "ł": "l", "Ł": "L",     # l/L with stroke
    "ß": "ss", "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE", "ð": "d", "þ": "th",
}

# Same human, different spelling between Wikipedia and nba_api's `players` table.
# Keep this SMALL and only for verified same-person cases — never to force two
# different people together (see NOT_ALIASES below).
_NAME_ALIASES = {
    "louie dampier": "lou dampier",     # nba_api lists the ABA guard as "Lou"
}

# Deliberately NOT aliased, though the names look close:
#   "Neil Johnston" (player_id 77169; 543 games, 1951-59, 10,381 pts) is the real
#   1990 inductee. "Nate Johnston" (77170; 24 games, 1989-90, 59 pts, drafted
#   1988 #59) is a different person — and nba_api hangs its 1990 HOF row on
#   *Nate*. That upstream row is wrong; this scraper resolves to Neil on purpose.

# Same normalized name, two real NBA careers, both ended before the induction —
# so neither the name index nor the career-window rule can separate them. Each
# entry is a hand-verified (induction year, normalized name) -> player_id.
_AMBIGUITY_OVERRIDES = {
    # 2019 inductee is the 76ers/Nuggets forward (drafted 1974 #5, 899 games),
    # not the 2006 second-rounder of the same name (player_id 200784, 91 games).
    (2019, "bobbyjones"): 77193,
}


class HOFScrapeError(RuntimeError):
    """Raised when the page cannot be fetched or parsed into usable rows."""


# ── pure helpers ─────────────────────────────────────────────────────────────
def normalize_name(name: str) -> str:
    """A name -> a comparison key that survives diacritics, punctuation and spacing.

    Spaces are dropped entirely so nba_api's "Jojo White" matches Wikipedia's
    "Jo Jo White". Generational suffixes are deliberately KEPT: stripping them
    collapses Patrick Ewing into Patrick Ewing Jr. (and Gary Payton into Gary
    Payton II), manufacturing ambiguity where the source had none.
    """
    s = "".join(_TRANSLIT.get(c, c) for c in name)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)          # drop "(basketball)" disambiguators
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = _NAME_ALIASES.get(s, s)
    return re.sub(r"[^a-z0-9]", "", s)


def parse_inductees(html: str) -> list[dict]:
    """Rendered "Players" section HTML -> [{inducted_year, name}], newest last.

    Parses the RENDERED table rather than the wikitext on purpose: the wikitext
    rows use at least four different cell-delimiter and template styles (the 2025
    and 2026 classes use single pipes, Yao Ming has an empty sortname field), and
    a wikitext parser silently dropped 12 rows including two whole classes. The
    rendered table is uniform, and the hCard <span class="fn"> gives the display
    name directly.
    """
    doc = lxml.html.fromstring(html)
    rows: list[dict] = []
    for tr in doc.xpath("//table[contains(@class,'wikitable')]//tr"):
        cells = tr.xpath("./td")
        if len(cells) < 2:
            continue                                   # header / layout row
        year_text = (cells[0].text_content() or "").strip()
        if not re.fullmatch(r"\d{4}", year_text):
            continue
        name_cell = cells[1]
        fn = name_cell.xpath(".//span[@class='fn']")
        name = (fn[0] if fn else name_cell).text_content().strip()
        # The flagicon's alt text ("United States") can lead the cell when the
        # hCard span is absent; keep only the trailing personal name.
        if not fn:
            name = name.split("\n")[-1].strip()
        if not name:
            continue
        rows.append({"inducted_year": int(year_text), "name": name})
    if not rows:
        raise HOFScrapeError(
            "parsed 0 inductees — the Wikipedia table markup likely changed; "
            "inspect the page before trusting any load"
        )
    return rows


def build_name_index(players: list[tuple[int, str]]) -> dict[str, list[int]]:
    """[(player_id, player_name)] -> {normalized name: [player_id, ...]}."""
    idx: dict[str, list[int]] = {}
    for player_id, player_name in players:
        if player_name:
            idx.setdefault(normalize_name(player_name), []).append(player_id)
    return idx


def resolve_inductees(
    inductees: list[dict],
    name_index: dict[str, list[int]],
    last_season: dict[int, int],
    overrides: dict[tuple[int, str], int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Attach a player_id to each inductee. Returns (rows, unresolved).

    Every inductee becomes a row; `player_id` is None when no NBA player matches
    (WNBA inductees, Globetrotters, pre-NBA college stars) or when the match is
    ambiguous. Ambiguity is never guessed away: two same-name candidates are
    separated only by the career-window rule (an inductee is fully retired, so
    his last season precedes his induction) or by an explicit override.
    """
    # `is None`, not `or`: an explicitly empty dict means "apply no overrides",
    # and must not fall back to the shipped ones.
    overrides = _AMBIGUITY_OVERRIDES if overrides is None else overrides
    rows, unresolved = [], []
    for ind in inductees:
        key = normalize_name(ind["name"])
        year = ind["inducted_year"]
        candidates = sorted(set(name_index.get(key, [])))
        player_id, reason = None, ""

        if (year, key) in overrides:
            player_id = overrides[(year, key)]
        elif len(candidates) == 1:
            player_id = candidates[0]
        elif len(candidates) > 1:
            eligible = [c for c in candidates if last_season.get(c, 9999) < year]
            if len(eligible) == 1:
                player_id = eligible[0]
            else:
                reason = f"ambiguous: {candidates} (career-eligible {eligible})"
        else:
            reason = "no NBA player of this name"

        rows.append({"inductee_name": ind["name"], "inducted_year": year,
                     "player_id": player_id})
        if player_id is None:
            unresolved.append({**ind, "reason": reason})
    return rows, unresolved


def validate_against_awards(
    rows: list[dict], known: dict[int, str],
) -> tuple[int, list[str]]:
    """Cross-check resolved rows against nba_api's own HOF rows (the <=2018 classes).

    Returns (agreements, problems). A problem is an induction-year disagreement
    on a player both sources know — the signal that this scraper is misreading
    the table. Players nba_api lacks are the whole point and are not problems.
    """
    by_player = {r["player_id"]: r for r in rows if r["player_id"] is not None}
    agreements, problems = 0, []
    for player_id, season in known.items():
        row = by_player.get(player_id)
        if row is None:
            continue
        if str(row["inducted_year"]) == str(season):
            agreements += 1
        else:
            problems.append(
                f"player {player_id} ({row['inductee_name']}): "
                f"nba_api says {season}, Wikipedia says {row['inducted_year']}"
            )
    return agreements, problems


# ── IO ───────────────────────────────────────────────────────────────────────
def _get_json(session: requests.Session, params: dict, timeout_s: int,
              max_retries: int) -> dict:
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(WIKI_API, params=params, timeout=timeout_s)
            resp.raise_for_status()
            payload = resp.json()
            if "error" in payload:
                raise HOFScrapeError(f"MediaWiki error: {payload['error']}")
            return payload
        except (requests.exceptions.RequestException, ValueError) as e:
            last_err = e
            backoff = BACKOFF_BASE_S ** attempt
            log.warning("wiki fetch attempt %d/%d failed: %s — retrying in %.1fs",
                        attempt, max_retries, e, backoff)
            time.sleep(backoff)
    raise HOFScrapeError(f"could not fetch {WIKI_PAGE} after {max_retries} attempts") from last_err


def fetch_players_html(session: requests.Session | None = None,
                       timeout_s: int = DEFAULT_TIMEOUT_S,
                       max_retries: int = DEFAULT_MAX_RETRIES) -> str:
    """Fetch the rendered HTML of the page's "Players" section.

    Resolves the section index by heading name rather than hardcoding it, so a
    new section added above Players doesn't silently shift the scrape onto the
    wrong table.
    """
    own = session is None
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        sections = _get_json(session, {
            "action": "parse", "page": WIKI_PAGE, "prop": "sections",
            "format": "json", "formatversion": 2,
        }, timeout_s, max_retries)["parse"]["sections"]
        index = next((s["index"] for s in sections if s["line"].strip() == "Players"), None)
        if index is None:
            raise HOFScrapeError(
                f"no 'Players' section on {WIKI_PAGE!r} — page structure changed")
        log.info("fetching '%s' section %s", WIKI_PAGE, index)
        return _get_json(session, {
            "action": "parse", "page": WIKI_PAGE, "prop": "text", "section": index,
            "format": "json", "formatversion": 2,
        }, timeout_s, max_retries)["parse"]["text"]
    finally:
        if own:
            session.close()


def read_players(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return list(conn.execute(
        "SELECT player_id, player_name FROM players WHERE player_name IS NOT NULL"))


def read_last_seasons(conn: sqlite3.Connection) -> dict[int, int]:
    """player_id -> last season-start year with a logged game."""
    return {pid: yr for pid, yr in conn.execute(
        "SELECT player_id, MAX(CAST(substr(season,1,4) AS INTEGER)) "
        "FROM player_game GROUP BY player_id") if yr is not None}


def read_known_hof(conn: sqlite3.Connection) -> dict[int, str]:
    """nba_api's own HOF rows — the independent set this scrape is checked against."""
    return {pid: season for pid, season in conn.execute(
        "SELECT person_id, season FROM player_awards "
        "WHERE description = 'Hall of Fame Inductee'")}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build the NBA hall_of_fame table from Wikipedia's Naismith list")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite path")
    ap.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    ap.add_argument("--show-unmatched", action="store_true",
                    help="list every inductee with no player_id")
    ap.add_argument("--skip-validate", action="store_true",
                    help="do not cross-check against nba_api's own HOF rows")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)
    try:
        inductees = parse_inductees(fetch_players_html())
        years = [i["inducted_year"] for i in inductees]
        log.info("parsed %d inductions (%d-%d)", len(inductees), min(years), max(years))

        rows, unresolved = resolve_inductees(
            inductees, build_name_index(read_players(conn)), read_last_seasons(conn))
        matched = len(rows) - len(unresolved)
        log.info("resolved %d/%d to an NBA player_id", matched, len(rows))

        ambiguous = [u for u in unresolved if u["reason"].startswith("ambiguous")]
        for u in ambiguous:
            log.error("UNRESOLVED %s (%d): %s — add an _AMBIGUITY_OVERRIDES entry",
                      u["name"], u["inducted_year"], u["reason"])
        if args.show_unmatched:
            for u in unresolved:
                log.info("  unmatched: %d %s (%s)", u["inducted_year"], u["name"], u["reason"])

        known = read_known_hof(conn)
        if not args.skip_validate:
            agreements, problems = validate_against_awards(rows, known)
            for p in problems:
                log.error("VALIDATION: %s", p)
            if problems:
                raise HOFScrapeError(
                    f"{len(problems)} induction-year disagreement(s) with nba_api — "
                    "not loading; the table markup or the parser is wrong")
            log.info("validation: agrees with nba_api on %d/%d of its own HOF rows",
                     agreements, len(known))

        new = sum(1 for r in rows
                  if r["player_id"] is not None and r["player_id"] not in known)
        log.info("%d resolved inductee(s) nba_api does not have", new)

        if args.dry_run:
            log.info("dry run — nothing written")
            return
        loaded = db.load_hall_of_fame(conn, rows)
        conn.commit()
        log.info("done: hall_of_fame now %d rows (%d with a player_id)",
                 loaded, matched)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
