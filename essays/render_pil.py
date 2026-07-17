"""Pillow frame renderer for the video (no SVG rasterizer available here).

Produces 1280x720 PNGs directly: bold stat cards, horizontal bar charts, and the
closer scatter -- pasting the real cleared headshot files as circular markers.
render_chapter() maps each script chapter to the right visual.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from essays.headshots import headshot_path

W, H = 1280, 720
BG = (15, 20, 25)
FG = (230, 237, 243)
MUTE = (125, 136, 148)
GRID = (35, 43, 51)
DOT = (91, 102, 114)
HI = (240, 180, 41)
LINE = (255, 89, 100)

FEATURED = ["Tiger Woods", "Rory McIlroy", "Scottie Scheffler", "Lee Westwood"]

_FONT_DIR = Path("C:/Windows/Fonts")
_FONT_FILES = {
    "black": ["seguibl.ttf", "arialbd.ttf", "arial.ttf"],
    "semibold": ["seguisb.ttf", "arialbd.ttf", "arial.ttf"],
    "regular": ["segoeui.ttf", "arial.ttf"],
}


@lru_cache(maxsize=64)
def _font(size: int, kind: str = "regular") -> ImageFont.FreeTypeFont:
    for name in _FONT_FILES[kind]:
        p = _FONT_DIR / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _center(d, cx, y, text, font, fill):
    d.text((cx - d.textlength(text, font=font) / 2, y), text, font=font, fill=fill)


def _wrap(d, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _paste_circle(base, img_path, cx, cy, r, ring):
    hs = Image.open(img_path).convert("RGB").resize((2 * r, 2 * r))
    mask = Image.new("L", (2 * r, 2 * r), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
    base.paste(hs, (int(cx - r), int(cy - r)), mask)
    ImageDraw.Draw(base).ellipse((cx - r, cy - r, cx + r, cy + r), outline=ring, width=3)


_COURSE_BGS = None


def _course_bg(i):
    """Path to a cleared course photo (by index), or None (fail closed)."""
    global _COURSE_BGS
    if _COURSE_BGS is None:
        try:
            from essays import imagery
            _COURSE_BGS = [imagery.image_path(e) for e in imagery.cleared("courses")]
        except Exception:
            _COURSE_BGS = []
    return _COURSE_BGS[i % len(_COURSE_BGS)] if _COURSE_BGS else None


def _fill_bg(img, image_path, darken=0.42):
    """Cover-crop `image_path` to fill the frame, darkened for text legibility."""
    bg = Image.open(image_path).convert("RGB")
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((max(W, int(bg.width * scale)), max(H, int(bg.height * scale))))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    img.paste(ImageEnhance.Brightness(bg.crop((left, top, left + W, top + H))).enhance(darken), (0, 0))


def _player_bg(name):
    """Path to a cleared, featured player photo, or None (fail closed)."""
    try:
        from essays import imagery
        return imagery.player_photo(name)
    except Exception:
        return None


def card(path, kicker, big, sub, name="", face_player="", footnote="", bg=None, bg_darken=0.42):
    img = Image.new("RGB", (W, H), BG)
    if bg:
        _fill_bg(img, bg, darken=bg_darken)
    d = ImageDraw.Draw(img)
    base = 305
    if face_player:
        hp = headshot_path(face_player)
        if hp:
            _paste_circle(img, hp, 640, 185, 66, HI)
            base = 400
    _center(d, 640, base - 150, kicker.upper(), _font(30, "semibold"), HI)
    _center(d, 640, base - 100, big, _font(150, "black"), FG)
    _center(d, 640, base + 95, sub, _font(34, "regular"), FG)
    if name:
        _center(d, 640, base + 148, name, _font(26, "regular"), MUTE)
    if footnote:
        _center(d, 640, 656, footnote, _font(20, "regular"), MUTE)
    img.save(path)


def title_card(path, title, tagline="", bg=None):
    """The intro title moment — big centered title, over an optional course photo."""
    img = Image.new("RGB", (W, H), BG)
    if bg:
        _fill_bg(img, bg, darken=0.5)
    d = ImageDraw.Draw(img)
    f = _font(80, "black")
    lines = _wrap(d, title, f, 1080)
    y = (H - len(lines) * 92) // 2 - 14
    d.line((W // 2 - 70, y - 34, W // 2 + 70, y - 34), fill=HI, width=4)
    for ln in lines:
        _center(d, W // 2, y, ln, f, FG)
        y += 92
    if tagline:
        _center(d, W // 2, y + 16, tagline.upper(), _font(24, "semibold"), MUTE)
    img.save(path)


def bars(path, title, items, subtitle="", highlight=""):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((120, 66), title, font=_font(38, "semibold"), fill=FG)
    maxv = max((v for _, v, _ in items), default=1) or 1
    n = max(len(items), 1)
    top, span, x0, barmax = 200, 420, 360, 700
    gap = span / n
    bh = min(60.0, gap * 0.62)
    fl, fb = _font(26, "regular"), _font(26, "semibold")
    for i, (label, v, disp) in enumerate(items):
        y = top + i * gap
        w = barmax * (v / maxv)
        col = HI if (highlight and label == highlight) else DOT
        lw = d.textlength(label, font=fl)
        d.text((x0 - 22 - lw, y + bh / 2 - 16), label, font=fl, fill=FG)
        d.rounded_rectangle((x0, y, x0 + w, y + bh), radius=7, fill=col)
        d.text((x0 + w + 16, y + bh / 2 - 16), disp, font=fb, fill=FG)
    if subtitle:
        d.text((120, 650), subtitle, font=_font(22, "regular"), fill=MUTE)
    img.save(path)


def scatter(path, rows, field_pct, featured):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    L, R, T, B = 130, 1180, 110, 600
    maxled = max(r["led"] for r in rows)

    def sx(led):
        return L + (led / maxled) * (R - L)

    def sy(pct):
        return B - (pct / 100) * (B - T)

    d.text((130, 48), "Who actually closes the 54-hole lead", font=_font(34, "semibold"), fill=FG)
    for p in (0, 25, 50, 75, 100):
        y = sy(p)
        d.line((L, y, R, y), fill=GRID)
        d.text((L - 48, y - 11), f"{p}%", font=_font(18, "regular"), fill=MUTE)
    fy = sy(field_pct)
    x = L
    while x < R:
        d.line((x, fy, min(x + 12, R), fy), fill=LINE)
        x += 22
    _center(d, R - 90, fy - 28, f"field avg {field_pct}%", _font(18, "regular"), LINE)
    fset = set(featured)
    for r in rows:
        if r["player"] in fset:
            continue
        cx, cy = sx(r["led"]), sy(r["convert_pct"])
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=DOT)
    for name in featured:
        r = next((x for x in rows if x["player"] == name), None)
        if not r:
            continue
        cx, cy = sx(r["led"]), sy(r["convert_pct"])
        hp = headshot_path(name)
        if hp:
            _paste_circle(img, hp, cx, cy, 24, HI)
        else:
            d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=HI)
        _center(d, cx, cy - 52, name.split()[-1], _font(19, "semibold"), FG)
    img.save(path)


def _find(rows, name):
    return next((r for r in rows if r["player"] == name), None)


def render_chapter(png_path: Path, title: str, P: dict, rows: list[dict]) -> None:
    """Map a chapter title to its visual and write the PNG."""
    t = title.lower()
    if "cold open" in t:
        return title_card(png_path, "The 54-Hole Lead Is a Lie",
                          "the loneliest place in golf, by the numbers", bg=_course_bg(4))
    if "premise" in t:
        return card(png_path, "The number nobody shows you", f'{P["field_pct"]}%',
                    "how often the 54-hole leader actually wins", bg=_course_bg(2))
    if "close" in t:
        return scatter(png_path, rows, P["field_pct"], FEATURED)
    if "most dangerous" in t:
        order = ["co-lead", "1 shot", "2 shots", "3 shots", "4+ shots"]
        items = [(k, P["margins"][k]["pct"], f'{P["margins"][k]["pct"]}%')
                 for k in order if k in P["margins"]]
        return bars(png_path, "How often each 54-hole lead converts (per player)", items,
                    "Being tied is the weakest place to lead from.", "co-lead")
    if "weight of the lead" in t:
        su = P["sunday"]
        items = [("First three rounds", su["avg_first3"], f'{su["avg_first3"]}'),
                 ("Final round", su["avg_final"], f'{su["avg_final"]}')]
        return bars(png_path, "What the leader shoots: before vs. Sunday", items,
                    f'54-hole leaders average {su["gap"]:+g} strokes worse on Sunday (lower is better).',
                    "Final round")
    if "the god" in t:
        r = _find(P["best"], "Tiger Woods")
        return card(png_path, "The God", f'{r["won"]} / {r["led"]}',
                    f'{r["convert_pct"]}% conversion from the 54-hole lead',
                    name="Tiger Woods", footnote="The lone miss: the 2009 PGA Championship.",
                    bg=_player_bg("Tiger Woods"), bg_darken=0.32)
    if "collapse" in t:
        sixes = [b for b in P["blown"] if b["margin"] == 6]
        names = "    ".join(f'{b["leader"]} ({b["year"]})' for b in sixes[:4])
        return card(png_path, "The Floor", "SIX", "the largest 54-hole lead ever surrendered",
                    footnote=names)
    if "majors" in t:
        me = P.get("major_eras")
        items = [("Regular events", P["field_pct"], f'{P["field_pct"]}%'),
                 ("The four majors", P["majors_pct"], f'{P["majors_pct"]}%')]
        sub = (f'Count each major since 1960 ({me["combined_n"]} of them): {me["combined_pct"]}% '
               f'-- the rule is six decades old.' if me else "")
        return bars(png_path, "The 54-hole lead: majors vs. everywhere else", items,
                    sub, "The four majors")
    if "ghost" in t and P.get("major_eras"):
        me = P["major_eras"]
        return card(png_path, "The Ghost", f'{me["norman_won"]} / {me["norman_led"]}',
                    "majors led -- and lost", "Greg Norman",
                    footnote="1986: led all four majors, won only the Open.", bg=_course_bg(0))
    if "cursed" in t:
        r = _find(P["worst"], "Lee Westwood")
        return card(png_path, "The Cursed", f'{r["won"]} / {r["led"]}',
                    "never converted a 54-hole lead", name="Lee Westwood",
                    bg=_player_bg("Lee Westwood"), bg_darken=0.32)
    if "reputation" in t:
        r = _find(P["best"], "Rory McIlroy")
        return card(png_path, "Reputation vs. Reality", f'{r["convert_pct"]}%',
                    f'{r["won"]} of {r["led"]} -- one of his era\'s best closers',
                    name="Rory McIlroy", bg=_player_bg("Rory McIlroy"), bg_darken=0.32)
    return card(png_path, "The 54-Hole Lead", f'{P["field_pct"]}%', "of leaders go on to win")
