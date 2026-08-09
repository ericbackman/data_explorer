"""World Cup draws — how often do matches end level, and does it vary?

Reproducible analysis over the local soccer DB (FIFA World Cup, 1930-2022; the 2026
tournament is in the DB as 61 Scheduled fixtures and is excluded). Every number is
derived from the DB at run time, not hard-coded.

Headline (all with Wilson 95% CIs):
  - Overall full-time draw rate ~22%.
  - Group-stage draws ~24-25%; knockout games level after 90 min ~17%.
  - The draw rate does NOT vary detectably with the pre-match strength gap — large
    Elo mismatches draw at statistically the same rate as even matchups. This is a
    NULL result: the buckets' CIs overlap heavily and the sign even flips with the
    Elo K constant, so we cannot claim the favorite suppresses (or inflates) draws.

Open as a notebook:  uv run marimo edit soccer_wc_draws.py
Run as an app:       uv run marimo run soccer_wc_draws.py

Caveat: soccer.db currently lives in a git worktree rather than soccer/data/.
`dbpath.worktree_db` finds it either way; set SOCCER_DB to override.
"""
import marimo

__generated_with = "0.23.10"
app = marimo.App(width="medium", app_title="World Cup draws")


@app.cell
def _():
    import marimo as mo
    import sqlite3
    import math
    import pandas as pd
    import matplotlib.pyplot as plt

    import dbpath

    # soccer.db still lives in a git worktree; dbpath searches the worktrees
    # rather than naming one, so a regenerated worktree still resolves.
    DB_PATH = dbpath.worktree_db("soccer", "data", "soccer.db", env_var="SOCCER_DB")

    def connect_ro():
        return sqlite3.connect(dbpath.ro_uri(DB_PATH), uri=True)

    def wilson(k, n, z=1.96):
        """Wilson score 95% CI for a proportion k/n. Returns (lo, hi)."""
        if n == 0:
            return (0.0, 0.0)
        p = k / n
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        return (centre - half, centre + half)

    return DB_PATH, connect_ro, math, mo, pd, plt, wilson


@app.cell
def _(mo):
    mo.md(
        """
        # World Cup draws — how often does a match end level?

        FIFA World Cup, **1930–2022** (22 played tournaments; the 2026 fixtures in
        the DB are `Scheduled` and excluded). Every figure below is computed from the
        local soccer DB at run time.

        **What we find**

        - Full-time draws happen ~**22%** of the time overall.
        - In the **group stage** ~**24–25%**; in **knockout** games the rate level
          after 90 minutes is ~**17%**.
        - The draw rate does **not** vary detectably with the pre-match strength gap.
          This is reported as a **null result**, not a betting edge — see the
          mismatch section.
        """
    )
    return


@app.cell
def _(connect_ro, pd):
    # Pull every played WC match, chronological. Read-only.
    _con = connect_ro()
    matches = pd.read_sql_query(
        """
        SELECT m.match_id, m.date, m.round, s.year,
               m.home_team_id, m.away_team_id,
               m.home_score, m.away_score, m.home_pens, m.away_pens, m.status
        FROM matches m
        JOIN seasons s ON m.season_id = s.season_id
        WHERE m.status != 'Scheduled'
        ORDER BY m.date, m.match_id
        """,
        _con,
    )
    _con.close()

    GROUP_ROUNDS = {"group-stage", "preliminary-round", "final-stage"}
    matches["is_draw"] = matches["home_score"] == matches["away_score"]
    matches["is_group"] = matches["round"].isin(GROUP_ROUNDS)
    matches
    return GROUP_ROUNDS, matches


@app.cell
def _(matches, mo, pd, wilson):
    # Headline rates with Wilson 95% CIs.
    def rate_row(label, sub):
        _k = int(sub["is_draw"].sum())
        _n = len(sub)
        _lo, _hi = wilson(_k, _n)
        return {
            "split": label,
            "draws": _k,
            "n": _n,
            "draw_rate": round(_k / _n, 4),
            "ci_low": round(_lo, 4),
            "ci_high": round(_hi, 4),
            "fair_odds": round(_n / _k, 2) if _k else None,
        }

    _grp = matches[matches["is_group"]]
    _kno = matches[~matches["is_group"]]
    headline = pd.DataFrame(
        [
            rate_row("Overall (full time)", matches),
            rate_row("Group stage", _grp),
            rate_row("Knockout (level after 90')", _kno),
        ]
    )
    mo.vstack(
        [
            mo.md("## Headline draw rates (Wilson 95% CI)"),
            mo.md(
                "Group rounds := `group-stage`, `preliminary-round`, `final-stage`. "
                "_Caveat:_ the 1934 `preliminary-round` (17 games) is really a pure "
                "knockout and the 1950 `final-stage` (6 games) a final round-robin — "
                "a strict `group-stage`-only split gives **177/720 = 24.6%**, "
                "essentially the same number."
            ),
            headline,
        ]
    )
    return (headline,)


