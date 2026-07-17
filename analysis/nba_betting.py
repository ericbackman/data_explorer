"""NBA player-prop form analysis — 2025-26 Regular Season.

A betting-minded look at the high-minutes core: for every rotation player with
enough games, compare full-season per-game rates against a last-10-games (L10)
"current form" window. The gap between season and L10 is exactly what a prop
bettor cares about — a player trending up or down relative to his season line,
plus how volatile his minutes are (low-minutes variance = more predictable props).

Every number is derived live from the local read-only nba.db; nothing is
hardcoded. Reproduces the verified findings table + two charts.

    uv run marimo edit nba_betting.py      # notebook editor
    uv run marimo run  nba_betting.py      # app view
"""
import marimo

__generated_with = "0.23.10"
app = marimo.App(width="full", app_title="NBA Prop Form")


@app.cell
def _():
    import marimo as mo
    import sqlite3
    import statistics
    from pathlib import Path

    import matplotlib.pyplot as plt
    import pandas as pd

    return Path, mo, pd, plt, sqlite3, statistics


@app.cell
def _(Path):
    # Resolve the DB read-only, relative to this file — never a hardcoded user path.
    # nba.db lives in the nba/ sub-project (data/ is gitignored & regenerable).
    _here = Path(__file__).resolve().parent
    DB_PATH = _here.parent / "nba" / "data" / "nba.db"
    DB_URI = "file:///" + DB_PATH.as_posix() + "?mode=ro"
    return DB_PATH, DB_URI


@app.cell
def _(mo):
    mo.md(
        r"""
        # NBA player-prop form — 2025-26 Regular Season

        For the high-minutes core of the league, this compares **full-season**
        per-game rates against a **last-10-games (L10)** "current form" window.
        The season-vs-L10 gap is the signal a prop bettor wants: who is trending
        up or down relative to his season line, and how volatile are his minutes.

        All figures are computed live from the local read-only `nba.db`.
        """
    )
    return


@app.cell
def _(DB_URI, sqlite3):
    SEASON = "2025-26"

    # Pull every regular-season player-game for the season, joined to name + team.
    # Ordering is deterministic (date, then game_id) so the L10 tail is stable.
    _sql = """
        SELECT pg.player_id, p.player_name, t.abbreviation AS team,
               pg.game_date, pg.min, pg.pts, pg.reb, pg.ast,
               pg.fg3m, pg.stl, pg.blk, pg.tov
        FROM player_game pg
        JOIN players p ON p.player_id = pg.player_id
        LEFT JOIN teams  t ON t.team_id  = pg.team_id
        WHERE pg.season = ? AND pg.season_type = 'Regular Season'
        ORDER BY pg.player_id, pg.game_date, pg.game_id
    """
    _con = sqlite3.connect(DB_URI, uri=True)
    try:
        rows = _con.execute(_sql, (SEASON,)).fetchall()
    finally:
        _con.close()
    return SEASON, rows


@app.cell
def _(DB_URI, SEASON, sqlite3):
    # Coverage anchors, derived (not assumed): date span + distinct game count.
    _con = sqlite3.connect(DB_URI, uri=True)
    try:
        _min, _max, _n_pg = _con.execute(
            "SELECT MIN(game_date), MAX(game_date), COUNT(DISTINCT game_id) "
            "FROM player_game WHERE season = ? AND season_type = 'Regular Season'",
            (SEASON,),
        ).fetchone()
        # The `games` table disagrees slightly with player_game (see data notes).
        _n_games_tbl = _con.execute(
            "SELECT COUNT(*) FROM games "
            "WHERE season = ? AND season_type = 'Regular Season'",
            (SEASON,),
        ).fetchone()[0]
    finally:
        _con.close()
    coverage = {
        "date_min": _min,
        "date_max": _max,
        "games_player_game": _n_pg,
        "games_games_tbl": _n_games_tbl,
    }
    coverage
    return (coverage,)


