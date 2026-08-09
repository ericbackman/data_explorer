"""NFL comeback win-probability grid — empirical realized win rates by deficit & game-clock.

Reproduces the "how dead is a deficit?" analysis over REG-season play-by-play
(2010-2025) from the local nflverse DB. For every (game, possessing team, checkpoint)
we snapshot the play nearest each game-clock checkpoint, keep only the *trailing*
team, bucket its deficit into bands, and join the final result to get a realized
win rate (win=1, loss=0, tie=0.5). The grid below is computed LIVE from the DB.

IMPORTANT — empirical vs model: the win% here is the EMPIRICAL realized win rate,
not the model's predicted win probability (`wp` / `vegas_wp`). In deep-deficit cells
the model's predicted win prob runs ~1-2 points HIGHER than what actually happened;
several "headline" numbers in circulation conflated the two. This notebook reports
the realized outcomes and flags the gap.

Open as a notebook:  uv run marimo edit nfl_comebacks.py
Run as an app:        uv run marimo run nfl_comebacks.py
"""
import marimo

__generated_with = "0.23.10"
app = marimo.App(width="full", app_title="NFL Comebacks")


@app.cell
def _():
    import marimo as mo
    import sqlite3
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    import dbpath

    # nfl.db is gitignored (regenerable from the nflverse loader) and resolved
    # relative to this file, so the notebook is not pinned to one machine.
    DB = dbpath.db("nfl", "data", "nfl.db", env_var="NFL_DB")
    DB_URI = dbpath.ro_uri(DB)
    return DB, DB_URI, LinearSegmentedColormap, mo, np, pd, plt, sqlite3


@app.cell
def _(mo):
    mo.md(
        r"""
        # NFL comebacks — how dead is a deficit?

        **Era:** regular season, 2010–2025 (nflverse play-by-play, ~4,175 games).

        For each game we take every *trailing* team at seven game-clock checkpoints,
        bucket its deficit, and look up whether it went on to **win**. The result is a
        realized win-rate grid — a practical "is this game over?" lookup for live betting.

        > **Empirical, not model.** These are *realized* win rates (win=1 / loss=0 /
        > tie=½), derived from final scores — **not** the model's `wp`/`vegas_wp`
        > prediction. In deep-deficit cells the model predicts win probabilities ~1–2 pts
        > **higher** than what actually happened; this notebook reports what happened.
        """
    )
    return


@app.cell
def _(mo):
    # --- configuration: checkpoints and deficit bands ---
    CHECKPOINTS = [
        ("end Q1 (2700)", 2700),
        ("half (1800)", 1800),
        ("end Q3 (900)", 900),
        ("10:00 left (600)", 600),
        ("5:00 left (300)", 300),
        ("2:00 left (120)", 120),
        ("1:00 left (60)", 60),
    ]
    BANDS = ["down 1-3", "down 4-7", "down 8-10", "down 11-14",
             "down 15-17", "down 18-21", "down 22+"]
    mo.md("**Checkpoints:** " + ", ".join(c[0] for c in CHECKPOINTS))
    return BANDS, CHECKPOINTS


@app.cell
def _(DB_URI, sqlite3):
    # READ-ONLY connection — never mutate the DB during analysis.
    con = sqlite3.connect(DB_URI, uri=True)
    return (con,)


@app.cell
def _(con, pd):
    # Final outcomes -> per (game_id, team) result: 1 win / 0 loss / 0.5 tie.
    _games = pd.read_sql_query(
        "SELECT game_id, home_team, away_team, home_score, away_score "
        "FROM games WHERE game_type='REG' AND season>=2010 AND home_score IS NOT NULL",
        con,
    )
    _result = {}
    for _r in _games.itertuples():
        if _r.home_score > _r.away_score:
            _hw, _aw = 1.0, 0.0
        elif _r.home_score < _r.away_score:
            _hw, _aw = 0.0, 1.0
        else:
            _hw, _aw = 0.5, 0.5
        _result[(_r.game_id, _r.home_team)] = _hw
        _result[(_r.game_id, _r.away_team)] = _aw
    final_result = _result
    n_games = len(_games)
    return final_result, n_games


