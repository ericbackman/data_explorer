"""Render an OutcomeTree as a Mermaid flowchart or a self-contained SVG.

Both renderers walk the same IR from ``expand.py``. Mermaid is best for
embedding in markdown/docs; the SVG is a standalone shareable graphic with no
external dependency (no graphviz, no JS).
"""

from __future__ import annotations

import html
import logging

from .expand import Decision, Outcome, OutcomeTree, Node

logger = logging.getLogger(__name__)

_KIND_COLOR = {  # (fill, stroke) per owned-asset kind
    "pick": ("#e6f4ea", "#34a853"),         # green — unconditional
    "conditional": ("#fef7e0", "#f9ab00"),  # amber — protected/rolling
    "swap": ("#e8f0fe", "#4285f4"),         # blue  — swap right
}

# ---------------------------------------------------------------------------
# Mermaid
# ---------------------------------------------------------------------------
def to_mermaid(tree: OutcomeTree) -> str:
    """Return Mermaid ``flowchart TD`` source for the whole trade."""
    lines = ["flowchart TD", f'  %% {tree.title}']
    counter = [0]

    def new_id() -> str:
        counter[0] += 1
        return f"n{counter[0]}"

    def walk(node: Node) -> str:
        nid = new_id()
        if isinstance(node, Outcome):
            text = node.result + (f"\\n{node.detail}" if node.detail else "")
            lines.append(f'  {nid}["{_mm(text)}"]')
            return nid
        # Decision → rhombus, then one edge per branch.
        lines.append(f'  {nid}{{"{_mm(node.prompt)}"}}')
        for br in node.branches:
            child = walk(br.node)
            lines.append(f'  {nid} -->|"{_mm(br.condition)}"| {child}')
        return nid

    for caption, root in tree.roots:
        sub = new_id()
        lines.append(f'  subgraph {sub}["{_mm(caption)}"]')
        walk(root)
        lines.append("  end")
    return "\n".join(lines)


def _mm(text: str) -> str:
    """Escape text for a Mermaid label."""
    return text.replace('"', "'").replace("—", "-")


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
_NODE_H = 48
_V_GAP = 96          # vertical distance between levels (room for edge labels)
_H_GAP = 34          # horizontal gap between adjacent leaves
_PAD = 28            # canvas margin
_CHAR_W = 7.2        # approx px per character at 13px
_WRAP = 26           # wrap node text near this many chars
_CAPTION_H = 34


def to_svg(tree: OutcomeTree, path: str | None = None) -> str:
    """Render the trade to a self-contained SVG string; write it if ``path``."""
    groups: list[str] = []
    y_cursor = _PAD
    max_w = 0.0
    for caption, root in tree.roots:
        placed, edges, w, h = _layout(root)
        body = _svg_group(caption, placed, edges, y_cursor, w)
        groups.append(body)
        y_cursor += _CAPTION_H + h + _V_GAP  # gap between stacked assets
        max_w = max(max_w, w)

    width = max_w + 2 * _PAD
    height = y_cursor
    svg = _svg_document(tree.title, width, height, "\n".join(groups))
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        logger.info("wrote SVG flowchart to %s (%d assets)", path, len(tree.roots))
    return svg


def _layout(root: Node):
    """Top-down tidy layout: depth → row, leaf order → column.

    Returns (placed_nodes, edges, width, height). Each placed node is a dict
    with pixel center (cx, cy) and box size (w, h).
    """
    placed: list[dict] = []
    edges: list[tuple[int, int, str]] = []
    leaf_cursor = [0.0]
    max_depth = [0]

    def visit(node: Node, depth: int) -> int:
        nid = len(placed)
        lines = _wrap(_node_text(node))
        w = max(120.0, min(240.0, max(len(ln) for ln in lines) * _CHAR_W + 24))
        h = max(_NODE_H, 22 + len(lines) * 16)
        placed.append({"lines": lines, "w": w, "h": h, "kind": _kind(node)})
        max_depth[0] = max(max_depth[0], depth)

        if isinstance(node, Outcome):
            cx = leaf_cursor[0] + w / 2
            leaf_cursor[0] += w + _H_GAP
        else:
            centers = []
            for br in node.branches:
                cid = visit(br.node, depth + 1)
                edges.append((nid, cid, br.condition))
                centers.append(placed[cid]["cx"])
            cx = (min(centers) + max(centers)) / 2

        placed[nid]["cx"] = cx
        placed[nid]["cy"] = depth * _V_GAP + _NODE_H / 2
        return nid

    visit(root, 0)
    width = leaf_cursor[0] - _H_GAP if placed else 0.0
    height = max_depth[0] * _V_GAP + _NODE_H
    return placed, edges, width, height


