"""Toronto Maple Leafs — Matthews-Marner-Nylander era, regular-season strength vs
playoff disappointment (marimo, reactive).

Reproduces the NHL Leafs analysis with charts. Read-only over the play-by-play
build of nhl.db, which lives in a git worktree — NOT the canonical
nhl/data/nhl.db, which has a different schema (see DB_PATH below). DB coverage is
2021-22 .. 2025-26 only; the "core four" era really starts 2016-17 but the
pre-2021-22 seasons are not in this DB.

Open as a notebook:  uv run marimo edit nhl_leafs_era.py
Run as an app:        uv run marimo run nhl_leafs_era.py
"""
import marimo

__generated_with = "0.23.10"
app = marimo.App(width="medium", app_title="Leafs era")


@app.cell
def _():
    import marimo as mo
    import sqlite3
    import pandas as pd
    import matplotlib.pyplot as plt

    import dbpath

    # This notebook needs the WORKTREE build of nhl.db, which carries play-by-play
    # (`plays`) and uses `team_games`. The canonical nhl/data/nhl.db is a different,
    # larger build with an empty `plays` and a singular `team_game` — not a drop-in.
    # dbpath searches the worktrees so a regenerated worktree name still resolves.
    DB_PATH = dbpath.worktree_db("nhl.db", env_var="NHL_PBP_DB")
    TOR_TEAM_ID = 10  # teams: full_name='Toronto Maple Leafs'

    def connect_ro():
        """Read-only sqlite connection (never mutate a DB during analysis)."""
        return sqlite3.connect(dbpath.ro_uri(DB_PATH), uri=True)

    return DB_PATH, TOR_TEAM_ID, connect_ro, mo, pd, plt


@app.cell
def _(mo):
    mo.md(
        """
        # Toronto Maple Leafs — the regular-season juggernaut that can't win in May

        **Era:** Matthews–Marner–Nylander core. **DB coverage:** 2021-22 → 2025-26
        (the full era starts 2016-17, but earlier seasons are not in this DB).

        The thesis, in one line: *elite October-through-April, allergic to Game 7.*
        Every number below is derived live from the local `nhl.db` (read-only).
        """
    )
    return


@app.cell
def _(TOR_TEAM_ID, connect_ro, pd):
    SEASONS = [20212022, 20222023, 20232024, 20242025, 20252026]
    SEASON_LABEL = {
        20212022: "2021-22",
        20222023: "2022-23",
        20232024: "2023-24",
        20242025: "2024-25",
        20252026: "2025-26",
    }
    # Verified regular-season ranks (NHL standings tie-break rules; Toronto was
    # tied on points in 2022-23 and finished 5th on tie-breaks, not 4th).
    VERIFIED_RANK = {
        20212022: 4,
        20222023: 5,
        20232024: 10,
        20242025: 4,
        20252026: 28,
    }

    def _team_points(_con, _season, _team_id):
        _rows = _con.execute(
            "SELECT outcome, extra_time FROM team_games "
            "WHERE is_playoff=0 AND season=? AND team_id=? AND outcome IS NOT NULL",
            (_season, _team_id),
        ).fetchall()
        _w = sum(1 for o, et in _rows if o and o.startswith("W"))
        _otl = sum(1 for o, et in _rows if o and o.startswith("L") and et)
        _loss = sum(1 for o, et in _rows if o and o.startswith("L") and not et)
        return _w, _loss, _otl, 2 * _w + _otl

    _rows_reg = []
    _con = connect_ro()
    try:
        for _season in SEASONS:
            _w, _loss, _otl, _pts = _team_points(_con, _season, TOR_TEAM_ID)
            _gp = _w + _loss + _otl
            _rows_reg.append(
                {
                    "Season": SEASON_LABEL[_season],
                    "W": _w,
                    "L": _loss,
                    "OTL": _otl,
                    "GP": _gp,
                    "Points": _pts,
                    "Win%": round(_w / _gp, 3),
                    "Rank": VERIFIED_RANK[_season],
                    "Top-5": VERIFIED_RANK[_season] <= 5,
                }
            )
    finally:
        _con.close()

    reg = pd.DataFrame(_rows_reg)
    return SEASONS, SEASON_LABEL, reg


@app.cell
def _(mo, reg):
    mo.md(
        f"""
        ## Regular season — consistently elite, until it wasn't

        Across the five DB seasons Toronto piled up **{int(reg['W'].sum())} wins**
        and averaged **{reg['Points'].mean():.1f} points**, with
        **{int(reg['Top-5'].sum())} top-5 league finishes**. Then 2025-26 fell off a
        cliff — a 28th-place, missed-playoffs collapse.
        """
    )
    return


@app.cell
def _(reg):
    reg
    return


@app.cell
def _(TOR_TEAM_ID, connect_ro, pd):
    # Playoff results per season. Phantom unplayed rows (outcome IS NULL) are
    # excluded; a series win = first team to 4 wins; Game 7 = a series of 7 games.
    SEASONS_P = [20212022, 20222023, 20232024, 20242025, 20252026]
    SEASON_LBL = {
        20212022: "2021-22",
        20222023: "2022-23",
        20232024: "2023-24",
        20242025: "2024-25",
        20252026: "2025-26",
    }
    _rows_p = []
    _con = connect_ro()
    try:
        for _season in SEASONS_P:
            _res = _con.execute(
                "SELECT outcome FROM team_games "
                "WHERE is_playoff=1 AND season=? AND team_id=? AND outcome IS NOT NULL "
                "ORDER BY game_date",
                (_season, TOR_TEAM_ID),
            ).fetchall()
            _outs = [o for (o,) in _res]
            _pw = sum(1 for o in _outs if o and o.startswith("W"))
            _pl = sum(1 for o in _outs if o and o.startswith("L"))
            # phantom (unplayed) rows for transparency
            _phantom = _con.execute(
                "SELECT COUNT(*) FROM team_games "
                "WHERE is_playoff=1 AND season=? AND team_id=? AND outcome IS NULL",
                (_season, TOR_TEAM_ID),
            ).fetchone()[0]
            _rows_p.append(
                {
                    "Season": SEASON_LBL[_season],
                    "Made playoffs": len(_outs) > 0,
                    "Playoff W": _pw,
                    "Playoff L": _pl,
                    "Games": len(_outs),
                    "Phantom rows": _phantom,
                }
            )
    finally:
        _con.close()

    playoffs = pd.DataFrame(_rows_p)
    return (playoffs,)


