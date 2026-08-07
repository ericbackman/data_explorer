"""Ingest a podcast RSS feed into the ``episodes`` table.

RSS is the backbone of the whole pipeline: every ``<item>`` carries the audio
enclosure and — crucially — the publish date that makes year-by-year analysis
possible. When a show ships a Podcasting 2.0 ``<podcast:transcript>`` tag we
capture that URL too (free text, no transcription needed downstream).

Usage (from the project root):
    python -m podcastlab.feeds lonely-island
    python -m podcastlab.feeds --all
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests

from podcastlab import db
from podcastlab.shows import SHOWS

logger = logging.getLogger(__name__)

USER_AGENT = "podcast-lab/0.1 (personal research; contact via github.com/ericbackman)"
TIMEOUT = 30
RETRY_STATUS = {429, 500, 502, 503, 504}


def http_get(url: str, max_retries: int = 3) -> bytes:
    """GET with a timeout and exponential backoff on transient failures."""
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if resp.status_code in RETRY_STATUS:
                raise requests.HTTPError(f"HTTP {resp.status_code} from {url}")
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("fetch failed (%d/%d) for %s: %s — retrying in %ds",
                           attempt + 1, max_retries, url, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"failed to fetch {url} after {max_retries} attempts") from last_exc


def _parse_duration(raw) -> Optional[int]:
    """itunes:duration comes as seconds ('3720'), 'MM:SS', or 'HH:MM:SS'."""
    if not raw:
        return None
    raw = str(raw).strip()
    if raw.isdigit():
        return int(raw)
    try:
        parts = [int(p) for p in raw.split(":")]
    except ValueError:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _published_iso(entry) -> Optional[str]:
    """feedparser parses pubDate into a UTC struct_time; normalize to ISO8601."""
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()


def _audio_url(entry) -> Optional[str]:
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("audio") or enc.get("href"):
            return enc.get("href")
    return None


def _transcript_url(entry) -> Optional[str]:
    """Best-effort extraction of a <podcast:transcript> URL (Podcasting 2.0)."""
    pt = entry.get("podcast_transcript")
    if isinstance(pt, dict):
        return pt.get("url")
    if isinstance(pt, list) and pt and isinstance(pt[0], dict):
        return pt[0].get("url")
    for link in entry.get("links", []):
        if "transcript" in (link.get("type", "") + link.get("rel", "")).lower():
            return link.get("href")
    return None


def ingest_show(slug: str) -> int:
    """Fetch a show's feed and upsert its episodes. Returns the count of new ones."""
    show = SHOWS.get(slug)
    if show is None:
        raise KeyError(f"unknown show slug {slug!r}; known: {sorted(SHOWS)}")
    if not show.get("rss_url"):
        raise ValueError(f"show {slug!r} has no rss_url yet (TODO marker in shows.py)")

    parsed = feedparser.parse(http_get(show["rss_url"]))
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"could not parse feed for {slug}: {parsed.bozo_exception}")

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO shows (slug, title, rss_url, yt_channel) VALUES (?,?,?,?) "
            "ON CONFLICT(slug) DO UPDATE SET title=excluded.title, rss_url=excluded.rss_url",
            (slug, show["title"], show["rss_url"], show.get("yt_channel")),
        )
        show_id = conn.execute("SELECT show_id FROM shows WHERE slug=?", (slug,)).fetchone()[0]

        new = 0
        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("link") or entry.get("title")
            if not guid:
                logger.warning("skipping an entry with no guid in %s", slug)
                continue
            cur = conn.execute(
                "INSERT INTO episodes "
                "(show_id, guid, title, published_at, duration_sec, audio_url, transcript_url) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(show_id, guid) DO NOTHING",
                (show_id, guid, entry.get("title", "(untitled)"),
                 _published_iso(entry), _parse_duration(entry.get("itunes_duration")),
                 _audio_url(entry), _transcript_url(entry)),
            )
            new += cur.rowcount
        conn.commit()

    with_transcript = sum(1 for e in parsed.entries if _transcript_url(e))
    logger.info("%s: %d entries in feed, %d new episodes, %d ship a transcript URL",
                slug, len(parsed.entries), new, with_transcript)
    return new


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Ingest podcast RSS feeds into episodes.")
    ap.add_argument("slug", nargs="?", help="show slug (see podcastlab/shows.py)")
    ap.add_argument("--all", action="store_true", help="ingest every show with a feed URL")
    args = ap.parse_args(argv)

    db.init_db()
    if args.all:
        for slug, show in SHOWS.items():
            if not show.get("rss_url"):
                logger.warning("skipping %s (no rss_url yet)", slug)
                continue
            ingest_show(slug)
    elif args.slug:
        ingest_show(args.slug)
    else:
        ap.error("provide a show slug or --all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
