"""MLB — Toronto Blue Jays late/close-game analysis (NULL-RESULT report).

The original ask: per-season Blue Jays record, one-run games, run differential,
and blown-save / "blew a lead" tendencies. This notebook documents — with the DB
as the source of truth — why that ask CANNOT be answered for Toronto from this
database, and delivers the best adjacent analysis (a league-wide late/close-game
splits demo over the teams that ARE present).

Hard facts derived below:
  * Toronto Blue Jays (team_id 141 / 'TOR') have ZERO rows — absent from `teams`,
    `games`, and `team_game`. This is a 24-team, pre-1977-style roster (Toronto
    joined MLB in 1977), so the franchise simply is not in the data.
  * `season` / `game_date` are NOT real full ~162-game seasons: only 1974, 1975
    (regular season, game_type R) and a small 2024 Dodgers-Yankees postseason
    sample (game_type D/L/W/F). The values are legitimate rows from a fragmentary
    multi-source pull, not garbage — but there are no clean per-season buckets.
  * There is NO linescore / inning-level data, so a true "blew a lead" /
    "came from behind" is undetectable for ANY team.
  * `blown_saves` exists (in player_game_pitching) but is near-empty: only
    9 of 24 teams have any, 0-6 per team.

Run as a notebook:  uv run marimo edit mlb_bluejays.py
Export to HTML:     uv run marimo export html mlb_bluejays.py -o outputs/_check.html
"""
import marimo

__generated_with = "0.23.10"
app = marimo.App(width="medium", app_title="MLB Blue Jays")


@app.cell
def _():
    import marimo as mo
    import sqlite3
    import pandas as pd
    import matplotlib.pyplot as plt

    import dbpath

    # mlb.db still lives in a git worktree (see notebook caveat); dbpath searches
    # the worktrees rather than naming one, and falls back to mlb/data/ if the DB
    # is ever promoted out.
    DB_PATH = dbpath.worktree_db("mlb", "data", "mlb.db", env_var="MLB_DB")

    def q(sql: str) -> "pd.DataFrame":
        """Read-only query into a DataFrame. Connection is opened ?mode=ro."""
        con = sqlite3.connect(dbpath.ro_uri(DB_PATH), uri=True)
        try:
            return pd.read_sql_query(sql, con)
        finally:
            con.close()

    return DB_PATH, mo, pd, plt, q


@app.cell
def _(mo):
    mo.md(
        """
        # MLB — Toronto Blue Jays: late & close-game analysis

        **Verdict: the Blue Jays ask cannot be answered from this database.** This
        is a documented null result, not a modeling failure. Below, every claim is
        derived live from the DB. We then deliver the best *adjacent* analysis: a
        league-wide one-run / blowout / run-differential split over the teams that
        **are** present.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## 1. Is Toronto in the database? (No.)

        Toronto Blue Jays would be `team_id = 141` / abbreviation `TOR`. We check
        all three tables a team can appear in.
        """
    )
    return


@app.cell
def _(pd, q):
    _teams = q(
        "SELECT team_id, abbreviation, name FROM teams "
        "WHERE name LIKE '%Blue Jays%' OR abbreviation='TOR'"
    )
    _tg = q("SELECT COUNT(*) AS rows_in_team_game FROM team_game WHERE team_id=141")
    _gh = q("SELECT COUNT(*) AS games_as_home FROM games WHERE home_team_id=141")
    _ga = q("SELECT COUNT(*) AS games_as_away FROM games WHERE away_team_id=141")

    toronto_presence = pd.DataFrame(
        {
            "check": [
                "rows in teams (name/abbr match)",
                "rows in team_game (team_id=141)",
                "games as home (141)",
                "games as away (141)",
            ],
            "rows_found": [
                len(_teams),
                int(_tg.iloc[0, 0]),
                int(_gh.iloc[0, 0]),
                int(_ga.iloc[0, 0]),
            ],
        }
    )
    toronto_presence
    return (toronto_presence,)


@app.cell
def _(mo, q):
    _n_teams = len(q("SELECT DISTINCT team_id FROM team_game"))
    mo.md(
        f"""
        Every check returns **0**. The league here is a **{_n_teams}-team** roster
        — Toronto (which joined MLB in 1977) is not among them. There is no
        per-season W-L, one-run, run-diff, or blown-save data to derive for the
        Blue Jays. Fabricating any would violate the no-fake-data rule, so the
        rest of this notebook is a **method demo** on the present teams.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## 2. What seasons *are* here? (Not real full seasons.)

        The `season` / `game_date` fields are **not** clean ~162-game seasons —
        they're a fragmentary multi-source sample. 1974/1975 are regular season
        (`game_type` R); the 2024 rows are a small Dodgers-Yankees postseason set
        (`game_type` D/L/W/F). Legitimate rows, but no per-season buckets.
        """
    )
    return


@app.cell
def _(q):
    season_breakdown = q(
        "SELECT season, game_type, COUNT(*) AS games "
        "FROM games GROUP BY season, game_type ORDER BY season, game_type"
    )
    season_breakdown
    return (season_breakdown,)


