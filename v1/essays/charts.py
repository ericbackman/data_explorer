"""SVG chart renderer with an optional, fail-closed face-marker layer.

Charts double as copyright-clean b-roll for the video. Featured outliers render as
a circular headshot IF the player has a cleared entry in the headshot pool;
otherwise a styled dot. No external deps -- hand-built SVG stays crisp at any
video resolution and animates cleanly later.

    python -m essays.charts
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pga.betting import DEFAULT_DB, closer_rankings
from pga.db import connect

from essays.headshots import attribution, marker_data_uri

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
CHART_DIR = _ROOT / "assets" / "charts"

_W, _H = 1280, 720
_L, _R, _T, _B = 120, 1180, 90, 610
_BG, _FG, _MUTE, _GRID = "#0f1419", "#e6edf3", "#7d8894", "#232b33"
_DOT, _HI, _LINE = "#5b6672", "#f0b429", "#ff5964"

FEATURED = ["Tiger Woods", "Rory McIlroy", "Scottie Scheffler", "Lee Westwood"]


def _sx(led: float, maxled: int) -> float:
    return _L + (led / maxled) * (_R - _L)


def _sy(pct: float) -> float:
    return _B - (pct / 100.0) * (_B - _T)


def render_closer_scatter(rows: list[dict], field_pct: float,
                          featured: list[str]) -> tuple[str, int, list[str]]:
    """Return (svg, n_faces, credit_lines). Faces used only where cleared."""
    maxled = max(r["led"] for r in rows)
    featured_set = set(featured)
    s = [f'<svg viewBox="0 0 {_W} {_H}" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="Inter, Segoe UI, sans-serif">',
         f'<rect width="{_W}" height="{_H}" fill="{_BG}"/>',
         f'<text x="{_L}" y="50" fill="{_FG}" font-size="30" font-weight="700">'
         f'Who actually closes the 54-hole lead</text>']

    # y gridlines + labels
    for p in (0, 25, 50, 75, 100):
        y = _sy(p)
        s.append(f'<line x1="{_L}" y1="{y:.0f}" x2="{_R}" y2="{y:.0f}" stroke="{_GRID}"/>')
        s.append(f'<text x="{_L - 14}" y="{y + 5:.0f}" fill="{_MUTE}" font-size="14" '
                 f'text-anchor="end">{p}%</text>')
    # x ticks
    for lv in range(0, maxled + 1, 5):
        x = _sx(lv, maxled)
        s.append(f'<text x="{x:.0f}" y="{_B + 30:.0f}" fill="{_MUTE}" font-size="14" '
                 f'text-anchor="middle">{lv}</text>')
    s.append(f'<text x="{(_L + _R) / 2:.0f}" y="{_H - 26:.0f}" fill="{_MUTE}" font-size="15" '
             f'text-anchor="middle">number of 54-hole leads (2005-2026, min 5)</text>')

    # field-average reference line
    fy = _sy(field_pct)
    s.append(f'<line x1="{_L}" y1="{fy:.0f}" x2="{_R}" y2="{fy:.0f}" stroke="{_LINE}" '
             f'stroke-dasharray="6 5" stroke-width="1.5" opacity="0.85"/>')
    s.append(f'<text x="{_R}" y="{fy - 9:.0f}" fill="{_LINE}" font-size="14" '
             f'text-anchor="end">field average {field_pct}%</text>')

    # background dots (non-featured)
    for r in rows:
        if r["player"] in featured_set:
            continue
        s.append(f'<circle cx="{_sx(r["led"], maxled):.1f}" cy="{_sy(r["convert_pct"]):.1f}" '
                 f'r="4" fill="{_DOT}"/>')

    # featured markers: face if cleared, else highlighted dot (fail closed)
    credits: list[str] = []
    faces = 0
    for name in featured:
        r = next((x for x in rows if x["player"] == name), None)
        if r is None:
            continue
        cx, cy = _sx(r["led"], maxled), _sy(r["convert_pct"])
        uri = marker_data_uri(name)
        if uri:
            faces += 1
            rad, cid = 26, f"clip{faces}"
            s.append(f'<clipPath id="{cid}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rad}"/></clipPath>')
            s.append(f'<image href="{uri}" x="{cx - rad:.1f}" y="{cy - rad:.1f}" '
                     f'width="{2 * rad}" height="{2 * rad}" preserveAspectRatio="xMidYMid slice" '
                     f'clip-path="url(#{cid})"/>')
            s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rad}" fill="none" '
                     f'stroke="{_HI}" stroke-width="3"/>')
            att = attribution(name)
            if att:
                credits.append(att)
            below = 46
        else:
            s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="9" fill="{_HI}" '
                     f'stroke="{_BG}" stroke-width="2"/>')
            below = 26
        label = name.split()[-1]
        s.append(f'<text x="{cx:.1f}" y="{cy - 36:.1f}" fill="{_FG}" font-size="16" '
                 f'font-weight="600" text-anchor="middle">{label}</text>')
        s.append(f'<text x="{cx:.1f}" y="{cy + below:.1f}" fill="{_MUTE}" font-size="12" '
                 f'text-anchor="middle">{r["won"]}/{r["led"]} - {r["convert_pct"]}%</text>')

    if credits:
        s.append(f'<text x="{_L}" y="{_H - 6:.0f}" fill="{_GRID}" font-size="10">'
                 f'Photos: {"  |  ".join(credits)}</text>')
    s.append("</svg>")
    return "\n".join(s), faces, credits


def render_card(kicker: str, big: str, sub: str, name: str = "",
                face_player: str = "", footnote: str = "") -> str:
    """A bold stat card: kicker, huge number, subtitle, optional headshot + name."""
    s = [f'<svg viewBox="0 0 {_W} {_H}" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="Inter, Segoe UI, sans-serif">',
         f'<rect width="{_W}" height="{_H}" fill="{_BG}"/>']
    cy = 330
    if face_player:
        uri = marker_data_uri(face_player)
        if uri:
            cx, fy, rad = 640, 195, 66
            s.append(f'<clipPath id="cardclip"><circle cx="{cx}" cy="{fy}" r="{rad}"/></clipPath>')
            s.append(f'<image href="{uri}" x="{cx - rad}" y="{fy - rad}" width="{2 * rad}" '
                     f'height="{2 * rad}" preserveAspectRatio="xMidYMid slice" clip-path="url(#cardclip)"/>')
            s.append(f'<circle cx="{cx}" cy="{fy}" r="{rad}" fill="none" stroke="{_HI}" stroke-width="3"/>')
            cy = 420
    s.append(f'<text x="640" y="{cy - 120}" fill="{_HI}" font-size="26" font-weight="600" '
             f'text-anchor="middle" letter-spacing="4">{kicker.upper()}</text>')
    s.append(f'<text x="640" y="{cy}" fill="{_FG}" font-size="150" font-weight="800" '
             f'text-anchor="middle">{big}</text>')
    s.append(f'<text x="640" y="{cy + 66}" fill="{_FG}" font-size="34" text-anchor="middle">{sub}</text>')
    if name:
        s.append(f'<text x="640" y="{cy + 118}" fill="{_MUTE}" font-size="24" text-anchor="middle">{name}</text>')
    if footnote:
        s.append(f'<text x="640" y="{_H - 44}" fill="{_MUTE}" font-size="19" text-anchor="middle">{footnote}</text>')
    s.append("</svg>")
    return "\n".join(s)


def render_bars(title: str, items: list[tuple], subtitle: str = "", highlight: str = "") -> str:
    """Horizontal bar chart. items = [(label, value_float, display_str), ...]."""
    s = [f'<svg viewBox="0 0 {_W} {_H}" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="Inter, Segoe UI, sans-serif">',
         f'<rect width="{_W}" height="{_H}" fill="{_BG}"/>',
         f'<text x="120" y="92" fill="{_FG}" font-size="40" font-weight="700">{title}</text>']
    maxv = max((v for _, v, _ in items), default=1) or 1
    n = max(len(items), 1)
    top, span, x0, barmax = 175, 470, 360, 720
    gap = span / n
    bh = min(58.0, gap * 0.62)
    for i, (label, v, disp) in enumerate(items):
        y = top + i * gap
        w = barmax * (v / maxv)
        col = _HI if (highlight and label == highlight) else _DOT
        s.append(f'<text x="{x0 - 20}" y="{y + bh * 0.7:.0f}" fill="{_FG}" font-size="24" '
                 f'text-anchor="end">{label}</text>')
        s.append(f'<rect x="{x0}" y="{y:.0f}" width="{w:.0f}" height="{bh:.0f}" rx="6" fill="{col}"/>')
        s.append(f'<text x="{x0 + w + 16:.0f}" y="{y + bh * 0.7:.0f}" fill="{_FG}" font-size="24" '
                 f'font-weight="600">{disp}</text>')
    if subtitle:
        s.append(f'<text x="120" y="{_H - 44}" fill="{_MUTE}" font-size="20">{subtitle}</text>')
    s.append("</svg>")
    return "\n".join(s)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Render the video-zero closer scatter chart.")
    ap.add_argument("--out", type=Path, default=CHART_DIR / "closer_scatter.svg")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = connect(DEFAULT_DB)
    try:
        rk = closer_rankings(conn, min_leads=5)
    finally:
        conn.close()

    svg, faces, credits = render_closer_scatter(rk["rows"], rk["field_pct"], FEATURED)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg, encoding="utf-8")
    print(f"wrote {args.out}  ({faces}/{len(FEATURED)} featured as faces, rest fail-closed to dots)")
    for c in credits:
        print("  credit:", c)


if __name__ == "__main__":
    main()