def _svg_group(caption: str, placed: list[dict], edges, y_off: float, width: float) -> str:
    parts: list[str] = [
        f'<text x="0" y="{y_off + 20:.0f}" class="caption">{html.escape(caption)}</text>'
    ]
    top = y_off + _CAPTION_H

    # Edges first so nodes draw on top.
    for pid, cid, label in edges:
        p, c = placed[pid], placed[cid]
        x1, y1 = p["cx"], top + p["cy"] + p["h"] / 2
        x2, y2 = c["cx"], top + c["cy"] - c["h"] / 2
        midx, midy = (x1 + x2) / 2, (y1 + y2) / 2
        parts.append(
            f'<path d="M {x1:.1f} {y1:.1f} C {x1:.1f} {midy:.1f} {x2:.1f} {midy:.1f} '
            f'{x2:.1f} {y2:.1f}" class="edge"/>'
        )
        parts.append(
            f'<rect x="{midx - _label_w(label) / 2:.1f}" y="{midy - 11:.1f}" '
            f'width="{_label_w(label):.1f}" height="18" rx="4" class="elabelbg"/>'
        )
        parts.append(
            f'<text x="{midx:.1f}" y="{midy + 3:.1f}" class="elabel">{html.escape(label)}</text>'
        )

    for n in placed:
        cx, cy, w, h = n["cx"], top + n["cy"], n["w"], n["h"]
        cls = {"decision": "decision", "convey": "convey", "fallback": "fallback"}[n["kind"]]
        parts.append(
            f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" rx="10" class="node {cls}"/>'
        )
        line_h = 16
        start_y = cy - (len(n["lines"]) - 1) * line_h / 2 + 4
        for i, ln in enumerate(n["lines"]):
            parts.append(
                f'<text x="{cx:.1f}" y="{start_y + i * line_h:.1f}" '
                f'class="nodetext">{html.escape(ln)}</text>'
            )
    return "\n".join(parts)


