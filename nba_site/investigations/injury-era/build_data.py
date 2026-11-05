#!/usr/bin/env python3
"""
build_data.py -- Build data.js for the NBA injury-era investigation.

Reads the CSVs that the `injuries/` package writes (games missed since 1946-47,
box-score absence reasons since 1996-97, official injury-report rows since
2018-12, injured-list events from open Pro Sports Transactions mirrors, pace,
minutes and schedule series) and emits one `const INJURY_ERA_DATA = {...}` for
the page to load through a plain <script> tag.

    python build_data.py

Every number on the page is computed here from a file in `injuries/data/`, or
is a research constant listed in RESEARCH with its source URL and grade. The
page never computes a rate itself and never carries a number this file does
not.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

log = logging.getLogger("build_data")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / "injuries" / "data"
OUT = HERE / "data.js"

FIRST_ROTATION_SEASON = "1976-77"  # minutes cover 95% of player-games from here (minutes_by_season.csv)
FIRST_PACE_SEASON = "1985-86"  # turnovers recorded for every team-game from here (pace_by_season.csv)
FULL_ROSTER_LAST_SEASON = "2002-03"  # box scores list the whole roster through this season
NAMED_BODY_PART_LAST_SEASON = "2016-17"  # box scores name the body part through this season
EPISODE_GAP_DAYS = 10  # a player off the report this long starts a new injury episode
SEASON_START_GRACE_DAYS = 14  # a repair or rehab listed this early in a season's reports predates the season
RECOVERY_WORDS = re.compile(r"(?<![a-z])(rehab|rehabilitation|repair|surgery|surgical|recovery|reconditioning)(?![a-z])", re.IGNORECASE)
LOCATION_ORDER = (
    "ankle",
    "foot",
    "achilles",
    "lower_leg",
    "knee",
    "hamstring",
    "quad_thigh",
    "hip_groin",
    "back",
    "torso",
    "neck",
    "head",
    "shoulder",
    "arm_elbow",
    "hand_wrist",
    "leg_unspecified",
    "other",
)
LOCATION_LABELS = {
    "ankle": "Ankle",
    "foot": "Foot and toe",
    "achilles": "Achilles",
    "lower_leg": "Calf and shin",
    "knee": "Knee",
    "hamstring": "Hamstring",
    "quad_thigh": "Quad and thigh",
    "hip_groin": "Hip and groin",
    "back": "Back",
    "torso": "Ribs and core",
    "neck": "Neck",
    "head": "Head and face",
    "shoulder": "Shoulder",
    "arm_elbow": "Arm and elbow",
    "hand_wrist": "Hand and wrist",
    "leg_unspecified": "Leg (unspecified)",
    "other": "Other",
}
BELOW_KNEE = ("ankle", "foot", "achilles", "lower_leg")


def read_csv(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run the injuries/ module that writes it")
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} is empty")
    return rows


def num(value: str, default=None):
    if value is None or value == "":
        return default
    return float(value)


def season_start(season: str) -> int:
    return int(season[:4])


# ----------------------------------------------------------------- games missed
def build_missed(missed_rows: list[dict], minutes_rows: list[dict], schedule_rows: list[dict]) -> list[dict]:
    coverage = {r["season"]: num(r["minutes_coverage"], 0.0) for r in minutes_rows}
    partial = {r["season"]: r["partial"] == "1" for r in schedule_rows}
    out = []
    for r in missed_rows:
        season = r["season"]
        if partial.get(season, False):
            continue
        if season < "1951-52":
            continue
        rot = season >= FIRST_ROTATION_SEASON
        out.append(
            {
                "season": season,
                "start": season_start(season),
                "team_games": int(r["team_games"]),
                "rotation_players": int(r["rotation_players"]) if rot else None,
                "rotation_missed": int(r["rotation_missed"]) if rot else None,
                "per_team_game": round(float(r["rotation_missed_per_team_game"]), 3) if rot else None,
                "share": round(float(r["rotation_missed_share"]), 4) if rot else None,
                "tail": int(r["rotation_tail_missed"]) if rot else None,
                "head": int(r["rotation_head_missed"]) if rot else None,
                "gap": int(r["rotation_gap_missed"]) if rot else None,
                "missed_10plus": int(r["rotation_missed_10plus"]) if rot else None,
                "missed_20plus": int(r["rotation_missed_20plus"]) if rot else None,
                "missed_0": int(r["rotation_missed_0"]) if rot else None,
                "all_per_team_game": round(float(r["all_missed_per_team_game"]), 3),
                "minutes_coverage": round(coverage.get(season, 0.0), 3),
            }
        )
    if not out:
        raise ValueError("no seasons survived the games-missed filter")
    return out


def era_means(series: list[dict], key: str, eras: list[tuple[str, str, str]]) -> list[dict]:
    """Mean of `key` over the seasons in each (label, first, last) era; None-safe."""
    out = []
    for label, first, last in eras:
        vals = [s[key] for s in series if first <= s["season"] <= last and s.get(key) is not None]
        if not vals:
            raise ValueError(f"era {label} has no values for {key}")
        out.append({"era": label, "first": first, "last": last, "seasons": len(vals), "mean": round(sum(vals) / len(vals), 3)})
    return out


# ----------------------------------------------------------------- reasons
def build_reasons(box_season_rows: list[dict]) -> list[dict]:
    out = []
    for r in box_season_rows:
        season = r["season"]
        counts = {k: int(r[f"abs_{k}"]) for k in ("injury", "injury_unspecified", "illness", "rest", "coach", "suspension", "personal", "protocol", "roster", "unknown")}
        non_coach = sum(v for k, v in counts.items() if k != "coach")
        if non_coach == 0:
            raise ValueError(f"{season}: no non-coach absences in box scores")
        out.append(
            {
                "season": season,
                "start": season_start(season),
                "team_games": int(r["team_games"]),
                "listing": "full roster" if season <= FULL_ROSTER_LAST_SEASON else "active roster only",
                "body_part_named": season <= NAMED_BODY_PART_LAST_SEASON,
                "counts": counts,
                "health_per_team_game": round(float(r["health_absences_per_team_game"]), 3),
                "shares": {k: round(v / non_coach, 4) for k, v in counts.items() if k != "coach"},
            }
        )
    return out


# ----------------------------------------------------------------- locations
def location_table(counter: Counter) -> dict:
    total = sum(counter[loc] for loc in LOCATION_ORDER)
    if total == 0:
        raise ValueError("location table with zero injuries")
    return {
        "n": total,
        "shares": {loc: round(counter[loc] / total, 4) for loc in LOCATION_ORDER},
        "counts": {loc: counter[loc] for loc in LOCATION_ORDER},
        "below_knee_share": round(sum(counter[loc] for loc in BELOW_KNEE) / total, 4),
    }


def build_box_locations(box_rows: list[dict]) -> dict:
    """Body-location shares from box-score injury rows, per season and per listing era."""
    by_season: dict[str, Counter] = defaultdict(Counter)
    for r in box_rows:
        if r["category"] != "injury" or r["season"] > NAMED_BODY_PART_LAST_SEASON:
            continue
        by_season[r["season"]][r["location"]] += 1
    seasons = {s: location_table(c) for s, c in sorted(by_season.items())}
    eras = {}
    for label, first, last in (("1996-97 to 2002-03", "1996-97", FULL_ROSTER_LAST_SEASON), ("2003-04 to 2016-17", "2003-04", NAMED_BODY_PART_LAST_SEASON)):
        c = Counter()
        for s, cnt in by_season.items():
            if first <= s <= last:
                c.update(cnt)
        eras[label] = location_table(c)
    return {"seasons": seasons, "eras": eras}


def build_pst_locations(pst_rows: list[dict]) -> dict:
    """Body-location shares from PST out-events, per season and per decade (when the Kaggle file is present)."""
    by_season: dict[str, Counter] = defaultdict(Counter)
    for r in pst_rows:
        if r["event_type"] != "out" or r["category"] != "injury":
            continue
        by_season[r["season"]][r["location"]] += 1
    seasons = {s: location_table(c) for s, c in sorted(by_season.items())}
    decades: dict[str, Counter] = defaultdict(Counter)
    for s, c in by_season.items():
        decades[f"{season_start(s) // 10 * 10}s"].update(c)
    return {
        "seasons": seasons,
        "decades": {d: location_table(c) for d, c in sorted(decades.items()) if sum(c.values()) >= 100},
        "first_season": min(by_season) if by_season else None,
        "last_season": max(by_season) if by_season else None,
        "sources": sorted({r["source"] for r in pst_rows}),
    }


def episodes(report_rows: list[dict], gap_days: int = EPISODE_GAP_DAYS) -> list[dict]:
    """Pure: collapse per-game injury-report rows into episodes per (player, location).

    An episode starts the first report date a player is listed with a body
    location and ends when he has been off the report for `gap_days`. Rows
    without an injury category (rest, G League, protocols) are ignored.
    """
    rows = sorted((r for r in report_rows if r["category"] == "injury"), key=lambda r: (r["player"], r["location"], r["report_date"]))
    out: list[dict] = []
    last_seen: dict[tuple[str, str], dt.date] = {}
    current: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["player"], r["location"])
        day = dt.date.fromisoformat(r["report_date"][:10])
        prev = last_seen.get(key)
        if prev is None or (day - prev).days > gap_days:
            ep = {"player": r["player"], "location": r["location"], "first": day.isoformat(), "last": day.isoformat(), "report_days": 1, "out_days": 1 if r["status"].lower().startswith("out") else 0, "season": r["season"], "nature": r["nature"]}
            current[key] = ep
            out.append(ep)
        else:
            ep = current[key]
            ep["last"] = day.isoformat()
            ep["report_days"] += 1
            if r["status"].lower().startswith("out"):
                ep["out_days"] += 1
        last_seen[key] = day
    return out


def build_report_locations(report_rows: list[dict]) -> dict:
    eps = episodes(report_rows)
    by_season: dict[str, Counter] = defaultdict(Counter)
    out_days: dict[str, Counter] = defaultdict(Counter)
    for ep in eps:
        by_season[ep["season"]][ep["location"]] += 1
        out_days[ep["season"]][ep["location"]] += ep["out_days"]
    seasons = {}
    for s in sorted(by_season):
        tbl = location_table(by_season[s])
        tbl["out_days"] = {loc: out_days[s][loc] for loc in LOCATION_ORDER}
        tbl["out_days_total"] = sum(out_days[s].values())
        seasons[s] = tbl
    allc = Counter()
    for c in by_season.values():
        allc.update(c)
    return {"seasons": seasons, "all": location_table(allc), "episodes": len(eps), "first_report": min(r["report_date"] for r in report_rows), "last_report": max(r["report_date"] for r in report_rows)}


def display_name(raw: str) -> str:
    """'Durant, Kevin' -> 'Kevin Durant'; a name already in first-last order is kept as the source wrote it."""
    raw = raw.strip()
    if "," in raw:
        last, first = [p.strip() for p in raw.split(",", 1)]
        return f"{first} {last}"
    return raw


def player_key(name: str) -> str:
    """'Durant, Kevin' and 'Kevin Durant' and 'J.J. Barea' -> one key: lower-case 'first last', no punctuation."""
    name = name.strip().lower()
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        name = f"{first} {last}"
    name = name.replace(".", "").replace("'", "")
    for suffix in (" jr", " sr", " ii", " iii", " iv"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    parts = name.split()
    if len(parts) >= 2:
        # 'jj barea' and 'jose juan barea' are one player: last name plus first initial
        return f"{parts[0][0]} {parts[-1]}"
    return " ".join(parts)


def build_achilles(box_rows: list[dict], report_rows: list[dict], pst_rows: list[dict]) -> list[dict]:
    """Distinct players per season with an Achilles rupture, by source.

    The rule, stated on the page. Box scores and injured-list notes name the
    tear itself, so a player counts in the season the note says tear, torn or
    rupture. The official report lists a rupture as a tear, then as a repair or
    surgery for the whole recovery, so for reports a player counts in the season
    of his first Achilles listing that says tear, torn, rupture, repair or
    surgery while he is Out. One guard: a repair, surgery or rehab listing
    already present in the first two weeks of a season's reports is a rupture
    from before the league's season (summer league, college, the offseason) and
    is not counted. A rupture that happens after a season's last report (the
    2025 Finals' last game) or in the offseason is first listed as a tear on
    the next season's reports and counts there, which is why 2024-25 reads six
    here against the league's seven. A rupture on an Available line is the
    source's error and is ignored; partial tears are their own nature and are
    not counted.
    """
    found: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    names: dict[str, str] = {}

    def remember(raw: str) -> str:
        key = player_key(raw)
        names.setdefault(key, display_name(raw))
        return key

    for r in box_rows:
        if r["location"] == "achilles" and r["nature"] == "rupture":
            found[r["season"]]["box"].add(remember(r["player"]))
    for r in pst_rows:
        if r["event_type"] == "out" and r["location"] == "achilles" and r["nature"] == "rupture":
            found[r["season"]]["pst"].add(remember(r["player"]))
    season_first_report: dict[str, dt.date] = {}
    for r in report_rows:
        day = dt.date.fromisoformat(r["report_date"][:10])
        if r["season"] not in season_first_report or day < season_first_report[r["season"]]:
            season_first_report[r["season"]] = day
    first_listed: dict[str, tuple[str, dt.date, bool]] = {}
    for r in sorted(report_rows, key=lambda r: r["report_date"]):
        if r["location"] == "achilles" and r["nature"] in ("rupture", "surgery") and r["status"].lower().startswith("out"):
            key = remember(r["player"])
            aftercare = RECOVERY_WORDS.search(r["reason"]) is not None
            first_listed.setdefault(key, (r["season"], dt.date.fromisoformat(r["report_date"][:10]), aftercare))
    for player, (season, day, aftercare) in first_listed.items():
        if aftercare and (day - season_first_report[season]).days <= SEASON_START_GRACE_DAYS:
            continue  # a repair or rehab already listed when the season's reports begin: ruptured before them
        found[season]["report"].add(player)
    out = []
    prev: set = set()
    for season in sorted(found):
        srcs = found[season]
        union = set().union(*srcs.values()) - prev
        prev = set().union(*srcs.values())
        out.append({"season": season, "start": season_start(season), "players": sorted(names[k] for k in union), "n": len(union), "by_source": {k: len(v) for k, v in srcs.items()}})
    return out


# ----------------------------------------------------------------- pace, minutes, schedule
def build_pace(pace_rows: list[dict]) -> list[dict]:
    out = []
    for r in pace_rows:
        if r["partial"] == "1":
            continue
        out.append(
            {
                "season": r["season"],
                "start": season_start(r["season"]),
                "pace": round(num(r["pace_bbr_formula"]), 1) if r["season"] >= FIRST_PACE_SEASON and num(r["pace_bbr_formula"]) is not None else None,
                "pts": round(num(r["pts_per_game"]), 1) if num(r["pts_per_game"]) is not None else None,
                "fg3a_share": round(num(r["fg3a_share_of_fga"]), 3) if num(r["fg3a_share_of_fga"]) is not None else None,
                "fga": round(num(r["fga_per_game"]), 1) if num(r["fga_per_game"]) is not None else None,
            }
        )
    return out


def build_minutes(minutes_rows: list[dict], schedule_rows: list[dict]) -> list[dict]:
    sched = {r["season"]: r for r in schedule_rows}
    out = []
    for r in minutes_rows:
        if r["partial"] == "1" or r["season"] < FIRST_ROTATION_SEASON:
            continue
        s = sched[r["season"]]
        games = int(s["games_per_team"])
        out.append(
            {
                "season": r["season"],
                "start": season_start(r["season"]),
                "games_per_team": games,
                "top8_per_game": round(num(r["top8_mean_minutes"]) / games, 1),
                "top1_per_game": round(num(r["top1_mean_minutes"]) / games, 1),
                "top1_total": round(num(r["top1_mean_minutes"])),
                "players_3000": int(r["players_3000_plus"]),
                "players_2500": int(r["players_2500_plus"]),
                "min_per_player_game": round(num(r["mean_minutes_per_player_game"]), 1),
                "players_appeared": int(r["players_appeared"]),
                "back_to_backs": round(num(s["back_to_backs_per_team"]), 1),
                "rest_days": round(num(s["mean_rest_days"]), 2),
                "span_days": int(s["season_span_days"]),
                "playoff_max": int(s["playoff_games_max_team"]),
            }
        )
    return out


def build_leaders(leader_rows: list[dict]) -> list[dict]:
    out = []
    for r in leader_rows:
        if r["group"] != "finals_team_leader":
            continue
        reg, po = num(r["regular_minutes"], 0.0), num(r["playoff_minutes"], 0.0)
        out.append({"season": r["season"], "start": season_start(r["season"]), "player": r["player_name"], "team": r["team"], "regular": round(reg), "playoff": round(po), "total": round(reg + po), "games": int(r["regular_games"]) + int(r["playoff_games"])})
    return out


# ----------------------------------------------------------------- research constants
RESEARCH = {
    "leagues": {
        "note": "Team ceilings are schedule length times game length, regular season, no overtime. Star rows are the 2024-25 minutes leaders of the NBA Finals teams against each other league's 2024-25 or 2025 minutes leader; the EuroLeague figure includes playoff games because its table does not split them.",
        "rows": [
            {"league": "NBA", "games": 82, "minutes_per_game": 48, "ceiling": 3936, "playoff_max_games": 28, "playoff_ceiling": 1344, "source": "https://www.basketball-reference.com/leagues/NBA_2025_totals.html", "grade": "primary"},
            {"league": "EuroLeague 2024-25", "games": 34, "minutes_per_game": 40, "ceiling": 1360, "source": "https://www.basketball-reference.com/international/euroleague/2025.html", "grade": "primary", "caveat": "40-minute game length not opened in a rulebook"},
            {"league": "WNBA 2025", "games": 44, "minutes_per_game": 40, "ceiling": 1760, "source": "https://www.wnba.com/news/2025-game-schedule", "grade": "primary"},
            {"league": "NCAA Division I", "games": 31, "minutes_per_game": 40, "ceiling": 1240, "source": "http://ncaa.org/media-center-mens-and-womens-basketball-oversight-committees-propose-32-game-maximum-contest-limits/", "grade": "primary", "caveat": "31 is the regular-season cap before conference and NCAA tournaments; 40 minutes not opened in a rulebook"},
        ],
        "stars": [
            {"league": "NBA", "player": "Shai Gilgeous-Alexander", "season": "2024-25", "regular": 2598, "playoff": 851, "games": 99, "source": "https://www.basketball-reference.com/playoffs/NBA_2025_totals.html", "grade": "primary"},
            {"league": "NBA", "player": "Pascal Siakam", "season": "2024-25", "regular": 2548, "playoff": 771, "games": 101, "source": "https://www.basketball-reference.com/playoffs/NBA_2025_totals.html", "grade": "primary"},
            {"league": "WNBA", "player": "Kelsey Plum", "season": "2025", "regular": 1508, "playoff": None, "games": 43, "source": "https://www.basketball-reference.com/wnba/years/2025_totals.html", "grade": "primary"},
            {"league": "EuroLeague", "player": "Kendrick Nunn", "season": "2024-25", "regular": None, "playoff": None, "total": 1233, "games": 40, "source": "https://www.basketball-reference.com/international/euroleague/2025_totals.html", "grade": "primary", "caveat": "includes playoff games; the regular-season leader is likely Nigel Hayes at 1,059, unlabelled on the source page"},
        ],
    },
    "shoes": {
        "window": {"start": "2008-12", "end": "2020-21", "basis": "Start: the Nike Zoom Kobe IV, the first low-top a star adopted, announced in December 2008 with an expected on-court debut of 19 December. End: the only measured NBA share, 61% low, 33% mid, 6% high across 25,009 player appearances in 2020-21 (Tansey et al., Foot & Ankle Orthopaedics, 2023). A team podiatrist estimated roughly half in March 2018. No per-season series exists."},
        "timeline": [
            {"year": 1985, "event": "Air Jordan 1 released; the high-top is the default basketball shoe for the next two decades", "source": "https://www.nike.com/au/a/air-jordan-1-history", "grade": "primary"},
            {"year": 1989, "event": "Reebok Pump released (24 Nov 1989), the high-top at its most elaborate", "source": "https://www.espn.com/nba/story/_/id/28149048", "grade": "secondary"},
            {"year": 2001, "event": "Nike Jet Flight, one of the first basketball-specific low-tops", "source": "https://www.complex.com/sneakers/a/zac-dubasik/get-low-a-history-of-low-top-basketball-sneakers", "grade": "secondary"},
            {"year": 2008, "event": "Nike Zoom Kobe IV announced 11 Dec 2008; Kobe Bryant asked for 'a true, genuine low-top', with an on-court debut expected 19 Dec 2008. A Jazz podiatrist warned lows mean less stability", "source": "https://www.espn.com.sg/nba/news/story?id=3761462", "grade": "secondary"},
            {"year": 2010, "event": "Wall Street Journal via Marketplace: low-tops rose from about 11% to 29% of the US basketball-shoe market in eight years; high-tops fell from about 20% to 8% (consumer market, not NBA players)", "source": "http://www.marketplace.org/story/2010/05/19/are-high-top-shoes-losing-their-footing/", "grade": "secondary"},
            {"year": 2014, "event": "Complex: by the season after the Kobe IV, at least one player on every NBA team wore Kobes; KD, Hyperdunk Low, CP3 and Crazy Light Low followed", "source": "https://www.complex.com/sneakers/a/zac-dubasik/get-low-a-history-of-low-top-basketball-sneakers", "grade": "secondary"},
            {"year": 2018, "event": "Wizards and Mystics podiatrist: roughly half of NBA players wear lows (an estimate, not a count)", "source": "https://www.aip.org/inside-science/the-science-of-sneakers-high-tops-vs-low-tops", "grade": "secondary"},
            {"year": 2018, "event": "NBA lets players wear any shoe colour all season from 2018-19; framed as expression, no height or safety rule", "source": "https://www.espn.com/nba/story/_/id/24507661", "grade": "secondary"},
            {"year": 2021, "event": "Measured: 61% of 2020-21 NBA player appearances in lows, 33% mids, 6% highs (Tansey et al., 2023)", "source": "https://europepmc.org/article/PMC/PMC10748690", "grade": "primary"},
        ],
        "studies": [
            {"study": "Barrett et al., AJSM 1993", "finding": "622 college intramural players randomised to high-top, air-chamber high-top or low-top for a season: 15 ankle sprains (7, 4, 4), no significant difference", "source": "https://europepmc.org/article/MED/8368420", "grade": "primary (abstract)"},
            {"study": "McKay et al., BJSM 2001", "finding": "10,393 basketball participations, 40 ankle injuries: prior injury (OR 4.94), air-cell heels (OR 4.34) and not stretching (OR 2.62) were the risk factors; that collar height was not among them is AIP Inside Science's reading of the paper", "source": "https://europepmc.org/article/MED/11273971", "grade": "secondary"},
            {"study": "Cochrane review, Handoll et al. 2001", "finding": "a protective effect of high-top shoes 'remains to be established'", "source": "https://europepmc.org/article/MED/11686947", "grade": "primary (abstract)"},
            {"study": "Tansey et al., Foot & Ankle Orthopaedics 2023", "finding": "NBA 2020-21: 77 significant ankle injuries in 66 players; no difference in injury rate, days missed or performance by shoe height", "source": "https://europepmc.org/article/PMC/PMC10748690", "grade": "primary (abstract)"},
        ],
    },
    "studies": [
        {"study": "Starkey, J Athl Train 2000", "span": "1988-89 to 1997-98", "finding": "1,094 players, 3,843 player-seasons; ankle sprain the most frequent injury (9.4%); game injury rate about twice the college rate", "source": "https://europepmc.org/search?query=Starkey%20%22National%20Basketball%20Association%22%202000", "grade": "primary (abstract)"},
        {"study": "Drakos et al., Sports Health 2010", "span": "1988-89 to 2004-05", "finding": "lateral ankle sprain 13.2% of injuries, patellofemoral inflammation 11.9% and the most games lost (10,370); no link between injury rate and age, size or experience", "source": "https://europepmc.org/article/MED/23015949", "grade": "primary (abstract)"},
        {"study": "Mack et al., Sports Health 2025", "span": "2013-14 to 2018-19", "finding": "league injury database: 5.6 to 7.0 game-loss injuries per 10,000 player-minutes, no significant trend (P = 0.19); playoffs 2.8", "source": "https://europepmc.org/article/MED/38877729", "grade": "primary (abstract)"},
        {"study": "Lewis, J Athl Train 2018", "span": "2012-13 to 2014-15", "finding": "627 players, 73,209 games: injury odds up 2.87% per 96 minutes played and down 15.96% per rest day", "source": "https://europepmc.org/search?query=%22hard-knock%20life%22%20basketball", "grade": "primary (abstract)"},
        {"study": "Teramoto et al., J Sci Med Sport 2017", "span": "2012-13 to 2014-15", "finding": "back-to-backs and four-in-five were not linked to injury rate; playing away was", "source": "https://europepmc.org/search?query=Teramoto%20%22National%20Basketball%20Association%22%20game%20schedules", "grade": "primary (abstract)"},
        {"study": "Herzog et al., Sports Med 2026", "span": "2014-15 to 2022-23", "finding": "games missed for rest rose 125%; resting was not tied to lower later injury risk", "source": "https://europepmc.org/article/MED/42218310", "grade": "primary (abstract)"},
        {"study": "Maman et al., Orthop J Sports Med 2026", "span": "2000-01 to 2024-25", "finding": "22 Achilles ruptures; annual incidence not correlated with league pace", "source": "https://europepmc.org/article/MED/42436963", "grade": "primary (abstract)"},
        {"study": "Kumar et al., Orthop J Sports Med 2026", "span": "2014-15 to 2024-25", "finding": "19 Achilles ruptures; minutes in the 10 games before rupture 29.0 against a 27.4 season average (P = .01)", "source": "https://europepmc.org/article/MED/42502501", "grade": "primary (abstract)"},
        {"study": "Elsabbagh et al., Orthop J Sports Med 2026", "span": "1958 to 2024", "finding": "60 Achilles ruptures against 258 calf-strain controls: a prior calf strain carried OR 2.49", "source": "https://europepmc.org/article/MED/42293040", "grade": "primary (abstract)"},
        {"study": "Adam Silver, NBA.com, 27 Jun 2025", "span": "2024-25", "finding": "seven Achilles ruptures in 2024-25 by the league's count (four regular season, three playoffs, one in the Finals), zero the season before, previous high four; the league convened an expert panel and doubts season length is the cause", "source": "https://www.nba.com/news/nba-commissioner-adam-silver-league-researching-achilles-tears", "grade": "secondary"},
    ],
    "pace_anchors": [
        {"season": "1959-60", "pace": 126.1},
        {"season": "1973-74", "pace": 107.8},
        {"season": "1988-89", "pace": 100.6},
        {"season": "1998-99", "pace": 88.9},
        {"season": "2012-13", "pace": 92.0},
        {"season": "2019-20", "pace": 100.3},
        {"season": "2024-25", "pace": 98.8},
    ],
    "pace_anchor_source": "https://www.basketball-reference.com/leagues/NBA_stats_per_game.html",
}

CAVEATS = [
    "Games missed are inferred from appearances: a player who appears on two dates missed the team games in between. Games after a player's last appearance count only when he returns to the same team the next season, so a season-ending injury in a player's final year with a team is not counted. Rest days, suspensions and personal absences are gaps too; the reason mix below sizes them.",
    "Rotation means at least 10 games played and at least 20 minutes per game played, in that season. The threshold is fixed across eras, so deeper modern rotations change who qualifies, not the definition.",
    "Box-score reasons list the whole roster through 2002-03 and only the active roster from 2003-04, and they name the body part only through 2016-17. They are a sample of reasons, not a rate. The official injury reports (from December 2018) name the body part for every listed player and are the body-part source for the modern era.",
    "Pro Sports Transactions rows come from a file someone else published: a GitHub repository that scraped the archive for 2010 to 2019 and carries no licence. The archive's own terms could not be read (its site answers scripts and this browser with a bot challenge). They are dated moves, not games missed, and only their classification is kept; the note text is not.",
    "Body locations are assigned by keyword rules from the free text; a reason naming two parts gets the first in a fixed order (ankle before knee before back). The unknown share is published, not hidden.",
    "Shoe height is not measured for any NBA season before 2020-21. The transition window is bounded by a release date and one measured season, with an estimate in between.",
    "Nothing here is a causal finding. The page lines series up in time; the studies listed are the published evidence found (one randomised trial, the rest observational), and they disagree with several popular explanations.",
    "Achilles ruptures: a player counts in the season of his first Achilles listing that says tear, torn, rupture, repair or surgery while he is Out. A repair or rehab already listed when a season's reports begin is a rupture from before the league's season and is not counted; a rupture after a season's last report (the 2025 Finals' last game) or in the offseason is first listed as a tear on the next season's reports and counts there, which is why 2024-25 reads six here against the league's seven. The current season is partial.",
    "Body parts and absences come from the NBA's own injury reports and box-score comments, sorted by keyword rules, plus one third-party mirror of Pro Sports Transactions. Named players and their representatives can ask for a correction or removal at corrections@buddycheck.dev.",
]

SOURCES = [
    {"name": "nba.com box scores via nba_api (games, player minutes, DNP comments)", "url": "https://github.com/swar/nba_api"},
    {"name": "NBA official injury reports (PDF, December 2018 on)", "url": "https://official.nba.com/nba-injury-report-2025-26-season/"},
    {"name": "elap733/NBA-Injuries-Analysis (a Pro Sports Transactions scrape, 2010-2019, no licence)", "url": "https://github.com/elap733/NBA-Injuries-Analysis"},
    {"name": "Basketball-Reference.com, Sports Reference LLC: league pace and minutes (validation anchors)", "url": "https://www.basketball-reference.com/leagues/NBA_stats_per_game.html"},
    {"name": "Research briefs with every cited study and article (in the repository)", "url": "https://github.com/ericbackman/data_explorer/tree/main/injuries/research"},
]


def build(include_reports: bool = True, include_pst: bool = True) -> dict:
    missed_rows = read_csv("missed_games_by_season.csv")
    minutes_rows = read_csv("minutes_by_season.csv")
    schedule_rows = read_csv("schedule_by_season.csv")
    pace_rows = read_csv("pace_by_season.csv")
    leader_rows = read_csv("player_minutes_leaders.csv")
    box_season_rows = read_csv("box_absences_by_season.csv")
    box_rows = read_csv("box_absences.csv")
    report_rows = read_csv("injury_reports_classified.csv") if include_reports else []
    pst_rows = read_csv("pst_events.csv") if include_pst else []

    missed = build_missed(missed_rows, minutes_rows, schedule_rows)
    eras = [
        ("1976-77 to 1985-86", "1976-77", "1985-86"),
        ("1986-87 to 1995-96", "1986-87", "1995-96"),
        ("1996-97 to 2005-06", "1996-97", "2005-06"),
        ("2006-07 to 2015-16", "2006-07", "2015-16"),
        ("2016-17 to 2025-26", "2016-17", "2025-26"),
    ]
    data = {
        "built": dt.date.today().isoformat(),
        "locations": {"order": list(LOCATION_ORDER), "labels": LOCATION_LABELS, "below_knee": list(BELOW_KNEE)},
        "missed": missed,
        "missed_eras": era_means(missed, "per_team_game", eras),
        "reasons": build_reasons(box_season_rows),
        "box_locations": build_box_locations(box_rows),
        "pst_locations": build_pst_locations(pst_rows) if pst_rows else None,
        "report_locations": build_report_locations(report_rows) if report_rows else None,
        "achilles": build_achilles(box_rows, report_rows, pst_rows),
        "pace": build_pace(pace_rows),
        "minutes": build_minutes(minutes_rows, schedule_rows),
        "finals_leaders": build_leaders(leader_rows),
        "research": RESEARCH,
        "caveats": CAVEATS,
        "sources": SOURCES,
    }
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--without-reports", action="store_true", help="build before injury_reports_classified.csv exists (page shows the gap)")
    parser.add_argument("--without-pst", action="store_true", help="build without pst_events.csv")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = build(include_reports=not args.without_reports, include_pst=not args.without_pst)
    OUT.write_text("const INJURY_ERA_DATA = " + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n", encoding="utf-8")
    log.info("wrote %s (%d bytes); seasons: missed %d, reasons %d, pace %d", OUT, OUT.stat().st_size, len(data["missed"]), len(data["reasons"]), len(data["pace"]))
    for era in data["missed_eras"]:
        log.info("rotation games missed per team-game, %s: %.3f", era["era"], era["mean"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
