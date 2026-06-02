#!/usr/bin/env python3
"""
mitchell_profile.py — Pull NBA stats to support the Donovan Mitchell top-10 case.

Fetches 2024-25 regular season stats + career playoff totals for Mitchell and
9 comparison players in the 7-25 ranking range, then writes
nba_site/investigations/mitchell-top10/data.js
for the one-page website.

Usage:
    python mitchell_profile.py
"""

import sys, json, time, os, unicodedata
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from nba_api.stats.static import players as nba_players_db
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    playercareerstats,
    playerdashboardbyclutch,
)

SLEEP        = 0.6
SEASON       = "2025-26"
OUT_DIR      = "nba_site/investigations/mitchell-top10"
CACHE_PATH   = f"{OUT_DIR}/.cache.json"
OUTPUT_PATH  = f"{OUT_DIR}/data.js"
MIN_GP_RANK  = 45    # players below this GP are pulled but excluded from the ladder

# The pool for the top-20 ladder: consensus stars + the original debate set.
# The Lab Score (below) sorts them; we don't hand-rank.
TARGETS = [
    # Elite tier
    "Nikola Jokic", "Shai Gilgeous-Alexander", "Giannis Antetokounmpo",
    "Luka Doncic", "Jayson Tatum", "Victor Wembanyama",
    # Stars / veterans
    "Anthony Edwards", "Stephen Curry", "Kevin Durant", "LeBron James",
    "Anthony Davis", "Jalen Brunson", "Damian Lillard", "Jaylen Brown",
    "Tyrese Maxey", "Karl-Anthony Towns", "De'Aaron Fox",
    # The man himself + the 7–25 debate set
    "Donovan Mitchell",
    "Cade Cunningham", "Bam Adebayo", "Pascal Siakam", "Tyrese Haliburton",
    "LaMelo Ball", "Zach LaVine", "Devin Booker", "Julius Randle",
    "Paolo Banchero", "Darius Garland",
]


def _norm_name(s: str) -> str:
    """Diacritic- and punctuation-insensitive key so 'Jokić' == 'Jokic'."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(".", "").replace("'", "").replace("-", " ").strip()


# ── Cache helpers ─────────────────────────────────────────────────────────────

def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(c):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f)


# ── API fetchers ──────────────────────────────────────────────────────────────

def pull_league_stats(cache):
    """Return (df_base, df_adv) for the full league, SEASON regular season, per-game."""
    base_key, adv_key = f"base_{SEASON}", f"adv_{SEASON}"
    if base_key in cache and adv_key in cache:
        print("  [cache] league base + advanced")
        return pd.DataFrame(cache[base_key]), pd.DataFrame(cache[adv_key])

    print("  [api] LeagueDashPlayerStats base ...")
    df_base = leaguedashplayerstats.LeagueDashPlayerStats(
        season=SEASON,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Base",
        per_mode_detailed="PerGame",
    ).get_data_frames()[0]
    time.sleep(SLEEP)

    print("  [api] LeagueDashPlayerStats advanced ...")
    df_adv = leaguedashplayerstats.LeagueDashPlayerStats(
        season=SEASON,
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
    ).get_data_frames()[0]
    time.sleep(SLEEP)

    cache[base_key] = df_base.to_dict("records")
    cache[adv_key]  = df_adv.to_dict("records")
    save_cache(cache)  # persist immediately — these calls are the most expensive
    return df_base, df_adv


def pull_career(pid, name, cache):
    """
    Return {rs_career, playoff_career} per-game dicts from PlayerCareerStats.

    DataFrame index map (standard order from the endpoint):
      [0] SeasonTotalsRegularSeason   [1] CareerTotalsRegularSeason
      [2] SeasonTotalsPostSeason      [3] CareerTotalsPostSeason
    """
    key = f"career_{pid}_{SEASON}"
    if key in cache:
        return cache[key]

    print(f"  [api] career stats — {name} ...")
    dfs = playercareerstats.PlayerCareerStats(player_id=pid).get_data_frames()
    time.sleep(SLEEP)

    def _totals_to_pg(df):
        try:
            if df.empty:
                return None
            r  = df.iloc[0]
            gp = max(int(r["GP"]), 1)
            return {
                "GP":  gp,
                "PPG": round(float(r["PTS"]) / gp, 1),
                "RPG": round(float(r["REB"]) / gp, 1),
                "APG": round(float(r["AST"]) / gp, 1),
            }
        except Exception:
            return None

    result = {
        "rs_career":      _totals_to_pg(dfs[1] if len(dfs) > 1 else pd.DataFrame()),
        "playoff_career": _totals_to_pg(dfs[3] if len(dfs) > 3 else pd.DataFrame()),
    }
    cache[key] = result
    save_cache(cache)
    return result


def pull_clutch(pid, cache):
    """Mitchell's clutch situational stats (last 5 min, within 5 pts)."""
    key = f"clutch_{pid}_{SEASON}"
    if key in cache:
        return cache[key]

    print("  [api] clutch stats — Mitchell ...")
    dfs = playerdashboardbyclutch.PlayerDashboardByClutch(
        player_id=pid,
        season=SEASON,
        season_type_playoffs="Regular Season",
        per_mode_detailed="PerGame",
    ).get_data_frames()
    time.sleep(SLEEP)

    result = {}
    for i, df in enumerate(dfs):
        if not df.empty and "PTS" in df.columns:
            try:
                r  = df.iloc[0]
                gp = int(r["GP"])
                if gp > 0:
                    result[f"s{i}"] = {
                        "label":  str(r.get("GROUP_VALUE", f"s{i}")),
                        "gp":     gp,
                        "ppg":    round(float(r["PTS"]), 1),
                        "fg_pct": round(float(r.get("FG_PCT", 0)) * 100, 1),
                        "w_pct":  round(float(r.get("W_PCT", 0))  * 100, 1),
                    }
            except Exception:
                pass

    cache[key] = result
    return result


