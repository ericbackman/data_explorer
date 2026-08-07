"""Per-episode transcript acquisition — a free-first waterfall.

For each episode we try, cheapest first, and stop at the first tier that works:

  1. RSS transcript URL   (episodes.transcript_url)          free, instant
  2. YouTube captions     (episodes.yt_video_id)             free, instant
  3. faster-whisper       (transcribe the audio enclosure)   free, CPU-bound

The heavy dependencies (youtube-transcript-api, faster-whisper) are imported
lazily, so ingestion and analysis keep working even if they are not installed —
you only pay for the tiers you actually reach.

Usage:
    python -m podcastlab.transcribe lonely-island --limit 1        # newest ep
    python -m podcastlab.transcribe lonely-island --tiers rss,youtube
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

from podcastlab import db
from podcastlab.feeds import http_get

logger = logging.getLogger(__name__)

DEFAULT_TIERS = ("rss", "youtube", "whisper")
WHISPER_MODEL = "base.en"  # good speed/quality on CPU; bump to small.en for accuracy


def _clean_captions(raw: str) -> str:
    """Strip VTT/SRT timestamps and cue numbers, leaving spoken text."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        if "-->" in line:  # timestamp cue line
            continue
        lines.append(re.sub(r"<[^>]+>", "", line))  # drop inline caption tags
    return " ".join(lines).strip()


def from_rss(transcript_url: str) -> Optional[str]:
    text = http_get(transcript_url).decode("utf-8", errors="replace")
    if "-->" in text or text.lstrip().startswith("WEBVTT"):
        text = _clean_captions(text)
    return text.strip() or None


def from_youtube(video_id: str) -> Optional[str]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.warning("youtube-transcript-api not installed; skipping YouTube tier")
        return None
    segments = YouTubeTranscriptApi.get_transcript(video_id)
    return " ".join(seg["text"] for seg in segments).strip() or None


def from_whisper(audio_url: str) -> Optional[str]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster-whisper not installed; skipping whisper tier")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / "episode.mp3"
        audio_path.write_bytes(http_get(audio_url))
        logger.info("transcribing %s with whisper (%s) — this is CPU-bound",
                    audio_url, WHISPER_MODEL)
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path))
        return " ".join(seg.text.strip() for seg in segments).strip() or None


def acquire(episode: "db.sqlite3.Row", tiers) -> Optional[tuple[str, str]]:
    """Return (source, text) from the first tier that yields text, else None."""
    if "rss" in tiers and episode["transcript_url"]:
        text = from_rss(episode["transcript_url"])
        if text:
            return "rss", text
    if "youtube" in tiers and episode["yt_video_id"]:
        text = from_youtube(episode["yt_video_id"])
        if text:
            return "youtube", text
    if "whisper" in tiers and episode["audio_url"]:
        text = from_whisper(episode["audio_url"])
        if text:
            return "whisper", text
    return None


def transcribe_show(slug: str, tiers=DEFAULT_TIERS, limit: Optional[int] = None) -> int:
    """Transcribe episodes of a show that don't yet have a transcript."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT e.* FROM episodes e JOIN shows s ON s.show_id = e.show_id "
            "LEFT JOIN transcripts t ON t.episode_id = e.episode_id "
            "WHERE s.slug = ? AND t.episode_id IS NULL "
            "ORDER BY e.published_at DESC" + (" LIMIT ?" if limit else ""),
            (slug, limit) if limit else (slug,),
        ).fetchall()

        done = 0
        for row in rows:
            result = acquire(row, tiers)
            if result is None:
                logger.warning("no transcript for %r via tiers %s", row["title"], tiers)
                continue
            source, text = result
            word_count = len(text.split())
            conn.execute(
                "INSERT INTO transcripts (episode_id, source, text, word_count) "
                "VALUES (?,?,?,?) ON CONFLICT(episode_id) DO UPDATE SET "
                "source=excluded.source, text=excluded.text, word_count=excluded.word_count",
                (row["episode_id"], source, text, word_count),
            )
            conn.execute(
                "INSERT INTO transcripts_fts (rowid, text) VALUES (?, ?)",
                (row["episode_id"], text),
            )
            conn.commit()
            done += 1
            logger.info("[%s] %r — %d words", source, row["title"], word_count)
    logger.info("%s: transcribed %d episode(s)", slug, done)
    return done


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Acquire transcripts via the free-first waterfall.")
    ap.add_argument("slug", help="show slug (see podcastlab/shows.py)")
    ap.add_argument("--limit", type=int, default=None, help="only the N newest untranscribed eps")
    ap.add_argument("--tiers", default=",".join(DEFAULT_TIERS),
                    help="comma-separated subset of: rss,youtube,whisper")
    args = ap.parse_args(argv)
    tiers = tuple(t.strip() for t in args.tiers.split(",") if t.strip())
    transcribe_show(args.slug, tiers=tiers, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