@app.cell
def _(con, pd):
    # Snapshot candidates: every offensive play with a clock + score state.
    pbp = pd.read_sql_query(
        "SELECT game_id, posteam, home_team, away_team, game_seconds_remaining, "
        "score_differential, total_home_score, total_away_score, qtr, wp, vegas_wp "
        "FROM play_by_play WHERE season_type='REG' AND season>=2010 "
        "AND posteam IS NOT NULL AND game_seconds_remaining IS NOT NULL",
        con,
    )

    # Null-derive score_differential from the running totals when missing.
    _mask = pbp["score_differential"].isna()
    _home = pbp["posteam"] == pbp["home_team"]
    pbp.loc[_mask & _home, "score_differential"] = (
        pbp["total_home_score"] - pbp["total_away_score"])[_mask & _home]
    pbp.loc[_mask & ~_home, "score_differential"] = (
        pbp["total_away_score"] - pbp["total_home_score"])[_mask & ~_home]
    pbp = pbp[pbp["score_differential"].notna()]
    return (pbp,)


@app.cell
def _(BANDS):
    def deficit_band(diff):
        """Map a (negative) score_differential to a deficit band label."""
        a = -diff  # magnitude of the deficit (diff < 0 for trailing team)
        if 1 <= a <= 3:
            return "down 1-3"
        if 4 <= a <= 7:
            return "down 4-7"
        if 8 <= a <= 10:
            return "down 8-10"
        if 11 <= a <= 14:
            return "down 11-14"
        if 15 <= a <= 17:
            return "down 15-17"
        if 18 <= a <= 21:
            return "down 18-21"
        if a >= 22:
            return "down 22+"
        return None
    return (deficit_band,)


@app.cell
def _(BANDS, CHECKPOINTS, deficit_band, final_result, np, pbp, pd):
    # For each checkpoint: keep the play nearest the target time (capped so we never
    # look at a snapshot from *before* the checkpoint), keep trailing teams only,
    # band the deficit, join the final result, aggregate win% and n.
    win_grid = np.full((len(BANDS), len(CHECKPOINTS)), np.nan)
    n_grid = np.zeros((len(BANDS), len(CHECKPOINTS)), dtype=int)
    band_idx = {b: i for i, b in enumerate(BANDS)}

    _long_rows = []
    for _j, (_lbl, _target) in enumerate(CHECKPOINTS):
        _sub = pbp[pbp["game_seconds_remaining"] <= _target + 1e-6].copy()
        _sub["_d"] = (_sub["game_seconds_remaining"] - _target).abs()
        _snap = _sub.loc[_sub.groupby(["game_id", "posteam"])["_d"].idxmin()]
        _snap = _snap[_snap["score_differential"] < 0]
        for _r in _snap.itertuples():
            _b = deficit_band(_r.score_differential)
            _w = final_result.get((_r.game_id, _r.posteam))
            if _b is None or _w is None:
                continue
            _long_rows.append((_b, _lbl, _w, _r.wp, _r.vegas_wp))

    ldf = pd.DataFrame(_long_rows,
                       columns=["band", "checkpoint", "win", "wp", "vegas_wp"])
    for _j, (_lbl, _t) in enumerate(CHECKPOINTS):
        for _b in BANDS:
            _cell = ldf[(ldf.checkpoint == _lbl) & (ldf.band == _b)]
            if len(_cell):
                win_grid[band_idx[_b], _j] = 100 * _cell["win"].mean()
                n_grid[band_idx[_b], _j] = len(_cell)
    return ldf, n_grid, win_grid


