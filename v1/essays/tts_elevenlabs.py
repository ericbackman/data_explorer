"""ElevenLabs narration voice -- 'George', a synthetic middle-aged British male
(a premade voice ElevenLabs owns; NOT a cloned real person, so no likeness risk).

Swaps in for the SAPI stage: writes video_zero_narration.mp3, which essays.compose
prefers over the SAPI wav. Needs ELEVENLABS_API_KEY in the environment.

  Free tier: 10,000 credits/month, 1 char = 1 credit (Turbo = 0.5/char). This
  script's ~9.4k chars fits, and Turbo leaves room for a second render. Free tier
  is non-commercial and needs a 'Powered by ElevenLabs' credit -- fine unlisted.

    setx ELEVENLABS_API_KEY <key>   (once, then restart shell)
    python -m essays.tts_elevenlabs
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from essays.narration import DEFAULT_OUT as NARRATION_TXT

logger = logging.getLogger(__name__)

_ASSET = Path(__file__).resolve().parent / "assets"
OUT_MP3 = _ASSET / "video_zero_narration.mp3"

# 'George' -- premade British male storyteller (public voice id, not a secret).
VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
MODEL_ID = "eleven_turbo_v2_5"          # 0.5 credits/char; swap to eleven_multilingual_v2 for max quality
_API = "https://api.elevenlabs.io/v1/text-to-speech"
_MAX_CHARS = 2000                        # keep each request well under per-call limits
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _api_key() -> str:
    import os
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is not set. Get a free key at elevenlabs.io "
            "(Profile -> API Keys), then: setx ELEVENLABS_API_KEY <key> and restart the shell.")
    return key


def _chunks(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Group paragraphs into <= max_chars chunks (natural pauses at paragraph breaks)."""
    out, cur = [], ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if cur and len(cur) + len(para) + 2 > max_chars:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        out.append(cur)
    return out


def _synth(key: str, text: str, retries: int = 3) -> bytes:
    body = json.dumps({"text": text, "model_id": MODEL_ID}).encode("utf-8")
    req = urllib.request.Request(
        f"{_API}/{VOICE_ID}?output_format=mp3_44100_128", data=body, method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in _RETRY_STATUS and attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning("ElevenLabs %s; retrying in %ds", e.code, wait)
                time.sleep(wait)
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"ElevenLabs error {e.code}: {detail}") from e
    raise RuntimeError("ElevenLabs: exhausted retries")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Voice the narration with ElevenLabs 'George'.")
    ap.add_argument("--final", action="store_true",
                    help="Confirm the script is reviewed + committed. REQUIRED: the free "
                         "tier gives only ~2 voice renders/month, so we never render a draft.")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.final:
        raise SystemExit(
            "Refusing to render: the free tier allows only ~2 voice renders/month.\n"
            "Voice the script ONLY once it is reviewed + committed, then pass --final.")

    key = _api_key()
    text = NARRATION_TXT.read_text(encoding="utf-8")
    chunks = _chunks(text)
    total = sum(len(c) for c in chunks)
    logger.info("voicing %d chars in %d chunk(s) as 'George' (%s)...", total, len(chunks), MODEL_ID)

    parts_dir = _ASSET / "narration_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_paths = []
    for i, chunk in enumerate(chunks):
        audio = _synth(key, chunk)
        p = parts_dir / f"part_{i:02d}.mp3"
        p.write_bytes(audio)
        part_paths.append(p)
        logger.info("  chunk %d/%d ok (%d chars)", i + 1, len(chunks), len(chunk))

    listing = parts_dir / "parts.txt"
    listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in part_paths) + "\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c:a", "libmp3lame", "-b:a", "192k", str(OUT_MP3)],
                   capture_output=True, text=True, check=True)
    credits = total * (0.5 if "turbo" in MODEL_ID or "flash" in MODEL_ID else 1.0)
    print(f"wrote {OUT_MP3}  (~{int(credits)} credits of the 10,000/mo free tier)")
    print("now: python -m essays.compose   (it will use George's voice)")


if __name__ == "__main__":
    main()