@app.cell
def _(mo):
    mo.md(
        """
        ## 3. Adjacent analysis — league-wide close & blowout splits

        Since we cannot do Toronto, we demonstrate the *intended* method on the
        teams present. From final scores only we derive, per team: games, W-L,
        one-run W-L, blowout (5+ run margin) W-L, and total run differential.

        **Caveat:** there is **no linescore / inning data**, so a true "blew a
        lead" or "came from behind" is undetectable. One-run games are the closest
        available proxy for late-game tightness.
        """
    )
    return


@app.cell
def _(q):
    league = q(
        """
        WITH g AS (
            SELECT home_team_id tid, home_score rs, away_score ra FROM games
            UNION ALL
            SELECT away_team_id tid, away_score rs, home_score ra FROM games
        )
        SELECT t.abbreviation AS team,
               COUNT(*)                              AS gp,
               SUM(rs>ra)                            AS w,
               SUM(rs<ra)                            AS l,
               SUM(ABS(rs-ra)=1 AND rs>ra)           AS one_run_w,
               SUM(ABS(rs-ra)=1 AND rs<ra)           AS one_run_l,
               SUM(ABS(rs-ra)>=5 AND rs>ra)          AS blowout_w,
               SUM(ABS(rs-ra)>=5 AND rs<ra)          AS blowout_l,
               SUM(rs-ra)                            AS run_diff
        FROM g JOIN teams t ON t.team_id = g.tid
        GROUP BY t.abbreviation
        ORDER BY w DESC
        """
    )
    league["win_pct"] = (league["w"] / league["gp"]).round(3)
    league["one_run_pct"] = (
        league["one_run_w"] / (league["one_run_w"] + league["one_run_l"]).replace(0, 1)
    ).round(3)
    league
    return (league,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Chart 1 — Run differential by team (the teams that exist)

        Reds/Dodgers/A's at the top; this is the kind of view the Blue Jays ask
        wanted — just for a roster that doesn't include Toronto.
        """
    )
    return


@app.cell
def _(league, plt):
    _df = league.sort_values("run_diff")
    fig1, ax1 = plt.subplots(figsize=(7, 7))
    _colors = ["#2e7d32" if v >= 0 else "#c62828" for v in _df["run_diff"]]
    ax1.barh(_df["team"], _df["run_diff"], color=_colors)
    ax1.axvline(0, color="#333", linewidth=0.8)
    ax1.set_xlabel("Total run differential (runs scored − allowed)")
    ax1.set_title("League run differential by team\n(24-team roster — Toronto absent)")
    ax1.tick_params(axis="y", labelsize=8)
    fig1.tight_layout()
    fig1
    return ax1, fig1


@app.cell
def _(mo):
    mo.md(
        """
        ### Chart 2 — Blown saves: a near-empty column

        `blown_saves` exists in `player_game_pitching`, but only **9 of 24** teams
        have any, ranging 1-6. This is why no blown-save / "blew a lead" story can
        be told — for Toronto or anyone.
        """
    )
    return


@app.cell
def _(q):
    blown = q(
        """
        SELECT t.abbreviation AS team, SUM(pgp.blown_saves) AS blown_saves
        FROM player_game_pitching pgp
        JOIN teams t ON t.team_id = pgp.team_id
        WHERE pgp.blown_saves IS NOT NULL
        GROUP BY t.abbreviation
        HAVING SUM(pgp.blown_saves) > 0
        ORDER BY blown_saves DESC
        """
    )
    blown
    return (blown,)


@app.cell
def _(blown, plt, q):
    _n_total = len(q("SELECT DISTINCT team_id FROM team_game"))
    fig2, ax2 = plt.subplots(figsize=(7, 4))
    ax2.bar(blown["team"], blown["blown_saves"], color="#1565c0")
    ax2.set_ylabel("Blown saves (total in DB)")
    ax2.set_title(
        f"Blown saves by team — only {len(blown)} of {_n_total} teams populated"
    )
    ax2.set_ylim(0, max(7, blown["blown_saves"].max() + 1))
    for _i, _v in enumerate(blown["blown_saves"]):
        ax2.text(_i, _v + 0.1, str(int(_v)), ha="center", fontsize=9)
    fig2.tight_layout()
    fig2
    return ax2, fig2


@app.cell
def _(mo):
    mo.md(
        """
        ## Summary

        | Question | Answerable for Toronto? | Why |
        |---|---|---|
        | Per-season W-L | No | Toronto absent (team_id 141, 0 rows) |
        | One-run game record | No | Toronto absent + no inning data |
        | Run differential | No | Toronto absent |
        | Blew a lead / came from behind | No (any team) | No linescore/inning data |
        | Blown saves | No (any team, ~) | Only 9 of 24 teams populated, 1-6 each |

        **Bottom line:** this DB is a fragmentary, 24-team, pre-Toronto multi-source
        sample (1974/1975 regular season + a 2024 Dodgers-Yankees postseason slice).
        The Blue Jays simply are not in it. The league-wide splits above show the
        method that *would* answer the ask given complete, Toronto-inclusive data.
        """
    )
    return


if __name__ == "__main__":
    app.run()
