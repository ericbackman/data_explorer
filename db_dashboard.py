"""Workspace database dashboard — a clean, visual inventory of every local DB.

One introspection, three outputs:
  (default)   -> db_dashboard.html         standalone dark-theme page for the browser
  --widget    -> db_dashboard.widget.html  chat-themed fragment for the /db-dashboard skill
  --json      -> stdout                     machine-readable inventory

    python db_dashboard.py            # standalone HTML
    python db_dashboard.py --open     # ...and open it
    python db_dashboard.py --widget   # chat-widget fragment (used by the skill)
    python db_dashboard.py --json     # raw inventory
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import pathlib
import sqlite3
import webbrowser

WORKSPACE = pathlib.Path(__file__).resolve().parent.parent  # C:\Users\ericb\Github
HERE = pathlib.Path(__file__).resolve().parent
OUT_HTML = HERE / "db_dashboard.html"
OUT_WIDGET = HERE / "db_dashboard.widget.html"

# Workspace-relative DB paths, grouped by interest. (label, category, rel_path)
MANIFEST = [
    ("NBA box scores",       "NBA",      "data_explorer/nba/data/nba.db"),
    ("NBA comebacks",        "NBA",      "data_explorer/nba_comebacks.db"),
    ("NBA playoff comebacks","NBA",      "data_explorer/nba_playoff_comebacks.db"),
    ("NFL (nflverse)",       "NFL",      "data_explorer/nfl/data/nfl.db"),
    ("NHL box scores",       "NHL",      "data_explorer/nhl/data/nhl.db"),
    ("MLB draft + careers",  "MLB",      "data_explorer/mlb/data/mlb_draft.db"),
    ("PGA Tour history",     "Golf",     "data_explorer/pga/data/pga.db"),
    ("Betting odds history", "Betting",  "betting_stuff/data/odds_history.db"),
    ("MTG deckbuilding",     "Games",    "MTG-Deckbuilding/data/mtg.db"),
    ("Life tracker",         "Personal", "life_tracker/life_tracker.db"),
    ("Video-game stats",     "Personal", "videogame-stattracker/stats.db"),
]

# Mid-ramp hexes (readable in both light & dark) for category accents.
CATEGORY_COLOR = {
    "NBA": "#D85A30", "NFL": "#1D9E75", "NHL": "#185FA5", "MLB": "#B3485D",
    "Golf": "#639922", "Betting": "#BA7517", "Games": "#7F77DD", "Personal": "#378ADD",
}

DATEISH = ("season", "game_date", "date", "year", "event_date",
           "start_date", "pulled_at", "calendar_year")
INTERNAL = {"sqlite_stat1", "sqlite_stat4", "sqlite_sequence", "sqlite_master"}


def _size(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} GB"


def inspect_db(path: pathlib.Path) -> dict:
    info = {"size": path.stat().st_size,
            "mtime": datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"),
            "tables": [], "total_rows": 0}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")  # wait out a concurrent writer (e.g. a backfill)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            if r[0] not in INTERNAL]
        for t in names:
            try:
                rows = conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
            except sqlite3.Error:
                continue
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info('{t}')")]
            coverage = ""
            for d in DATEISH:
                if d in cols:
                    try:
                        lo, hi = conn.execute(f"SELECT MIN({d}), MAX({d}) FROM '{t}'").fetchone()
                        if lo is not None:
                            coverage = f"{lo} → {hi}" if lo != hi else str(lo)
                        break
                    except sqlite3.Error:
                        pass
            info["tables"].append({"name": t, "rows": rows, "coverage": coverage})
            info["total_rows"] += rows
    finally:
        conn.close()
    return info


def collect_inventory() -> dict:
    dbs, missing = [], []
    for label, category, rel in MANIFEST:
        path = WORKSPACE / rel
        if not path.exists():
            missing.append(rel)
            continue
        info = inspect_db(path)
        info.update({"label": label, "category": category, "rel_path": rel})
        dbs.append(info)
    dbs.sort(key=lambda d: -d["total_rows"])
    totals = {
        "databases": len(dbs),
        "size": sum(d["size"] for d in dbs),
        "rows": sum(d["total_rows"] for d in dbs),
        "tables": sum(len(d["tables"]) for d in dbs),
    }
    return {"dbs": dbs, "missing": missing, "totals": totals}


# ── renderer 1: standalone dark-theme page (browser) ──────────────────────────
def render_standalone(inv: dict, generated: str) -> str:
    dbs, t = inv["dbs"], inv["totals"]
    cards = []
    for d in dbs:
        color = CATEGORY_COLOR.get(d["category"], "#8b949e")
        max_rows = max((tb["rows"] for tb in d["tables"]), default=1) or 1
        rows_html = []
        for tb in sorted(d["tables"], key=lambda x: -x["rows"]):
            frac = math.log10(tb["rows"] + 1) / math.log10(max_rows + 1) if max_rows > 1 else 1
            cov = f'<div class="tcov">{html.escape(tb["coverage"])}</div>' if tb["coverage"] else ""
            rows_html.append(f"""
              <div class="trow">
                <div class="tleft"><div class="tname">{html.escape(tb['name'])}</div>
                  <div class="tbar"><span style="width:{max(frac*100,3):.0f}%;background:{color}"></span></div></div>
                <div class="tright"><div class="tnum">{tb['rows']:,}</div>{cov}</div>
              </div>""")
        cards.append(f"""
        <div class="card">
          <div class="card-head">
            <span class="pill" style="background:{color}1a;color:{color};border-color:{color}55">{d['category']}</span>
            <h2>{html.escape(d['label'])}</h2><span class="size">{_size(d['size'])}</span></div>
          <div class="path">{html.escape(d['rel_path'])}</div>
          <div class="stats"><span><b>{d['total_rows']:,}</b> rows</span>
            <span><b>{len(d['tables'])}</b> table{"s" if len(d['tables']) != 1 else ""}</span><span>updated {d['mtime']}</span></div>
          <div class="tables">{''.join(rows_html)}</div>
        </div>""")
    miss = (f'<div class="missing">Not found (skipped): <ul>'
            + "".join(f"<li>{html.escape(m)}</li>" for m in inv["missing"]) + "</ul></div>"
            if inv["missing"] else "")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Data Lab — Database Inventory</title>
<style>
  :root {{ color-scheme: dark; }} * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0d1117; color:#e6edf3;
    font-family:-apple-system,"Segoe UI",system-ui,sans-serif; line-height:1.4; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:32px 20px 64px; }}
  header h1 {{ font-size:24px; margin:0 0 4px; letter-spacing:-.3px; }}
  header .sub {{ color:#8b949e; font-size:13px; margin-bottom:24px; }}
  .summary {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:28px; }}
  .stat {{ flex:1; min-width:140px; background:#161b22; border:1px solid #30363d;
    border-radius:12px; padding:16px 18px; }}
  .stat .n {{ font-size:28px; font-weight:700; letter-spacing:-.5px; }}
  .stat .l {{ color:#8b949e; font-size:12px; text-transform:uppercase; letter-spacing:.5px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:16px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:18px; }}
  .card:hover {{ border-color:#484f58; }}
  .card-head {{ display:flex; align-items:center; gap:10px; margin-bottom:2px; }}
  .card-head h2 {{ font-size:16px; margin:0; flex:1; }}
  .pill {{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.5px;
    padding:3px 8px; border-radius:20px; border:1px solid; }}
  .size {{ color:#8b949e; font-size:12px; font-variant-numeric:tabular-nums; }}
  .path {{ color:#6e7681; font-size:11px; font-family:ui-monospace,Menlo,Consolas,monospace;
    margin-bottom:10px; word-break:break-all; }}
  .stats {{ display:flex; gap:14px; font-size:12px; color:#8b949e; margin-bottom:14px;
    padding-bottom:12px; border-bottom:1px solid #21262d; }}
  .stats b {{ color:#e6edf3; font-variant-numeric:tabular-nums; }}
  .trow {{ display:grid; grid-template-columns:1fr 88px; align-items:center; gap:12px;
    padding:5px 0; font-size:12px; }}
  .tleft {{ min-width:0; }}
  .tname {{ font-family:ui-monospace,Menlo,Consolas,monospace; color:#c9d1d9;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .tbar {{ height:4px; background:#21262d; border-radius:3px; margin-top:4px; overflow:hidden; }}
  .tbar span {{ display:block; height:100%; border-radius:3px; }}
  .tright {{ text-align:right; }}
  .tnum {{ font-variant-numeric:tabular-nums; color:#e6edf3; }}
  .tcov {{ color:#8b949e; font-size:10px; font-variant-numeric:tabular-nums; margin-top:1px; }}
  .missing {{ margin-top:28px; color:#6e7681; font-size:12px; }} .missing ul {{ margin:6px 0 0; }}
  footer {{ margin-top:32px; color:#6e7681; font-size:11px; text-align:center; }}
</style></head>
<body><div class="wrap">
  <header><h1>Data Lab — Database Inventory</h1>
    <div class="sub">{t['databases']} databases · generated {generated}</div></header>
  <div class="summary">
    <div class="stat"><div class="n">{t['databases']}</div><div class="l">Databases</div></div>
    <div class="stat"><div class="n">{_size(t['size'])}</div><div class="l">Total size</div></div>
    <div class="stat"><div class="n">{t['rows']:,}</div><div class="l">Total rows</div></div>
    <div class="stat"><div class="n">{t['tables']}</div><div class="l">Tables</div></div></div>
  <div class="grid">{''.join(cards)}</div>
  {miss}
  <footer>Regenerate: <code>python db_dashboard.py</code></footer>
</div></body></html>"""


