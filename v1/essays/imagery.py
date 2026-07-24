"""License-tracked imagery pool (course scenery + player stills) from Wikimedia
Commons -- the same fail-closed, provenance-recorded discipline as headshots.py.

No image is kept unless it carries a free license (CC / public domain); every kept
image logs source + license + author for the on-screen credit and the video
description. `contact_sheet` renders a montage so a human (or a later Gemini pass)
can actually look before anything reaches a frame.

    python -m essays.imagery fetch "golf course links coast" courses 10
    python -m essays.imagery sheet courses
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse
from pathlib import Path

from PIL import Image, ImageDraw

from essays.headshots import _API, _get, _is_free  # reuse the Commons plumbing

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
ASSET_DIR = _ROOT / "assets" / "imagery"
MANIFEST = ASSET_DIR / "manifest.json"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def _save(m: dict) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch(query: str, category: str, n: int = 8, min_w: int = 1000) -> list[dict]:
    """Download up to `n` FREE-licensed Commons images for `query` into
    assets/imagery/<category>/, recording provenance. Never keeps a non-free image."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": str(n * 3),
        "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size", "iiurlwidth": "1280",
    }
    try:
        data = json.loads(_get(_API + "?" + urllib.parse.urlencode(params)))
    except Exception as e:  # network/parse -> keep nothing
        logger.warning("Commons query failed for %r: %s", query, e)
        return []

    pages = sorted((data.get("query") or {}).get("pages", {}).values(),
                   key=lambda p: p.get("index", 0))
    cat_dir = ASSET_DIR / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load()
    have = {e["commons_title"] for e in manifest.get(category, [])}
    kept: list[dict] = []
    for page in pages:
        if len(kept) >= n:
            break
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        if info.get("mime", "") not in ("image/jpeg", "image/png"):
            continue
        if (info.get("width") or 0) < min_w:
            continue
        if not _is_free((meta.get("LicenseShortName") or {}).get("value", "")):
            continue
        title = page.get("title")
        if title in have:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        blob = None
        for attempt in range(4):
            time.sleep(2.0 * (attempt + 1))  # polite spacing; back off harder each 429
            try:
                blob = _get(url)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    logger.warning("  429 throttled, backing off (%d/3)", attempt + 1)
                    continue
                logger.warning("download failed: %s", e)
                break
            except Exception as e:
                logger.warning("download failed: %s", e)
                break
        if blob is None:
            continue
        ext = ".jpg" if info["mime"] == "image/jpeg" else ".png"
        slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")[:24]
        idx = len(manifest.get(category, [])) + len(kept)
        fname = f"{slug}_{idx:02d}{ext}"
        (cat_dir / fname).write_bytes(blob)
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        kept.append({
            "file": fname, "category": category, "query": query,
            "commons_title": title, "image_url": url,
            "license": (meta.get("LicenseShortName") or {}).get("value", ""),
            "artist": artist or "Unknown", "cleared": True,
        })
    manifest.setdefault(category, []).extend(kept)
    _save(manifest)
    logger.info("kept %d free-licensed image(s) for %r in '%s'", len(kept), query, category)
    return kept


def cleared(category: str) -> list[dict]:
    return [e for e in _load().get(category, []) if e.get("cleared")]


def image_path(entry: dict) -> Path:
    return ASSET_DIR / entry["category"] / entry["file"]


def player_photo(name: str):
    """Path to the FEATURED cleared photo for a player (matched by last name),
    falling back to the first cleared photo for them, or None."""
    last = name.split()[-1].lower()
    entries = [e for e in cleared("players") if last in e.get("query", "").lower()]
    featured = [e for e in entries if e.get("featured")]
    pool = featured or entries
    return image_path(pool[0]) if pool else None


def attribution_lines(category: str) -> list[str]:
    return [f'{e["artist"]}, {e["license"]}, Wikimedia Commons' for e in cleared(category)]


def contact_sheet(category: str, cols: int = 4, thumb: int = 300) -> Path:
    """Montage every cleared image in a category, index-labelled, for visual review."""
    entries = cleared(category)
    rows = max(1, math.ceil(len(entries) / cols))
    sheet = Image.new("RGB", (cols * thumb, rows * (thumb + 26)), (18, 22, 28))
    d = ImageDraw.Draw(sheet)
    for i, e in enumerate(entries):
        try:
            im = Image.open(image_path(e)).convert("RGB")
        except Exception:
            continue
        im.thumbnail((thumb - 8, thumb - 8))
        x, y = (i % cols) * thumb, (i // cols) * (thumb + 26)
        sheet.paste(im, (x + 4, y + 4))
        d.text((x + 6, y + thumb + 4), f'[{i}] {e.get("query", "")[:16]}', fill=(210, 210, 210))
    out = ASSET_DIR / f"_contact_{category}.png"
    sheet.save(out)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="License-tracked Commons imagery pool.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("query")
    f.add_argument("category")
    f.add_argument("n", nargs="?", type=int, default=8)
    s = sub.add_parser("sheet")
    s.add_argument("category")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "fetch":
        kept = fetch(args.query, args.category, args.n)
        for e in kept:
            print(f"  {e['file']:<28} {e['license']}")
    elif args.cmd == "sheet":
        print("wrote", contact_sheet(args.category))


if __name__ == "__main__":
    main()