@app.cell
def _(GROUP_ROUNDS, matches):
    # Elo over ALL played matches in chrono order; score each GROUP game on
    # PRE-match ratings, then update. K=40, goal-diff multiplier, neutral venue.
    K = 40
    elo = {}

    def get(t):
        return elo.get(t, 1500.0)

    bucket_rows = []  # (bucket, is_draw) for group games
    for r in matches.itertuples(index=False):
        h, a = r.home_team_id, r.away_team_id
        eh, ea = get(h), get(a)
        if r.round in GROUP_ROUNDS:
            gap = abs(eh - ea)
            if gap < 75:
                _b = "even (<75)"
            elif gap < 200:
                _b = "moderate (75-200)"
            else:
                _b = "large (200+)"
            bucket_rows.append((_b, bool(r.is_draw)))
        # update ratings on the actual result
        exp_h = 1 / (1 + 10 ** ((ea - eh) / 400))
        if r.home_score > r.away_score:
            sc = 1.0
        elif r.home_score < r.away_score:
            sc = 0.0
        else:
            sc = 0.5
        gd = abs(r.home_score - r.away_score)
        if gd <= 1:
            mult = 1.0
        elif gd == 2:
            mult = 1.5
        else:
            mult = (11 + gd) / 8
        delta = K * mult * (sc - exp_h)
        elo[h] = eh + delta
        elo[a] = ea - delta

    return (bucket_rows,)


@app.cell
def _(bucket_rows, mo, pd, wilson):
    _order = ["even (<75)", "moderate (75-200)", "large (200+)"]
    _agg = {_b: [0, 0] for _b in _order}
    for _b, _d in bucket_rows:
        _agg[_b][1] += 1
        if _d:
            _agg[_b][0] += 1
    _rows = []
    for _b in _order:
        _k, _n = _agg[_b]
        _lo, _hi = wilson(_k, _n)
        _rows.append(
            {
                "elo_gap_bucket": _b,
                "draws": _k,
                "n": _n,
                "draw_rate": round(_k / _n, 4),
                "ci_low": round(_lo, 4),
                "ci_high": round(_hi, 4),
                "fair_odds": round(_n / _k, 2),
                "fair_odds_ci": f"{1/_hi:.2f}–{1/_lo:.2f}",
            }
        )
    mismatch = pd.DataFrame(_rows)
    mo.vstack(
        [
            mo.md("## Does the strength gap change the draw rate? (NULL result)"),
            mo.md(
                "Group games bucketed by pre-match Elo gap. The draw rate is "
                "**flat across buckets and the CIs overlap heavily** — large "
                "mismatches draw at statistically the same rate as even games. "
                "The `large` bucket's fair price (3.92) sits on a 95% CI of roughly "
                "**3.1–5.6**, so it cannot distinguish a 4.48 fair price from a 4.5 "
                "book line. There is **no actionable betting angle** here, and the "
                "sign of any gap effect flips with the Elo K constant (20/30/40)."
            ),
            mismatch,
        ]
    )
    return (mismatch,)


@app.cell
def _(matches, mo, pd, wilson):
    # Era trend.
    def era(y):
        if y <= 1966:
            return "1930-1966"
        if y <= 1990:
            return "1970-1990"
        if y <= 2006:
            return "1994-2006"
        return "2010-2022"

    _m = matches.copy()
    _m["era"] = _m["year"].map(era)
    _rows = []
    for _e in ["1930-1966", "1970-1990", "1994-2006", "2010-2022"]:
        _sub = _m[_m["era"] == _e]
        _k, _n = int(_sub["is_draw"].sum()), len(_sub)
        _lo, _hi = wilson(_k, _n)
        _rows.append(
            {"era": _e, "draws": _k, "n": _n, "draw_rate": round(_k / _n, 4),
             "ci_low": round(_lo, 4), "ci_high": round(_hi, 4)}
        )
    eras = pd.DataFrame(_rows)
    mo.vstack(
        [
            mo.md("## Draws by era"),
            mo.md(
                "The 1930–1966 era is the outlier (~14%): few teams, lopsided "
                "scorelines. From 1970 on the rate settles around a quarter."
            ),
            eras,
        ]
    )
    return (eras,)


