"""Mobile-friendly marimo explorer for the local sports/betting DBs.

Built to be served from your home machine and opened in mobile Safari (behind a
Cloudflare Tunnel + Access — see MOBILE.md). Touch-first: dropdowns to browse any
attached DB/table, plus a read-only SQL scratchpad. Same read-only DuckDB layer
(sportsdb.py) as 01_explore.ipynb.

Serve as a phone app:   uv run marimo run mobile.py     # app view, lightest
Open as a notebook:     uv run marimo edit mobile.py    # full editor
"""
import marimo

__generated_with = "0.23.10"
app = marimo.App(width="full", app_title="Sports DB")


@app.cell
def _():
    import marimo as mo
    import sportsdb

    sportsdb.connect()
    return mo, sportsdb


@app.cell
def _(mo):
    mo.md(
        """
        # Sports DB explorer

        Browse any attached database and run read-only SQL — from your phone.
        """
    )
    return


@app.cell
def _(mo, sportsdb):
    _dbs = sportsdb.databases()["database_name"].tolist()
    db = mo.ui.dropdown(_dbs, value=_dbs[0], label="Database")
    db
    return (db,)


@app.cell
def _(db, mo, sportsdb):
    _tbls = sportsdb.q(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_catalog = '{db.value}' ORDER BY table_name"
    )["table_name"].tolist()
    table = mo.ui.dropdown(_tbls, value=_tbls[0] if _tbls else None, label="Table")
    table
    return (table,)


@app.cell
def _(db, mo, table):
    mo.stop(not table.value, mo.md("_Pick a table above._"))
    mo.md(f"**Preview — `{db.value}.{table.value}`** (first 50 rows)")
    return


@app.cell
def _(db, sportsdb, table):
    sportsdb.q(f"SELECT * FROM {db.value}.{table.value} LIMIT 50")
    return


@app.cell
def _(mo):
    sql = mo.ui.text_area(
        value="",
        placeholder=(
            "SELECT p.player_name, g.pts, g.game_date\n"
            "FROM nba.player_game g JOIN nba.players p USING(player_id)\n"
            "ORDER BY g.pts DESC LIMIT 10"
        ),
        label="SQL scratchpad (read-only)",
        full_width=True,
        rows=5,
    )
    run = mo.ui.run_button(label="Run query")
    mo.vstack([sql, run])
    return run, sql


@app.cell
def _(mo, run, sportsdb, sql):
    mo.stop(not run.value, mo.md("_Type SQL above and tap **Run query**._"))
    try:
        _out = sportsdb.q(sql.value)
    except Exception as exc:  # surface DB errors in the UI — never swallow them
        _out = mo.md(f"**Query error:**\n\n```\n{exc}\n```")
    _out
    return


if __name__ == "__main__":
    app.run()
