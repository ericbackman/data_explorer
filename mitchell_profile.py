#!/usr/bin/env python3
"""
mitchell_profile.py — Pull NBA stats to support the Donovan Mitchell top-10 case.

Fetches 2024-25 regular season stats + career playoff totals for Mitchell and
9 comparison players in the 7-25 ranking range, then writes mitchell_top10/data.js
for the one-page website.

Usage:
    python mitchell_profile.py
"""

import sys, json, time, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from nba_api.stats.static import players as nba_players_db
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    playercareerstats,
    playerdashboardbyclutch,
)

SLEEP       = 0.6
SEASON      = "2024-25"
CACHE_PATH  = "mitchell_top10/.cache.json"
OUTPUT_PATH = "mitchell_top10/data.js"

# Players in the "is Mitchell top-15?" debate range — let data pick the winners
TARGETS = [
    "Donovan Mitchell",
    "Bam Adebayo",
    "Pascal Siakam",
    "Tyrese Haliburton",
    "LaMelo Ball",
    "Zach LaVine",
    "Devin Booker",
    "Julius Randle",
    "Paolo Banchero",
    "Darius Garland",
]


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
    if "base" in cache and "adv" in cache:
        print("  [cache] league base + advanced")
        return pd.DataFrame(cache["base"]), pd.DataFrame(cache["adv"])

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

    cache["base"] = df_base.to_dict("records")
    cache["adv"]  = df_adv.to_dict("records")
    save_cache(cache)  # persist immediately — these calls are the most expensive
    return df_base, df_adv


def pull_career(pid, name, cache):
    """
    Return {rs_career, playoff_career} per-game dicts from PlayerCareerStats.

    DataFrame index map (standard order from the endpoint):
      [0] SeasonTotalsRegularSeason   [1] CareerTotalsRegularSeason
      [2] SeasonTotalsPostSeason      [3] CareerTotalsPostSeason
    """
    key = f"career_{pid}"
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
    key = f"clutch_{pid}"
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("mitchell_top10", exist_ok=True)
    cache = load_cache()

    print(f"\nBuilding Mitchell top-10 profile — {SEASON}\n")
    df_base, df_adv = pull_league_stats(cache)

    # Index by player name (keeps first row if somehow duplicated)
    base_idx = {r["PLAYER_NAME"]: r for r in reversed(df_base.to_dict("records"))}
    adv_idx  = {r["PLAYER_NAME"]: r for r in reversed(df_adv.to_dict("records"))}

    found   = [n for n in TARGETS if n in base_idx]
    missing = [n for n in TARGETS if n not in base_idx]
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
        b   = base_idx[name]
        a   = adv_idx.get(name, {})
        pid = int(b["PLAYER_ID"])

        career = pull_career(pid, name, cache)

        out_players[name] = {
            "player_id": pid,
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

    output = {
        "season":  SEASON,
        "ordered": [n for n in TARGETS if n in out_players],
        "players": out_players,
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

    print("\nComparison players:")
    for name in found:
        if name == "Donovan Mitchell":
            continue
        p  = out_players[name]
        po = (p.get("career") or {}).get("playoff_career") or {}
        print(f"  {name:<22} {p['ppg']:5.1f} PPG | {str(p.get('ts_pct','?')):>5}% TS | PO: {po.get('PPG', 'N/A')}")


if __name__ == "__main__":
    main()