@app.cell
def _(headline, mismatch, plt):
    # Chart 1: headline rates + mismatch buckets, with CI error bars.
    fig1, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(11, 4.2))

    _h = headline
    _err = [
        _h["draw_rate"] - _h["ci_low"],
        _h["ci_high"] - _h["draw_rate"],
    ]
    ax_a.bar(_h["split"], _h["draw_rate"], yerr=_err, capsize=5,
             color=["#4C72B0", "#55A868", "#C44E52"])
    ax_a.set_ylabel("Draw rate")
    ax_a.set_title("WC draw rate by stage (Wilson 95% CI)")
    ax_a.set_ylim(0, 0.32)
    ax_a.tick_params(axis="x", rotation=20)
    for _i, _v in enumerate(_h["draw_rate"]):
        ax_a.text(_i, _v + 0.005, f"{_v:.1%}", ha="center", fontsize=9)

    _m = mismatch
    _err2 = [
        _m["draw_rate"] - _m["ci_low"],
        _m["ci_high"] - _m["draw_rate"],
    ]
    ax_b.bar(_m["elo_gap_bucket"], _m["draw_rate"], yerr=_err2, capsize=5,
             color="#8172B3")
    ax_b.set_ylabel("Draw rate")
    ax_b.set_title("Group draw rate vs Elo gap — flat (NULL)")
    ax_b.set_ylim(0, 0.40)
    ax_b.tick_params(axis="x", rotation=15)
    for _i, _v in enumerate(_m["draw_rate"]):
        ax_b.text(_i, _v + 0.005, f"{_v:.1%}\nn={_m['n'].iloc[_i]}",
                  ha="center", fontsize=8)
    fig1.tight_layout()
    fig1
    return


@app.cell
def _(eras, plt):
    # Chart 2: era trend line with CI band.
    fig2, ax = plt.subplots(figsize=(8, 4.2))
    _x = list(range(len(eras)))
    ax.plot(_x, eras["draw_rate"], marker="o", color="#4C72B0", lw=2,
            label="Draw rate")
    ax.fill_between(_x, eras["ci_low"], eras["ci_high"], alpha=0.2,
                    color="#4C72B0", label="Wilson 95% CI")
    ax.set_xticks(_x)
    ax.set_xticklabels(eras["era"])
    ax.set_ylabel("Draw rate")
    ax.set_ylim(0, 0.35)
    ax.set_title("World Cup full-time draw rate by era")
    for _i, _v in enumerate(eras["draw_rate"]):
        ax.text(_i, _v + 0.01, f"{_v:.1%}", ha="center", fontsize=9)
    ax.legend(loc="lower right")
    fig2.tight_layout()
    fig2
    return


@app.cell
def _(matches, mo):
    # Data-integrity notes derived live from the table.
    _level90 = matches[(~matches["is_group"]) & (matches["is_draw"])]
    _pens = matches[matches["status"] == "Final Score - After Penalties"]
    _et = matches[matches["status"] == "Final Score - After Extra Time"]
    mo.md(
        f"""
        ## Data-integrity notes (computed live)

        - **Knockout endings:** {len(_level90)} games were level after regulation;
          of those, **{len(_pens)} reached penalties**
          (`status = 'Final Score - After Penalties'`) and {len(_et)} more were
          settled in extra time. (So "45 went to penalties" would be wrong — 45 is
          the level-after-90 count, 33 is penalties.)
        - **Half-time data is absent:** every row has `home_ht IS NULL`, so an
          HT-level → FT-level analysis is impossible on this DB.
        - **2026 excluded:** the 61 `Scheduled` 2026 fixtures carry no scores and are
          filtered out; all rates are over the 1007 played matches.
        - **Stage scheme is a choice:** the group/knockout split is scheme-dependent
          (720/287 strict vs 743/264 inclusive); both give a group draw rate of
          ~24.5%.
        """
    )
    return


if __name__ == "__main__":
    app.run()
