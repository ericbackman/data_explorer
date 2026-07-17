"""marimo twin of 01_explore.ipynb — the 2026 reactive style, for an A/B.

Run it:  uv run marimo edit marimo_sample.py

Why it's worth a look (verified in the research run):
  * stored as pure .py  -> git-diffable, agent-friendly
  * reactive            -> change the slider and dependent cells re-run
                           automatically; deleting a cell scrubs its variables,
                           so no stale hidden state
Same DuckDB read-only layer (sportsdb.py) as the Jupyter notebook.
"""
import marimo

__generated_with = "0.9.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import sportsdb

    con = sportsdb.connect()
    return con, mo, sportsdb


@app.cell
def _(mo):
    mo.md(
        """
        # Sports analysis — marimo sample

        Same read-only DuckDB layer as `01_explore.ipynb`. Drag the slider —
        the table below re-runs on its own (reactive execution, no re-running
        cells by hand).
        """
    )
    return


@app.cell
def _(sportsdb):
    sportsdb.databases()
    return


@app.cell
def _(mo):
    top_n = mo.ui.slider(3, 25, value=10, label="Top N single-game scorers")
    top_n
    return (top_n,)


@app.cell
def _(sportsdb, top_n):
    sportsdb.q(
        f"""
        SELECT p.player_name, g.pts, g.game_date
        FROM nba.player_game g
        JOIN nba.players p USING (player_id)
        ORDER BY g.pts DESC
        LIMIT {int(top_n.value)}
        """
    )
    return


if __name__ == "__main__":
    app.run()