# ── renderer 2: chat-widget fragment (Claude Code, theme-adaptive) ────────────
def render_widget(inv: dict) -> str:
    dbs, t = inv["dbs"], inv["totals"]
    max_rows = max((d["total_rows"] for d in dbs), default=1) or 1

    metrics = "".join(f"""
      <div style="background:var(--color-background-secondary);border-radius:var(--border-radius-md);padding:1rem;">
        <div style="font-size:13px;color:var(--color-text-secondary);">{lbl}</div>
        <div style="font-size:24px;font-weight:500;">{val}</div></div>"""
        for lbl, val in (("Databases", t["databases"]), ("Total size", _size(t["size"])),
                         ("Total rows", f"{t['rows']:,}"), ("Tables", t["tables"])))

    rows = []
    for d in dbs:
        color = CATEGORY_COLOR.get(d["category"], "var(--color-text-tertiary)")
        frac = math.log10(d["total_rows"] + 1) / math.log10(max_rows + 1) if max_rows > 1 else 1
        cov = next((tb["coverage"] for tb in sorted(d["tables"], key=lambda x: -x["rows"])
                    if tb["coverage"]), "")
        cov_html = (f'<span style="margin-left:auto;font-family:var(--font-mono);">'
                    f'{html.escape(cov)}</span>' if cov else "")
        rows.append(f"""
      <div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-lg);padding:12px 16px;">
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="width:9px;height:9px;border-radius:50%;background:{color};flex:none;"></span>
          <span style="font-weight:500;">{html.escape(d['label'])}</span>
          <span style="margin-left:auto;color:var(--color-text-secondary);font-size:13px;">{_size(d['size'])}</span></div>
        <div style="margin:9px 0 7px;height:6px;background:var(--color-background-secondary);border-radius:3px;overflow:hidden;">
          <span style="display:block;height:100%;width:{max(frac*100,4):.0f}%;background:{color};"></span></div>
        <div style="display:flex;gap:14px;font-size:12px;color:var(--color-text-tertiary);">
          <span>{d['total_rows']:,} rows</span><span>{len(d['tables'])} table{"s" if len(d['tables']) != 1 else ""}</span>{cov_html}</div>
      </div>""")

    return f"""<h2 class="sr-only" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);">Inventory of {t['databases']} local databases totaling {_size(t['size'])} across {t['rows']:,} rows.</h2>
<div style="padding:0.5rem 0;">
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:1rem;">{metrics}</div>
  <div style="display:flex;flex-direction:column;gap:8px;">{''.join(rows)}</div>
</div>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the workspace DB dashboard")
    ap.add_argument("--widget", action="store_true", help="write chat-widget fragment")
    ap.add_argument("--json", action="store_true", help="print inventory as JSON")
    ap.add_argument("--open", action="store_true", help="open the standalone HTML when done")
    args = ap.parse_args()

    inv = collect_inventory()
    if args.json:
        print(json.dumps(inv, indent=2))
        return
    if args.widget:
        OUT_WIDGET.write_text(render_widget(inv), encoding="utf-8")
        print(f"wrote {OUT_WIDGET}")
        return

    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    OUT_HTML.write_text(render_standalone(inv, generated), encoding="utf-8")
    print(f"wrote {OUT_HTML}  ({inv['totals']['databases']} DBs, {inv['totals']['rows']:,} rows)")
    if args.open:
        webbrowser.open(OUT_HTML.as_uri())


if __name__ == "__main__":
    main()