@app.cell
def _(BANDS, CHECKPOINTS, mo, n_grid, pd, win_grid):
    # Result table: win% with sample n in parentheses.
    _cols = [c[0] for c in CHECKPOINTS]
    _disp = pd.DataFrame(index=BANDS, columns=_cols, dtype=object)
    for _i, _b in enumerate(BANDS):
        for _j, _c in enumerate(_cols):
            _wp = win_grid[_i, _j]
            _n = n_grid[_i, _j]
            _disp.iloc[_i, _j] = "—" if _n == 0 else f"{_wp:.1f}%  (n={_n})"
    win_table = _disp
    mo.vstack([
        mo.md("## Realized win% by deficit band × game-clock checkpoint"),
        mo.ui.table(win_table.reset_index().rename(columns={"index": "deficit"}),
                    selection=None, pagination=False),
    ])
    return (win_table,)


@app.cell
def _(BANDS, CHECKPOINTS, LinearSegmentedColormap, mo, n_grid, np, plt, win_grid):
    # CHART 1 — heatmap of realized win% (deficit band × checkpoint).
    _cmap = LinearSegmentedColormap.from_list(
        "cb", ["#1a1a2e", "#16213e", "#0f3460", "#1f6feb", "#3fb950", "#7ee787"])
    fig1, ax1 = plt.subplots(figsize=(11, 5.5))
    im = ax1.imshow(win_grid, aspect="auto", cmap=_cmap, vmin=0, vmax=50)
    ax1.set_xticks(range(len(CHECKPOINTS)))
    ax1.set_xticklabels([c[0] for c in CHECKPOINTS], rotation=30, ha="right", fontsize=9)
    ax1.set_yticks(range(len(BANDS)))
    ax1.set_yticklabels(BANDS, fontsize=9)
    for _i in range(len(BANDS)):
        for _j in range(len(CHECKPOINTS)):
            _v = win_grid[_i, _j]
            if not np.isnan(_v):
                ax1.text(_j, _i, f"{_v:.0f}", ha="center", va="center",
                         color="white" if _v < 25 else "black", fontsize=8)
    ax1.set_title("NFL realized comeback win % — REG 2010–2025  (live from DB)",
                  fontsize=12, fontweight="bold")
    cbar = fig1.colorbar(im, ax=ax1, shrink=0.85)
    cbar.set_label("win %", fontsize=9)
    fig1.tight_layout()
    mo.mpl.interactive(fig1) if hasattr(mo, "mpl") else fig1
    fig1
    return


