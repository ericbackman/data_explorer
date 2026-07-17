"""License-tracked headshot pool for outlier chart markers.

Sources from Wikimedia Commons, ACCEPTS only free licenses that permit commercial
reuse and modification (CC0 / public domain / CC BY / CC BY-SA), records
provenance per image, and -- critically -- FAILS CLOSED: a player with no cleared
entry gets no marker (the chart falls back to a dot), so an unlicensed image can
never be silently burned into a published, monetized video.

    python -m essays.headshots "Tiger Woods" "Rory McIlroy" ...
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
ASSET_DIR = _ROOT / "assets" / "headshots"
MANIFEST = ASSET_DIR / "manifest.json"

_API = "https://commons.wikimedia.org/w/api.php"
_UA = "backman-video-essays/0.1 (https://github.com/ericbackman; educational non-commercial)"
_TIMEOUT = 20

# Accept only licenses allowing commercial use AND derivatives (we may stylize).
_FREE = ("cc0", "public domain", "cc by 1", "cc by 2", "cc by 3", "cc by 4", "cc by-sa")
_BLOCKED = ("nc", "nd", "fair use", "non-free", "all rights reserved")


def _is_free(license_short: str) -> bool:
    s = (license_short or "").lower()
    if any(b in s for b in _BLOCKED):
        return False
    return any(f in s for f in _FREE)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _save_manifest(m: dict) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_headshot(player: str) -> dict | None:
    """Find a FREE-licensed Commons image for `player`, download a small thumbnail,
    record provenance in the manifest. Returns the entry, or None if nothing
    free-licensed was found -- it never fabricates a license."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{player} golfer", "gsrnamespace": "6", "gsrlimit": "12",
        "prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": "240",
    }
    try:
        data = json.loads(_get(_API + "?" + urllib.parse.urlencode(params)))
    except Exception as e:  # network / parse -> fail closed, no crash
        logger.warning("Commons query failed for %s: %s", player, e)
        return None

    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        if info.get("mime", "") not in ("image/jpeg", "image/png"):
            continue
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not _is_free(lic):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        try:
            blob = _get(url)
        except Exception as e:
            logger.warning("download failed for %s: %s", player, e)
            continue
        ext = ".jpg" if info["mime"] == "image/jpeg" else ".png"
        fname = re.sub(r"[^a-z0-9]+", "_", player.lower()).strip("_") + ext
        (ASSET_DIR / fname).parent.mkdir(parents=True, exist_ok=True)
        (ASSET_DIR / fname).write_bytes(blob)
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        entry = {
            "file": fname,
            "commons_title": page.get("title"),
            "image_url": url,
            "license": lic,
            "artist": artist or "Unknown",
            "cleared": True,
        }
        m = _load_manifest()
        m[player] = entry
        _save_manifest(m)
        logger.info("cleared headshot for %s (%s)", player, lic)
        return entry

    logger.warning("no free-licensed image found for %s -- chart will use a dot", player)
    return None


def marker_data_uri(player: str) -> str | None:
    """Base64 data URI for a CLEARED headshot, or None (fail closed)."""
    entry = _load_manifest().get(player)
    if not entry or not entry.get("cleared"):
        return None
    f = ASSET_DIR / entry["file"]
    if not f.exists():
        return None
    mime = "image/jpeg" if f.suffix == ".jpg" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()


def headshot_path(player: str) -> Path | None:
    """Filesystem path to a CLEARED headshot image, or None (fail closed)."""
    entry = _load_manifest().get(player)
    if not entry or not entry.get("cleared"):
        return None
    f = ASSET_DIR / entry["file"]
    return f if f.exists() else None


def attribution(player: str) -> str | None:
    """Credit line for a cleared headshot, for the chart footer + video description."""
    entry = _load_manifest().get(player)
    if not entry:
        return None
    return f'{player} ({entry["artist"]}, {entry["license"]}, Wikimedia Commons)'


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build the license-tracked headshot pool.")
    ap.add_argument("players", nargs="+")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for p in args.players:
        entry = fetch_headshot(p)
        status = f"OK   {entry['license']}" if entry else "NO FREE IMAGE (dot fallback)"
        print(f"  {p:<22} {status}")


if __name__ == "__main__":
    main()