@app.cell
def _(rows, statistics):
    # ---- Pure aggregation: season means, L10 means, minutes volatility ----
    # Group player-games (already date-ordered) into per-player lists, then derive:
    #   season per-game means, last-10 means, stdev of L10 minutes,
    #   % of games >= 30 min, and the headline pts (L10 - season) delta.
    from collections import defaultdict

    GP_MIN = 20  # require a real sample before judging form

    by_player = defaultdict(list)
    for r in rows:
        (pid, name, team, gdate, mins, pts, reb, ast, fg3m, stl, blk, tov) = r
        by_player[pid].append(
            dict(name=name, team=team, date=gdate, min=mins or 0.0,
                 pts=pts or 0, reb=reb or 0, ast=ast or 0, fg3m=fg3m or 0,
                 stl=stl or 0, blk=blk or 0, tov=tov or 0)
        )

    def _mean(xs):
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    records = []
    for pid, games in by_player.items():
        gp = len(games)
        if gp < GP_MIN:
            continue
        last10 = games[-10:]
        team = next((g["team"] for g in reversed(games) if g["team"]), None)
        mins_l10 = [g["min"] for g in last10]
        rec = {
            "player_id": pid,
            "name": games[-1]["name"],
            "team": team,
            "gp": gp,
            "min_season": _mean([g["min"] for g in games]),
            "min_l10": _mean(mins_l10),
            "min_std_l10": round(statistics.pstdev(mins_l10), 1)
            if len(mins_l10) > 1 else 0.0,
            "pts_season": _mean([g["pts"] for g in games]),
            "pts_l10": _mean([g["pts"] for g in last10]),
            "reb_season": _mean([g["reb"] for g in games]),
            "reb_l10": _mean([g["reb"] for g in last10]),
            "ast_season": _mean([g["ast"] for g in games]),
            "ast_l10": _mean([g["ast"] for g in last10]),
            "fg3m_season": _mean([g["fg3m"] for g in games]),
            "fg3m_l10": _mean([g["fg3m"] for g in last10]),
            "pct_ge30": round(
                100 * sum(1 for g in games if g["min"] >= 30) / gp, 1
            ),
        }
        rec["pts_delta"] = round(rec["pts_l10"] - rec["pts_season"], 1)
        records.append(rec)
    return GP_MIN, records


@app.cell
def _(coverage, mo):
    mo.md(
        f"""
        **Coverage (derived):** {coverage['games_player_game']:,} regular-season
        games, {coverage['date_min']} → {coverage['date_max']}.

        > Data note: the `player_game` table holds **{coverage['games_player_game']:,}**
        > distinct RS game_ids while the `games` table has
        > **{coverage['games_games_tbl']:,}** RS rows — a {coverage['games_player_game'] - coverage['games_games_tbl']}-game
        > disagreement (a handful of games missing from `games`). The headline
        > game count is sourced from `player_game`; no betting number below depends
        > on the `games` table.
        """
    )
    return


@app.cell
def _(GP_MIN, mo, pd, records):
    df = pd.DataFrame(records)
    # Focus the readable table on the high-minutes core, sorted by season minutes.
    core = (
        df.sort_values("min_season", ascending=False)
        .head(25)
        .reset_index(drop=True)
    )
    mo.md(
        f"**{len(df)} players** with ≥ {GP_MIN} games. "
        f"Showing the top 25 by season minutes per game."
    )
    return core, df