def _svg_document(title: str, width: float, height: float, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" \
font-family="'Segoe UI', system-ui, sans-serif">
  <style>
    .title {{ font-size: 18px; font-weight: 700; fill: #1a2233; }}
    .caption {{ font-size: 13px; font-weight: 600; fill: #5b6472; text-transform: uppercase; letter-spacing: .04em; }}
    .node {{ stroke-width: 1.5; }}
    .decision {{ fill: #e8f0fe; stroke: #4285f4; }}
    .convey {{ fill: #e6f4ea; stroke: #34a853; }}
    .fallback {{ fill: #fef7e0; stroke: #f9ab00; }}
    .nodetext {{ font-size: 13px; fill: #202430; text-anchor: middle; }}
    .edge {{ fill: none; stroke: #9aa0ab; stroke-width: 1.5; }}
    .elabelbg {{ fill: #ffffff; stroke: #d8dbe0; }}
    .elabel {{ font-size: 11px; fill: #4a5160; text-anchor: middle; }}
  </style>
  <rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>
  <text x="{_PAD}" y="24" class="title">{html.escape(title)}</text>
  <g transform="translate({_PAD}, 12)">
{body}
  </g>
</svg>"""


# ---------------------------------------------------------------------------
# HTML (browser lays out text — no manual measurement, no overlap)
# ---------------------------------------------------------------------------
_HTML_CSS = """<style>
.tf { font-family: 'Segoe UI', system-ui, sans-serif; color: #202430; line-height: 1.35; }
.tf-title { font-size: 17px; font-weight: 700; margin: 2px 0; }
.tf-caption { font-size: 11px; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: #5b6472; margin: 18px 0 10px; }
.tf-card { display: inline-block; border-radius: 10px; padding: 8px 13px;
  border: 1.5px solid; max-width: 340px; box-sizing: border-box; }
.tf-card.decision { background: #e8f0fe; border-color: #4285f4; }
.tf-card.convey   { background: #e6f4ea; border-color: #34a853; }
.tf-card.fallback { background: #fef7e0; border-color: #f9ab00; }
.tf-main { font-size: 13.5px; font-weight: 600; }
.tf-sub  { font-size: 11.5px; color: #5b6472; margin-top: 3px; }
.tf-children { margin-left: 20px; border-left: 2px solid #d3d7de; }
.tf-child { position: relative; padding-left: 22px; margin: 14px 0; }
.tf-child::before { content: ''; position: absolute; left: 0; top: 19px;
  width: 20px; height: 2px; background: #d3d7de; }
.tf-edge { display: inline-block; background: #fff; border: 1px solid #d8dbe0;
  border-radius: 12px; padding: 2px 10px; font-size: 11px; color: #4a5160; margin-bottom: 7px; }
</style>"""


def to_html(tree: OutcomeTree) -> str:
    """Render the trade as a self-contained HTML fragment (no external deps).

    Uses an indented connector-tree so the browser handles all text layout —
    boxes grow to fit their text and branches can never overlap.
    """
    parts = [_HTML_CSS, '<div class="tf">',
             f'<div class="tf-title">{html.escape(tree.title)}</div>']
    for caption, root in tree.roots:
        parts.append(f'<div class="tf-caption">{html.escape(caption)}</div>')
        parts.append(_html_node(root))
    parts.append("</div>")
    return "\n".join(parts)


def _html_node(node: Node) -> str:
    if isinstance(node, Outcome):
        sub = f'<div class="tf-sub">{html.escape(node.detail)}</div>' if node.detail else ""
        return (f'<div class="tf-card {_kind(node)}">'
                f'<div class="tf-main">{html.escape(node.result)}</div>{sub}</div>')
    children = "".join(
        f'<div class="tf-child"><span class="tf-edge">{html.escape(br.condition)}</span>'
        f'<div>{_html_node(br.node)}</div></div>'
        for br in node.branches
    )
    return (f'<div><div class="tf-card decision">'
            f'<div class="tf-main">{html.escape(node.prompt)}</div></div>'
            f'<div class="tf-children">{children}</div></div>')


# ---------------------------------------------------------------------------
# Ownership board
# ---------------------------------------------------------------------------
def ownership_svg(ledger: dict, title: str, path: str | None = None) -> str:
    """Render a 'who owns what' board: one card per team, one chip per asset.

    ``ledger`` is the dict from ``ownership.ownership`` (team → OwnedAsset list).
    """
    card_w = 660
    row_h = 30
    head_h = 38
    gap = 20
    x = _PAD

    # Layout pass → total height.
    y = 58
    cards: list[str] = []
    for team, assets in ledger.items():
        h = head_h + len(assets) * row_h + 12
        cards.append(_ownership_card(team, assets, x, y, card_w, head_h, row_h))
        y += h + gap
    width = card_w + 2 * _PAD
    height = y + _PAD

    body = "\n".join(cards)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" \
font-family="'Segoe UI', system-ui, sans-serif">
  <style>
    .btitle {{ font-size: 18px; font-weight: 700; fill: #1a2233; }}
    .team {{ font-size: 15px; font-weight: 700; fill: #ffffff; }}
    .chip {{ font-size: 13px; fill: #202430; }}
    .card {{ fill: #ffffff; stroke: #e2e5ea; stroke-width: 1.5; }}
    .cardhead {{ fill: #2b3140; }}
  </style>
  <rect x="0" y="0" width="{width}" height="{height:.0f}" fill="#ffffff"/>
  <text x="{_PAD}" y="34" class="btitle">{html.escape(title)}</text>
{body}
</svg>"""
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        logger.info("wrote ownership board to %s (%d teams)", path, len(ledger))
    return svg


_BOARD_CSS = """<style>
.ob { font-family: 'Segoe UI', system-ui, sans-serif; color: #202430; }
.ob-title { font-size: 17px; font-weight: 700; margin: 2px 0 14px; }
.ob-card { border: 1.5px solid #e2e5ea; border-radius: 12px; overflow: hidden;
  margin-bottom: 16px; max-width: 640px; }
.ob-head { background: #2b3140; color: #fff; font-size: 14px; font-weight: 700;
  padding: 9px 16px; }
.ob-row { display: flex; align-items: center; gap: 11px; padding: 8px 16px;
  font-size: 13px; border-top: 1px solid #f0f1f4; }
.ob-dot { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid;
  flex: none; }
.ob-pick { background: #e6f4ea; border-color: #34a853; }
.ob-conditional { background: #fef7e0; border-color: #f9ab00; }
.ob-swap { background: #e8f0fe; border-color: #4285f4; }
.ob-legend { font-size: 11.5px; color: #5b6472; margin-top: 4px; }
.ob-legend span { margin-right: 14px; }
</style>"""


def ownership_html(ledger: dict, title: str) -> str:
    """Render the who-owns-what board as a self-contained HTML fragment."""
    parts = [_BOARD_CSS, '<div class="ob">', f'<div class="ob-title">{html.escape(title)}</div>']
    for team, assets in ledger.items():
        n = len(assets)
        rows = "".join(
            f'<div class="ob-row"><span class="ob-dot ob-{a.kind}"></span>'
            f'<span>{html.escape(a.detail)}</span></div>'
            for a in assets
        )
        parts.append(
            f'<div class="ob-card"><div class="ob-head">{html.escape(team)} · '
            f'controls {n} asset{"s" if n != 1 else ""}</div>{rows}</div>'
        )
    parts.append(
        '<div class="ob-legend"><span>🟢 unconditional pick</span>'
        '<span>🟡 conditional</span><span>🔵 swap right</span></div></div>'
    )
    return "\n".join(parts)


def _ownership_card(team, assets, x, y, w, head_h, row_h) -> str:
    h = head_h + len(assets) * row_h + 12
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" class="card"/>',
        f'<path d="M {x} {y + 12} q 0 -12 12 -12 l {w - 24} 0 q 12 0 12 12 l 0 {head_h - 12} '
        f'l {-w} 0 z" class="cardhead"/>',
        f'<text x="{x + 16}" y="{y + 25}" class="team">{html.escape(team)} '
        f'&#183; controls {len(assets)} asset{"s" if len(assets) != 1 else ""}</text>',
    ]
    ry = y + head_h + 6
    for a in assets:
        fill, stroke = _KIND_COLOR.get(a.kind, ("#eee", "#999"))
        cy = ry + row_h / 2
        parts.append(
            f'<circle cx="{x + 22}" cy="{cy:.0f}" r="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{x + 40}" y="{cy + 4:.0f}" class="chip">{html.escape(a.detail)}</text>'
        )
        ry += row_h
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Slot strip: one pick across all 30 landing slots
# ---------------------------------------------------------------------------
# Mobile-first "trade card": ~380px wide so it reads like a phone graphic.
_STRIP_CSS = """<style>
.tc { font-family: 'Segoe UI', system-ui, sans-serif; color: #1a2233;
  max-width: 380px; margin: 0 auto; background: #fff; border: 1px solid #e6e8ec;
  border-radius: 16px; padding: 15px 15px 16px; box-sizing: border-box; }
.tc-title { font-size: 16px; font-weight: 800; line-height: 1.2; }
.tc-sub { font-size: 12px; color: #5b6472; margin-top: 2px; }
.tc-year { font-size: 11px; font-weight: 800; color: #5b6472; margin: 15px 0 6px;
  text-transform: uppercase; letter-spacing: .06em; }
.tc-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; }
.tc-cell { position: relative; border-radius: 7px; padding: 5px 1px 5px;
  text-align: center; min-height: 40px; box-sizing: border-box; }
.tc-slot { font-size: 14px; font-weight: 800; line-height: 1; }
.tc-ab { font-size: 8px; font-weight: 800; margin-top: 2px; letter-spacing: .02em; opacity: .95; }
.tc-keep::after { content: ''; position: absolute; inset: 0; border-radius: 7px;
  pointer-events: none;
  background: repeating-linear-gradient(45deg, rgba(255,255,255,.30) 0 4px, rgba(255,255,255,0) 4px 8px); }
.tc-legend { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 11px; }
.tc-leg { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: #3a4150; }
.tc-sw { width: 14px; height: 14px; border-radius: 4px; flex: none; position: relative; }
.tc-sw.k::after { content: ''; position: absolute; inset: 0; border-radius: 4px;
  background: repeating-linear-gradient(45deg, rgba(255,255,255,.45) 0 3px, rgba(255,255,255,0) 3px 6px); }
.tc-note { margin-top: 11px; background: #f5f6f8; border-radius: 11px;
  padding: 9px 11px; font-size: 11.5px; line-height: 1.4; color: #3a4150; }
.tc-note b { color: #1a2233; }
.tc-arrow { color: #98a0ab; }
</style>"""


def slot_strip_html(strips: list, title: str, subtitle: str = "") -> str:
    """Render a mobile trade card: each landing slot 1..30 colored by team.

    Convey slots take the receiving team's color; slots that DON'T convey take
    the *origin* team's color (they keep it), differentiated by a diagonal
    stripe. A footer note names what a non-conveyance leads to.
    """
    from .teams import color

    parts = [_STRIP_CSS, '<div class="tc">', f'<div class="tc-title">{html.escape(title)}</div>']
    if subtitle:
        parts.append(f'<div class="tc-sub">{html.escape(subtitle)}</div>')

    multi = len(strips) > 1
    for s in strips:
        to_bg, to_fg = color(s.to)
        keep_bg, keep_fg = color(s.origin)
        if multi:
            parts.append(f'<div class="tc-year">If it lands in {s.year}…</div>')

        cells = []
        for c in s.cells:
            if c.kind == "convey":
                cells.append(_strip_cell(c.slot, s.to, to_bg, to_fg, keep=False))
            else:
                cells.append(_strip_cell(c.slot, s.origin, keep_bg, keep_fg, keep=True))
        parts.append('<div class="tc-grid">' + "".join(cells) + "</div>")

        conv, prot = _fmt_run(s.convey_slots), _fmt_run(s.protected_slots)
        parts.append(
            '<div class="tc-legend">'
            f'<div class="tc-leg"><span class="tc-sw" style="background:{to_bg}"></span>'
            f'<span><b>{conv}</b> → conveys to {html.escape(s.to)}</span></div>'
            f'<div class="tc-leg"><span class="tc-sw k" style="background:{keep_bg}"></span>'
            f'<span><b>{prot}</b> → {html.escape(s.origin)} keeps it</span></div></div>'
        )
        parts.append(f'<div class="tc-note">{_strip_note(s, multi)}</div>')

    parts.append("</div>")
    return "\n".join(parts)


def _strip_cell(slot: int, ab: str, bg: str, fg: str, keep: bool) -> str:
    kc = " tc-keep" if keep else ""
    return (f'<div class="tc-cell{kc}" style="background:{bg};color:{fg}">'
            f'<div class="tc-slot">{slot}</div><div class="tc-ab">{html.escape(ab)}</div></div>')


def _strip_note(s, multi: bool) -> str:
    """The 'if it doesn't convey' consequence — the different-pick outcome."""
    prot = _fmt_run(s.protected_slots)
    rolls = any(c.kind == "roll" for c in s.cells)
    if rolls:
        nxt = s.rolls_to if s.rolls_to is not None else s.year + 1
        return (f'<b>Doesn\'t convey</b> (picks {prot}): {html.escape(s.origin)} keeps it '
                f'and the obligation <b>rolls to {nxt}</b> ↓')
    return (f'<b>Doesn\'t convey</b> (picks {prot}): {html.escape(s.origin)} keeps its pick — '
            f'instead, {html.escape(s.fallback)}.')


def _fmt_run(slots: list) -> str:
    """Compress a sorted slot list to ranges, e.g. [9,10,...,30] -> '9–30'."""
    if not slots:
        return "—"
    out, start, prev = [], slots[0], slots[0]
    for s in slots[1:]:
        if s == prev + 1:
            prev = s
            continue
        out.append(f"{start}–{prev}" if start != prev else f"{start}")
        start = prev = s
    out.append(f"{start}–{prev}" if start != prev else f"{start}")
    return ", ".join(out)


# ---------------------------------------------------------------------------
# Full-draft ownership board (grid)
# ---------------------------------------------------------------------------
_GRID_CSS = """<style>
.db { font-family: 'Segoe UI', system-ui, sans-serif; color: #202430; }
.db-title { font-size: 17px; font-weight: 700; margin: 2px 0 3px; }
.db-sub { font-size: 12px; color: #5b6472; margin-bottom: 12px; }
.db-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.db-cell { position: relative; border-radius: 9px; padding: 9px 10px; min-height: 60px;
  box-sizing: border-box; overflow: hidden; }
.db-origin { font-size: 15px; font-weight: 800; letter-spacing: .02em; }
.db-arrow { font-size: 11.5px; font-weight: 600; opacity: .95; margin-top: 2px; }
.db-badge { display: inline-block; margin-top: 5px; font-size: 10px; font-weight: 700;
  background: rgba(255,255,255,.9); color: #202430; border-radius: 9px; padding: 1px 7px; }
.db-own { outline: 1px dashed rgba(255,255,255,.35); outline-offset: -4px; }
.db-legend { font-size: 11.5px; color: #5b6472; margin-top: 12px; }
.db-legend b { color: #202430; }
</style>"""


def board_html(cells: dict, title: str, subtitle: str = "", columns: int = 6) -> str:
    """Render a {team: PickCell} board as a color-coded grid, one cell per pick.

    Each cell is colored by the *controlling* team. Untraded picks are dashed;
    traded picks show '→ owner' and a condition badge.
    """
    from .teams import color  # local import to avoid a hard cycle

    order = sorted(cells)
    body = []
    for team in order:
        c = cells[team]
        bg, fg = color(c.controller)
        arrow = "" if not c.traded else (
            f'<div class="db-arrow">→ {html.escape(c.controller)}</div>'
            if c.controller != c.origin else '<div class="db-arrow">⇄ swap</div>'
        )
        badge = f'<div class="db-badge">{html.escape(_badge(c))}</div>' if c.condition else ""
        own_cls = " db-own" if not c.traded else ""
        tip = html.escape(c.condition) if c.condition else ""
        body.append(
            f'<div class="db-cell{own_cls}" style="background:{bg};color:{fg}" title="{tip}">'
            f'<div class="db-origin">{html.escape(c.origin)}</div>{arrow}{badge}</div>'
        )

    grid_style = f"grid-template-columns: repeat({columns}, 1fr);"
    sub = f'<div class="db-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    return (
        _GRID_CSS.replace("repeat(6, 1fr)", f"repeat({columns}, 1fr)")
        + f'<div class="db"><div class="db-title">{html.escape(title)}</div>{sub}'
        + f'<div class="db-grid" style="{grid_style}">' + "".join(body) + "</div>"
        + '<div class="db-legend">Cells colored by <b>controlling</b> team. '
        + 'Dashed = team keeps its own pick. <b>→</b> = owed to another team '
        + '(badge shows the protection). <b>⇄</b> = swap right.</div></div>'
    )


def _badge(cell) -> str:
    """Short badge text from a cell's condition."""
    if cell.swap and cell.controller == cell.origin:
        return "swap"
    if cell.conditional and cell.condition:
        # First clause of the protection, e.g. "top-8 protected".
        return cell.condition.split(" →")[0].split(",")[0]
    return "traded"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _node_text(node: Node) -> str:
    if isinstance(node, Outcome):
        return node.result
    return node.prompt


def _kind(node: Node) -> str:
    if isinstance(node, Decision):
        return "decision"
    return "fallback" if node.tone == "fallback" else "convey"


def _wrap(text: str) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > _WRAP:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [text]


def _label_w(label: str) -> float:
    return len(label) * 6.0 + 12
