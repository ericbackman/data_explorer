"""Registry of the shows we track.

Feed URLs are public RSS endpoints (the same ones Apple Podcasts / Overcast
subscribe to). A ``None`` rss_url is a deliberate TODO marker: ingestion will
refuse it loudly rather than guess a wrong feed.

To find a show's real feed: look it up on https://castos.com/tools/find-podcast-rss-feed/
or read the ``<link rel="alternate" type="application/rss+xml">`` on its site.
"""
from __future__ import annotations

SHOWS: dict[str, dict] = {
    # Verified feed — the first vertical slice runs on this show.
    "lonely-island": {
        "title": "The Lonely Island and Seth Meyers Podcast",
        "rss_url": "https://feeds.megaphone.fm/RGP4565962324",
        "yt_channel": None,  # audio-first; expect the whisper tier
    },
    # TODO(feed): confirm the real public RSS URL before ingesting these two.
    "bill-simmons": {
        "title": "The Bill Simmons Podcast",
        "rss_url": None,
        "yt_channel": None,  # The Ringer posts recent eps to YouTube (caption tier)
    },
    "steve-dangle": {
        "title": "The Steve Dangle Podcast",
        "rss_url": None,
        "yt_channel": None,  # SDPN is on YouTube (caption tier)
    },
}
