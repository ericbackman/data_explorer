# podcast-lab

*(Folded in as `data_explorer/podcasts/` from the standalone `podcast-lab` folder,
2026-08-07: it already followed this repo's conventions and gains version control
here. The database stays local via this directory's `.gitignore`.)*

A queryable **semantic layer over podcasts**. Ingest a show's RSS feed, acquire
transcripts via a free-first waterfall, store everything in local SQLite, and
turn "how often does Bill Simmons say *Boston*, by year?" into plain SQL plus a
mention-counting function.

Mirrors the conventions of the sibling `data_explorer` project: read-only SQLite
queries, cached scrapers, a gitignored `data/`, and *validate every number
against a known fact* before trusting it.

## Pipeline

```
RSS feed ──► episodes (title, pubDate, audio_url, transcript_url?)   ← the spine
   │                                    pubDate = the year-by-year key
   └─ per episode, acquire text via a free-first waterfall:
        1. <podcast:transcript> URL from the feed   free, instant
        2. YouTube captions (youtube-transcript-api)  free, instant
        3. faster-whisper on the audio enclosure     free, CPU-bound (fallback)
                    │
                    ▼
        SQLite  data/podcasts.db  (+ FTS5 index)
                    │
                    ▼
        count_mentions() ──► mentions/year ──► charts
```

## Usage

```bash
# from the project root
python -m podcastlab.feeds lonely-island          # pull episodes + dates
python -m podcastlab.transcribe lonely-island --limit 1   # transcribe newest ep
python -m podcastlab.count lonely-island Quaid    # mention rate by year
```

## Schema (`data/podcasts.db`)

| table | purpose |
|-------|---------|
| `shows` | tracked podcasts (slug, title, RSS url) |
| `episodes` | one row per episode; `published_at` drives all year-by-year stats |
| `transcripts` | acquired text + word count + which tier produced it |
| `transcripts_fts` | FTS5 index over transcript text (fast lexical search) |
| `mentions` | cached per-(episode, term) counts: re-metric without re-transcribing |

## The one decision that's yours

`podcastlab/count.py :: count_mentions(text, term)` defines what counts as a
single mention (case, word boundaries, plurals/possessives, multi-word phrases).
It shapes every number this project produces and is deliberately left to
implement by hand.

## Design notes

- **Free sources only** by default (matches the workspace ethos). Paid transcript
  APIs (Spoken.md ~$0.08/ep, Taddy Pro) are an escape hatch, not the default.
- **RSS is the backbone**, not any transcript API — it's the only source that
  reliably preserves the publish date needed for longitudinal analysis.
- **Raw counts + word counts are stored per episode**, so switching the metric
  later (per-1000-words, per-hour, %-of-episodes) is a re-query, not a re-run.