# ── Ranking model ─────────────────────────────────────────────────────────────
#
# "Lab Score" — a transparent 0–100 blend of 2024-25 production, playoff resume,
# and availability. Every input is a sourced stat; only the WEIGHTS are an
# opinion (and they're shown on the page).
#
#   35%  Impact        PIE (NBA's catch-all box metric), ceiling 20%
#   18%  Scoring       PPG, ceiling 32
#   12%  Efficiency    TS%, mapped 50%→0 … 65%→1
#   20%  Playoffs      career PO PPG (ceiling 30) + experience (ceiling 120 games)
#   15%  Availability  GP vs the NBA's own 65-game award-eligibility rule
#
# Availability is anchored to the league's actual 65-game minimum for MVP /
# All-NBA eligibility — not an arbitrary cutoff. A player who can't stay on the
# floor can't be a top-10 player, by the NBA's own standard.

LAB_WEIGHTS = {
    "impact":       0.35,
    "scoring":      0.18,
    "efficiency":   0.12,
    "playoffs":     0.20,
    "availability": 0.15,
}
AWARD_GP = 65   # NBA award-eligibility threshold (2023-24 onward)


def lab_score(p: dict) -> float:
    pie = p.get("pie")    or 0.0
    ppg = p.get("ppg")    or 0.0
    ts  = p.get("ts_pct") or 0.0
    gp  = p.get("gp")     or 0
    po  = (p.get("career") or {}).get("playoff_career") or {}
    po_ppg = po.get("PPG") or 0.0
    po_gp  = po.get("GP")  or 0

    impact       = min(pie / 20.0, 1.0)
    scoring      = min(ppg / 32.0, 1.0)
    efficiency   = max(0.0, min((ts - 50.0) / 15.0, 1.0))
    playoffs     = (min(po_ppg / 30.0, 1.0) * 0.6 +
                    min(po_gp, 120) / 120.0 * 0.4) if po_gp > 0 else 0.0
    availability = min(gp / float(AWARD_GP), 1.0)

    score = (LAB_WEIGHTS["impact"]       * impact +
             LAB_WEIGHTS["scoring"]      * scoring +
             LAB_WEIGHTS["efficiency"]   * efficiency +
             LAB_WEIGHTS["playoffs"]     * playoffs +
             LAB_WEIGHTS["availability"] * availability)
    return round(score * 100, 1)