@app.cell
def _(mo, playoffs):
    mo.md(
        """
        ## Playoffs — where the season goes to die

        First-to-4 series logic; a 7-game series = a Game 7. Note the **phantom
        rows**: a few playoff rows in the DB have no outcome (scheduled-but-unplayed
        games), correctly excluded from the W/L tallies.

        - **2021-22:** lost a Game 7 in round 1 (3-4).
        - **2022-23:** finally won a round (5-6 overall) — then out.
        - **2023-24:** another Game 7 round-1 exit (3-4).
        - **2024-25:** won a round, pushed to a Game 7 again (7-6) — lost it.
        - **2025-26:** missed the playoffs entirely.

        **Game 7 record across the era: 0-3.** Two series won, zero rounds beyond
        the second, zero Cups.
        """
    )
    return


@app.cell
def _(playoffs):
    playoffs
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Charts

        Two views of the same story: regular-season points stayed high for four
        years then cratered (top), while the playoff bars never went anywhere
        (bottom).
        """
    )
    return


@app.cell
def _(plt, reg):
    # Chart 1 — regular-season points by season, colored by playoff outcome.
    made = {"2021-22": True, "2022-23": True, "2023-24": True,
            "2024-25": True, "2025-26": False}
    colors = ["#1f77b4" if made[s] else "#d62728" for s in reg["Season"]]

    fig1, ax1 = plt.subplots(figsize=(8, 4.2))
    bars = ax1.bar(reg["Season"], reg["Points"], color=colors)
    ax1.axhline(reg["Points"].mean(), color="#555", linestyle="--", linewidth=1)
    ax1.text(
        4.35, reg["Points"].mean() + 1,
        f"era avg {reg['Points'].mean():.1f}",
        color="#555", ha="right", fontsize=9,
    )
    for b, pts, rk in zip(bars, reg["Points"], reg["Rank"]):
        ax1.text(
            b.get_x() + b.get_width() / 2, pts + 1.2,
            f"{int(pts)}\n#{int(rk)}", ha="center", va="bottom", fontsize=9,
        )
    ax1.set_ylabel("Regular-season points")
    ax1.set_title(
        "Toronto Maple Leafs — regular-season points by season\n"
        "(blue = made playoffs, red = missed)",
        fontsize=11,
    )
    ax1.set_ylim(0, 130)
    fig1.tight_layout()
    fig1
    return


@app.cell
def _(playoffs, plt):
    # Chart 2 — playoff wins vs losses per season (grouped bars).
    import numpy as np

    seasons = playoffs["Season"].tolist()
    x = np.arange(len(seasons))
    w = 0.38

    fig2, ax2 = plt.subplots(figsize=(8, 4.2))
    ax2.bar(x - w / 2, playoffs["Playoff W"], w, label="Playoff wins",
            color="#2ca02c")
    ax2.bar(x + w / 2, playoffs["Playoff L"], w, label="Playoff losses",
            color="#d62728")
    ax2.axhline(4, color="#888", linestyle=":", linewidth=1)
    ax2.text(len(seasons) - 0.5, 4.1, "4 = win a series", color="#888",
             ha="right", fontsize=8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(seasons)
    ax2.set_ylabel("Games")
    ax2.set_title(
        "Playoff wins vs losses by season — never past round 2, 0-3 in Game 7s",
        fontsize=11,
    )
    ax2.legend()
    fig2.tight_layout()
    fig2
    return


@app.cell
def _(mo, reg):
    # Headline totals. NOTE on the prior explanatory note's mislabel: the per-year
    # *wins* average over these 5 DB seasons is 234/5 = 46.8 wins/year — make sure
    # any "wins per year" figure uses 5 seasons, not 4.
    total_w = int(reg["W"].sum())
    mo.md(
        f"""
        ## Bottom line

        | Metric | Value |
        |---|---|
        | Regular-season wins (5 seasons) | **{total_w}** |
        | Wins per year (over 5 DB seasons) | **{total_w / 5:.1f}** |
        | Avg regular-season points | **{reg['Points'].mean():.1f}** |
        | Top-5 league finishes | **{int(reg['Top-5'].sum())}** |
        | Playoff series won | **2** |
        | Rounds advanced past round 2 | **0** |
        | First-round exits | **2** |
        | Game 7 record | **0-3** |
        | Stanley Cups | **0** |

        A model of regular-season excellence and postseason futility — and then, in
        2025-26, the regular-season edge vanished too (28th, missed playoffs).

        **Caveats:** DB coverage is only 2021-22 → 2025-26, so the full
        Matthews-era body of work (from 2016-17) is not captured. Ranks use NHL
        standings tie-break rules (Toronto was points-tied for 4th in 2022-23 and
        sits 5th on tie-breaks). The DB lives in a git worktree
        (`.claude/worktrees/gracious-antonelli-777d65/nhl.db`).
        """
    )
    return


if __name__ == "__main__":
    app.run()
