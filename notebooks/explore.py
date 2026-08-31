import marimo

__generated_with = "0.9"
app = marimo.App(width="medium")


@app.cell
def _():
    # Make the sibling helper importable. This notebook is launched with its own
    # folder as the working directory, so cwd holds sports_db.py.
    import os
    import sys

    sys.path.insert(0, os.getcwd())

    import marimo as mo
    import pandas as pd

    import sports_db
    from sports_db import DATA_ROOT, DATABASES, q, schema, tables

    return DATA_ROOT, DATABASES, mo, pd, q, schema, sports_db, tables


@app.cell
def _(mo):
    mo.md(
        r"""
        # Sports data explorer (marimo)

        Reactive, **read-only** exploration. Pick a database, type SQL, and the
        results re-run automatically — no "run cell" needed.

        Connections are opened `mode=ro`, so nothing here can mutate a database.
        Full column map: [`../SCHEMA.md`](../SCHEMA.md).
        """
    )
    return


@app.cell
def _(DATABASES, mo):
    db = mo.ui.dropdown(
        options=sorted(DATABASES), value="nba", label="**Database**"
    )
    db
    return (db,)


@app.cell
def _(DATA_ROOT, DATABASES, db, mo, tables):
    _path = DATABASES[db.value]
    _mb = _path.stat().st_size / 1e6
    mo.md(
        f"**{db.value}** — `{_path.relative_to(DATA_ROOT)}` ({_mb:,.0f} MB)\n\n"
        f"Tables: {', '.join(f'`{t}`' for t in tables(db.value))}"
    )
    return


@app.cell
def _(mo):
    sql = mo.ui.text_area(
        value=(
            "SELECT pl.player_name, SUM(pg.pts) AS career_pts, COUNT(*) AS games\n"
            "FROM player_game pg\n"
            "JOIN players pl ON pl.player_id = pg.player_id\n"
            "WHERE pg.season_type = 'Regular Season'\n"
            "GROUP BY pg.player_id\n"
            "ORDER BY career_pts DESC\n"
            "LIMIT 10"
        ),
        label="**SQL** (read-only)",
        full_width=True,
        rows=8,
    )
    sql
    return (sql,)


@app.cell
def _(db, mo, q, sql):
    # Reactive: re-runs whenever the dropdown or the SQL box changes.
    try:
        _df = q(sql.value, db.value)
        view = mo.ui.table(_df, selection=None)
    except Exception as exc:  # surface the error instead of swallowing it
        view = mo.md(f"**Query error:** `{exc}`")
    view
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## 🧩 Your turn: a safety guard

        `play_by_play` is **17.7M rows** — a bare `SELECT *` would try to load all
        of them. In `sports_db.py` there's a stubbed `peek()` waiting for you.
        Decide how it should behave:

        - auto-append `LIMIT` when none is present (simple, but can silently truncate),
        - only guard row-returning `SELECT`s and leave aggregates alone (smarter), or
        - hard-cap fetched rows and **warn loudly** when the cap is hit (never silent).

        Implement it, then wire it into the results cell above.
        """
    )
    return


@app.cell
def _():
    # Scratch — add cells with the + button and explore.
    return


if __name__ == "__main__":
    app.run()