def build_ranking(out_players: dict) -> list:
    """Sort eligible players by Lab Score, assign ranks + tiers."""
    eligible = [
        {"name": n, **p, "score": lab_score(p)}
        for n, p in out_players.items()
        if (p.get("gp") or 0) >= MIN_GP_RANK
    ]
    eligible.sort(key=lambda x: x["score"], reverse=True)

    ranking = []
    for i, p in enumerate(eligible, start=1):
        tier = "lock" if i <= 6 else "tier" if i <= 12 else "chase"
        po   = (p.get("career") or {}).get("playoff_career") or {}
        ranking.append({
            "rank":   i,
            "name":   p["name"],
            "team":   p.get("team", ""),
            "tier":   tier,
            "score":  p["score"],
            "ppg":    p.get("ppg"),
            "ts_pct": p.get("ts_pct"),
            "pie":    p.get("pie"),
            "po_ppg": po.get("PPG"),
            "po_gp":  po.get("GP") or 0,
            "is_mitchell": p["name"] == "Donovan Mitchell",
        })
    return ranking


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = load_cache()

    print(f"\nBuilding Mitchell top-10 profile — {SEASON}\n")
    df_base, df_adv = pull_league_stats(cache)

    # Index by NORMALIZED name so diacritics (Jokić, Dončić) still match
    base_idx = {_norm_name(r["PLAYER_NAME"]): r for r in reversed(df_base.to_dict("records"))}
    adv_idx  = {_norm_name(r["PLAYER_NAME"]): r for r in reversed(df_adv.to_dict("records"))}

    found   = [n for n in TARGETS if _norm_name(n) in base_idx]
    missing = [n for n in TARGETS if _norm_name(n) not in base_idx]
    if missing:
        print(f"  [warn] Not found in {SEASON} data: {missing}")

    def _pct(d, key):
        v = d.get(key) if d else None
        if v is None:
            return None
        v = float(v)
        # API returns 0-1 decimals for all percentage fields
        return round(v * 100, 1) if v <= 1.0 else round(v, 1)

    out_players = {}
    for name in found:
        key = _norm_name(name)
        b   = base_idx[key]
        a   = adv_idx.get(key, {})
        pid = int(b["PLAYER_ID"])

        career = pull_career(pid, name, cache)

        out_players[name] = {
            "player_id": pid,
            "team":    b.get("TEAM_ABBREVIATION", ""),
            "gp":      int(b["GP"]),
            "ppg":     round(float(b["PTS"]),    1),
            "rpg":     round(float(b["REB"]),    1),
            "apg":     round(float(b["AST"]),    1),
            "spg":     round(float(b["STL"]),    1),
            "bpg":     round(float(b["BLK"]),    1),
            "fg_pct":  round(float(b["FG_PCT"])  * 100, 1),
            "fg3_pct": round(float(b["FG3_PCT"]) * 100, 1),
            "ft_pct":  round(float(b["FT_PCT"])  * 100, 1),
            "ts_pct":  _pct(a, "TS_PCT"),
            "usg_pct": _pct(a, "USG_PCT"),
            "pie":     _pct(a, "PIE"),
            "career":  career,
        }

    mitchell = out_players.get("Donovan Mitchell")
    if mitchell:
        try:
            mitchell["clutch"] = pull_clutch(mitchell["player_id"], cache)
        except Exception as e:
            print(f"  [warn] clutch fetch failed ({e.__class__.__name__}) — skipping")
            mitchell["clutch"] = {}

    save_cache(cache)

    ranking       = build_ranking(out_players)
    mitchell_rank = next((r["rank"] for r in ranking if r["is_mitchell"]), None)

    output = {
        "season":        SEASON,
        "ordered":       [n for n in TARGETS if n in out_players],
        "players":       out_players,
        "ranking":       ranking,
        "mitchell_rank": mitchell_rank,
        "lab_weights":   LAB_WEIGHTS,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by mitchell_profile.py — do not edit manually\n")
        f.write("const MITCHELL_DATA = ")
        json.dump(output, f, indent=2, default=str)
        f.write(";\n")

    print(f"\nWrote {OUTPUT_PATH}")

    # ── Quick summary ──────────────────────────────────────────────────────────
    if mitchell:
        m      = mitchell
        career = m.get("career", {})
        po     = career.get("playoff_career") or {}
        rs_c   = career.get("rs_career")      or {}

        print(f"\nDonovan Mitchell {SEASON}:")
        print(f"  {m['ppg']} PPG | {m.get('ts_pct')}% TS | {m.get('usg_pct')}% USG | {m.get('pie')}% PIE")
        if po:
            elevation = round((po["PPG"] or 0) - (rs_c.get("PPG") or 0), 1)
            sign      = "+" if elevation >= 0 else ""
            print(f"  Career RS: {rs_c.get('PPG')} PPG | Playoffs: {po['PPG']} PPG ({po['GP']} games) | Elevation: {sign}{elevation}")

    print(f"\nLab Score ranking (Mitchell = #{mitchell_rank}):")
    for r in ranking:
        mark = "  <<< MITCHELL" if r["is_mitchell"] else ""
        po   = f"{r['po_ppg']:.1f}/{r['po_gp']}g" if r["po_ppg"] else "—"
        print(f"  {r['rank']:>2}. {r['name']:<26} score={r['score']:>5} | "
              f"{r['ppg']:>4.1f}p {str(r['ts_pct']):>4}ts {str(r['pie']):>4}pie | PO {po}{mark}")


if __name__ == "__main__":
    main()