@app.cell
def _(core):
    # Headline table: season vs L10 across the box-score lines that drive props.
    _show = core[
        ["name", "team", "gp", "min_season", "min_l10", "min_std_l10",
         "pts_season", "pts_l10", "pts_delta",
         "reb_season", "reb_l10", "ast_season", "ast_l10",
         "fg3m_season", "fg3m_l10", "pct_ge30"]
    ]
    _show
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Chart 1 — Points: season line vs current (L10) form

        Sorted by the **L10 − season** points delta. Bars to the right are players
        scoring **above** their season line over the last 10 (overs trending);
        bars to the left are cooling off (unders trending). This is the core
        prop-betting read: don't bet last season's number, bet the trend.
        """
    )
    return


@app.cell
def _(core, plt):
    # Chart 1: points delta (L10 - season), the headline betting signal.
    _d = core.sort_values("pts_delta")
    _colors = ["#c0392b" if v < 0 else "#27ae60" for v in _d["pts_delta"]]

    fig1, ax1 = plt.subplots(figsize=(8, 9))
    ax1.barh(_d["name"], _d["pts_delta"], color=_colors)
    ax1.axvline(0, color="#444", lw=1)
    ax1.set_xlabel("Points per game:  L10  −  season")
    ax1.set_title("Who's hot / cold vs their season scoring line (2025-26)")
    for _y, (_n, _v) in enumerate(zip(_d["name"], _d["pts_delta"])):
        ax1.text(_v + (0.1 if _v >= 0 else -0.1), _y, f"{_v:+.1f}",
                 va="center", ha="left" if _v >= 0 else "right", fontsize=8)
    ax1.margins(x=0.15)
    fig1.tight_layout()
    fig1
    return (fig1,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Chart 2 — Minutes: load and volatility

        Each player's **season minutes** (bar) with the spread of his **last-10
        minutes** (error bar = ±1 std of L10 minutes). Tall bars = heavy load;
        long error bars = erratic minutes, i.e. higher prop variance and blow-out /
        injury / rest risk. The most bettable props sit on high-minute, low-variance
        players.
        """
    )
    return


@app.cell
def _(core, plt):
    # Chart 2: minutes load + L10 volatility (error bar = std of last-10 minutes).
    _m = core.sort_values("min_season", ascending=True)
    fig2, ax2 = plt.subplots(figsize=(8, 9))
    ax2.barh(_m["name"], _m["min_season"], color="#2c7fb8",
             xerr=_m["min_std_l10"], capsize=3, ecolor="#e67e22")
    ax2.set_xlabel("Minutes per game (bar = season; error bar = ±1σ of L10 minutes)")
    ax2.set_title("Minutes load & last-10 volatility (2025-26)")
    ax2.set_xlim(0, max(45, _m["min_season"].max() + 6))
    for _y, (_v, _s) in enumerate(zip(_m["min_season"], _m["min_std_l10"])):
        ax2.text(_v + 0.3, _y, f"{_v:.1f}±{_s:.1f}", va="center", fontsize=7)
    fig2.tight_layout()
    fig2
    return (fig2,)


@app.cell
def _(df, mo):
    # Quick betting-angle leaderboards off the same derived frame.
    _hot = df.sort_values("pts_delta", ascending=False).head(5)
    _cold = df.sort_values("pts_delta", ascending=True).head(5)
    _steady = (
        df[df["min_season"] >= 30]
        .sort_values("min_std_l10")
        .head(5)
    )

    def _fmt(_r):
        return f"- **{_r['name']}** ({_r['team']}): {_r['pts_delta']:+.1f} pts "
        # noqa: kept simple

    mo.md(
        "### Betting angles (derived)\n\n"
        "**Hottest scorers (L10 vs season):** "
        + ", ".join(
            f"{r['name']} {r['pts_delta']:+.1f}" for _, r in _hot.iterrows()
        )
        + "\n\n**Coldest scorers:** "
        + ", ".join(
            f"{r['name']} {r['pts_delta']:+.1f}" for _, r in _cold.iterrows()
        )
        + "\n\n**Steadiest minutes (≥30 mpg, lowest L10 σ):** "
        + ", ".join(
            f"{r['name']} σ={r['min_std_l10']:.1f}" for _, r in _steady.iterrows()
        )
    )
    return


@app.cell
def _(SEASON, coverage, df, mo):
    mo.md(
        f"""
        ---
        *Source: local read-only `nba.db` (nba_api box scores). Season {SEASON},
        {coverage['games_player_game']:,} regular-season games. {len(df)} players
        met the ≥20-game threshold. Every figure derived live from the DB; the
        season-vs-L10 split and minutes σ are computed in-notebook.*
        """
    )
    return


if __name__ == "__main__":
    app.run()