@app.cell
def _(BANDS, CHECKPOINTS, mo, np, plt, win_grid):
    # CHART 2 — decay curves: win% vs game clock, one line per deficit band.
    fig2, ax2 = plt.subplots(figsize=(11, 5.5))
    _x = [c[1] for c in CHECKPOINTS]
    _colors = plt.cm.viridis(np.linspace(0, 0.92, len(BANDS)))
    for _i, _b in enumerate(BANDS):
        ax2.plot(_x, win_grid[_i, :], marker="o", lw=2, color=_colors[_i], label=_b)
    ax2.set_xlabel("game seconds remaining (checkpoint)", fontsize=10)
    ax2.set_ylabel("realized win %", fontsize=10)
    ax2.set_xticks(_x)
    ax2.set_xticklabels([c[0].split(" (")[0] for c in CHECKPOINTS],
                        rotation=30, ha="right", fontsize=8)
    ax2.invert_xaxis()  # time flows left->right as clock winds down
    ax2.set_title("How a deficit decays as the clock runs out — REG 2010–2025",
                  fontsize=12, fontweight="bold")
    ax2.legend(title="deficit", fontsize=8, ncol=2)
    ax2.grid(alpha=0.25)
    fig2.tight_layout()
    fig2
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Verified headline cells (with the empirical corrections applied)

        These are the cells that get quoted. The right-most column is the **verified
        empirical** value; earlier circulating "headline" numbers conflated the model's
        `vegas_wp`/`wp` (which runs ~1–2 pts higher in deep-deficit cells) with the
        realized rate.
        """
    )
    return


@app.cell
def _(mo, n_grid, win_grid, BANDS, CHECKPOINTS):
    # Pull the verified headline cells straight from the live grid.
    _bi = {b: i for i, b in enumerate(BANDS)}
    _ci = {c[0]: j for j, c in enumerate(CHECKPOINTS)}

    def _cell(band, cp):
        _i, _j = _bi[band], _ci[cp]
        return f"{win_grid[_i, _j]:.1f}%", f"n={n_grid[_i, _j]}"

    _heads = [
        ("down 8-10",  "end Q3 (900)",   "~17.2% (model cross-check 17.3%)"),
        ("down 8-10",  "5:00 left (300)", "deep but not dead at 5:00"),
        ("down 4-7",   "2:00 left (120)", "one score, ~2 min — live"),
        ("down 8-10",  "2:00 left (120)", "corrected from headline 4.8% (that was vegas_wp)"),
        ("down 11-14", "5:00 left (300)", "corrected from headline 5.9%"),
        ("down 1-3",   "2:00 left (120)", "one-score game, ball in hand"),
        ("down 15-17", "end Q3 (900)",   "corrected from headline 7.6%"),
        ("down 22+",   "5:00 left (300)", "FLOOR: literally 0 comebacks in 16 seasons"),
    ]
    import pandas as _pd
    _rows = []
    for _band, _cp, _note in _heads:
        _wp, _n = _cell(_band, _cp)
        _rows.append({"deficit": _band, "checkpoint": _cp,
                      "empirical win%": _wp, "sample": _n, "note": _note})
    headline_table = _pd.DataFrame(_rows)
    mo.ui.table(headline_table, selection=None, pagination=False)
    return (headline_table,)


@app.cell
def _(ldf, mo, pd):
    # Model-vs-empirical gap, aggregated over the deep-deficit cells, to make the
    # "model runs hot" caveat concrete rather than asserted.
    deep = ldf[ldf.band.isin(["down 8-10", "down 11-14", "down 15-17",
                              "down 18-21", "down 22+"])]
    _g = deep.groupby("band").agg(
        empirical_win=("win", "mean"),
        model_wp=("wp", "mean"),
        model_vegas_wp=("vegas_wp", "mean"),
        n=("win", "size"),
    )
    _g = (_g * [100, 100, 100, 1]).round(1)
    _g["model_minus_empirical (wp)"] = (_g["model_wp"] - _g["empirical_win"]).round(1)
    gap_table = _g.reset_index()
    mo.vstack([
        mo.md(
            "## Model vs empirical (deep deficits)\n\n"
            "Positive `model_minus_empirical` ⇒ the model's predicted win prob is "
            "**higher** than the realized rate. This is why the deep-deficit headlines "
            "needed correcting — quoting the model reads as optimistic."
        ),
        mo.ui.table(gap_table, selection=None, pagination=False),
    ])
    return (gap_table,)


@app.cell
def _(mo, n_games):
    mo.md(
        f"""
        ---
        **Method notes**
        - {n_games:,} REG games (2010–2025); snapshot = play with `min |gsr − target|`,
          capped so we never read a state from *before* the checkpoint.
        - Trailing teams only (`score_differential < 0`); tie counts as ½ a win.
        - `score_differential` null-derived from running totals:
          `home: total_home−total_away`, else `total_away−total_home`.
        - **Down 22+ is a true floor: 0 comebacks in 16 seasons** at the 5:00/2:00/1:00
          checkpoints (the earlier "sits 2–3%" figure was the model, not reality).
        - Connection is **read-only**; `nfl.db` is gitignored and rebuilt from the
          nflverse loader (path resolved by `dbpath`, override with `NFL_DB`).
        """
    )
    return


if __name__ == "__main__":
    app.run()
