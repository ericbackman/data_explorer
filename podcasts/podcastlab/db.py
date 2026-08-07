"""SQLite schema and connections for the podcast semantic layer.

One database at ``data/podcasts.db`` holding:
  - shows        : the podcasts we track (slug, title, RSS url)
  - episodes     : one row per episode, with the publish date that makes
                   year-by-year analysis possible
  - transcripts  : the acquired text + word count + which tier produced it
  - transcripts_fts : an FTS5 index over transcript text for fast lexical search
  - mentions     : cached per-(episode, term) counts so re-aggregating a metric
                   is a GROUP BY, never a re-transcription

Nothing runs on import. Call ``init_db()`` to create the schema.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root is the parent of this package; data/ is gitignored.
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "podcasts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS shows (
    show_id    INTEGER PRIMARY KEY,
    slug       TEXT UNIQUE NOT NULL,
    title      TEXT NOT NULL,
    rss_url    TEXT NOT NULL,
    yt_channel TEXT,
    added_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id     INTEGER PRIMARY KEY,
    show_id        INTEGER NOT NULL REFERENCES shows(show_id),
    guid           TEXT NOT NULL,
    title          TEXT NOT NULL,
    published_at   TEXT,          -- ISO8601 UTC; the year-by-year key
    duration_sec   INTEGER,
    audio_url      TEXT,          -- enclosure (for the whisper fallback)
    transcript_url TEXT,          -- podcast:transcript, if the show provides one
    yt_video_id    TEXT,          -- if matched to a YouTube upload
    UNIQUE(show_id, guid)
);

CREATE TABLE IF NOT EXISTS transcripts (
    episode_id     INTEGER PRIMARY KEY REFERENCES episodes(episode_id),
    source         TEXT NOT NULL,   -- 'rss' | 'youtube' | 'whisper'
    text           TEXT NOT NULL,
    word_count     INTEGER NOT NULL,
    transcribed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mentions (
    episode_id INTEGER NOT NULL REFERENCES episodes(episode_id),
    term       TEXT NOT NULL,
    count      INTEGER NOT NULL,
    PRIMARY KEY (episode_id, term)
);

CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts
    USING fts5(text, content='transcripts', content_rowid='episode_id');
"""


def connect(read_only: bool = False) -> sqlite3.Connection:
    """Open the database. Pass ``read_only=True`` for analysis/queries."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the schema if it does not already exist (idempotent)."""
    with connect() as conn:
        conn.executescript(SCHEMA)
    logger.info("schema ready at %s", DB_PATH)
