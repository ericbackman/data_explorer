"""Homebase self-hosted narration voices -- Kokoro (US/UK English) + MeloTTS (accents).

Two CPU-only TTS Docker stacks run on the always-on `homebase` server, both tailnet-only,
both free/unlimited/local and commercial-clean:
  - kokoro  (Kokoro-82M, Apache-2.0) : the default narrator + all US/UK English voices.
  - melotts (MeloTTS, MIT)           : the accents Kokoro lacks -- Australian, Indian English.
This one client voices the essays narration with any of them and writes
video_zero_narration.mp3, which essays.compose prefers over the SAPI wav.

Voices (pass to --voice or the HOMEBASE_VOICE env var; `--list-voices` prints them):
  bm_george (default), bm_fable, bm_lewis, am_michael, am_fenrir  -> Kokoro (US/UK English)
  aussie (EN-AU), indian (EN_INDIA)                                -> MeloTTS (accents)
A raw backend voice id also works: EN-*/EN_* route to MeloTTS, anything else to Kokoro (so
e.g. --voice bm_daniel or --voice af_bella hit Kokoro directly). A/B samples for every voice
live in assets/voice_samples/.

Endpoints (tailnet-only + unauthenticated -> plain default constants, not secrets; override
a run's backend URL with --url, or set KOKORO_TTS_URL / MELOTTS_TTS_URL):
  Kokoro  : http://homebase...:8880  (OpenAI-compatible POST /v1/audio/speech)
  MeloTTS : http://homebase...:8881  (POST /convert/tts)

The relevant stack must be up (HOMEBASE_PLAYBOOK.md OP-K1 = kokoro, OP-K2 = melotts):
    ssh root@homebase.tailc79552.ts.net 'cd /opt/stacks/kokoro  && docker compose up -d'
    ssh root@homebase.tailc79552.ts.net 'cd /opt/stacks/melotts && docker compose up -d'

    python -m essays.narration                        # (re)generate the narration .txt
    python -m essays.tts_homebase                      # bm_george -> video_zero_narration.mp3
    python -m essays.tts_homebase --voice aussie --out assets/narration.aussie.mp3   # A/B an accent
    python -m essays.tts_homebase --list-voices
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from essays.narration import DEFAULT_OUT as NARRATION_TXT

logger = logging.getLogger(__name__)

_ASSET = Path(__file__).resolve().parent / "assets"
OUT_MP3 = _ASSET / "video_zero_narration.mp3"
_PARTS_DIR = _ASSET / "narration_parts_homebase"   # WAV parts; one backend per run so rate is uniform

# homebase endpoints. MagicDNS name > raw 100.x address: it survives Tailscale IP drift.
# Tailnet-only + no auth, so these are plain constants, not secrets.
DEFAULT_HOST = "homebase.tailc79552.ts.net"
KOKORO_PORT = 8880
MELOTTS_PORT = 8881
_ENV_KOKORO_URL = "KOKORO_TTS_URL"     # per-backend base-URL overrides (fail loudly if blank)
_ENV_MELOTTS_URL = "MELOTTS_TTS_URL"
_ENV_VOICE = "HOMEBASE_VOICE"          # optional default-voice override
_ENV_SPEED = "HOMEBASE_SPEED"          # optional speech-rate override

BACKEND_KOKORO = "kokoro"
BACKEND_MELOTTS = "melotts"
DEFAULT_VOICE = "bm_george"            # highest-graded British male in Kokoro; documentary register
DEFAULT_SPEED = 1.0                    # bm_george @ 1.0 ~= 158 wpm (~9 min); ~0.85 stretches toward ~11 min
MODEL_ID = "kokoro"                    # required by Kokoro's OpenAI-compatible schema

_KOKORO_SPEECH = "/v1/audio/speech"
_KOKORO_HEALTH = "/health"
_MELOTTS_SPEECH = "/convert/tts"

# canonical voice name -> (backend, backend voice id, human label)
VOICES: dict[str, tuple[str, str, str]] = {
    "bm_george":  (BACKEND_KOKORO,  "bm_george",  "British male, documentary register (default narrator)"),
    "bm_fable":   (BACKEND_KOKORO,  "bm_fable",   "British male, lighter timbre"),
    "bm_lewis":   (BACKEND_KOKORO,  "bm_lewis",   "British male, alternate"),
    "am_michael": (BACKEND_KOKORO,  "am_michael", "American male (General/Middle American)"),
    "am_fenrir":  (BACKEND_KOKORO,  "am_fenrir",  "American male (General/Middle American, alt)"),
    "aussie":     (BACKEND_MELOTTS, "EN-AU",      "Australian English (MeloTTS)"),
    "indian":     (BACKEND_MELOTTS, "EN_INDIA",   "Indian English (MeloTTS)"),
}

_MAX_CHARS = 2000                      # group paragraphs under this: natural pauses + per-chunk retry granularity
_RETRY_STATUS = {429, 500, 502, 503, 504}
# MeloTTS lazy-loads its model on the FIRST /convert/tts call (~150s cold start), so it needs
# a far longer per-request timeout than Kokoro (which warms up at container start).
_TIMEOUT = {BACKEND_KOKORO: 180, BACKEND_MELOTTS: 300}
_RETRIES = 4


def resolve_voice(voice: str) -> tuple[str, str]:
    """Map a --voice value to (backend, backend_voice_id). Registry names win; otherwise a raw
    backend id is routed by shape (EN-*/EN_* -> MeloTTS, anything else -> Kokoro)."""
    if voice in VOICES:
        backend, vid, _ = VOICES[voice]
        return backend, vid
    if voice.upper().startswith(("EN-", "EN_")):
        return BACKEND_MELOTTS, voice
    return BACKEND_KOKORO, voice


def _backend_url(backend: str, override: str | None = None) -> str:
    """Resolve a backend's base URL. Precedence: explicit override > env var > default host.
    An env override that is *set but blank* is a mistake, so fail loudly (Tier-0/Tier-1)."""
    if override:
        return override.strip().rstrip("/")
    env, port = ((_ENV_KOKORO_URL, KOKORO_PORT) if backend == BACKEND_KOKORO
                 else (_ENV_MELOTTS_URL, MELOTTS_PORT))
    raw = os.getenv(env)
    if raw is not None:
        url = raw.strip().rstrip("/")
        if not url:
            raise RuntimeError(
                f"{env} is set but empty. Unset it to use the default "
                f"(http://{DEFAULT_HOST}:{port}) or give a full URL like http://100.122.124.52:{port}")
        return url
    return f"http://{DEFAULT_HOST}:{port}"


def _chunks(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Group paragraphs into <= max_chars chunks (natural pauses at paragraph breaks).
    Every non-empty paragraph MUST land in exactly one chunk -- a dropped paragraph is
    silently missing narration, so this is covered by a test."""
    out: list[str] = []
    cur = ""
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


def _health_check(backend: str, base_url: str, retries: int = 3) -> None:
    """Confirm the backend is reachable before a long render. homebase's uplink is a
    known-flaky USB-WiFi dongle that blips under load (see HOMEBASE_PLAYBOOK), so retry a
    few times before failing loudly. Kokoro exposes /health (200 = model loaded); MeloTTS
    has no health route and lazy-loads on first synth, so any HTTP response means 'alive'."""
    url = f"{base_url}{_KOKORO_HEALTH}" if backend == BACKEND_KOKORO else f"{base_url}/"
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                status = getattr(r, "status", r.getcode())
                if backend == BACKEND_MELOTTS or status == 200:
                    return
                last_err = RuntimeError(f"{backend} health HTTP {status}")
        except urllib.error.HTTPError as e:
            if backend == BACKEND_MELOTTS:
                return                      # server answered (e.g. 404 at root) -> it is up
            last_err = e
        except (urllib.error.URLError, OSError) as e:
            last_err = e
        if attempt < retries - 1:
            wait = 2 ** attempt
            logger.warning("%s not reachable (%s); retrying in %ds", backend, last_err, wait)
            time.sleep(wait)
    raise RuntimeError(
        f"Cannot reach {backend} at {base_url} after {retries} attempts ({last_err}).\n"
        f"Is the stack up, and are you on the tailnet? Check/start it with:\n"
        f"  ssh root@{DEFAULT_HOST} 'cd /opt/stacks/{backend} && docker compose up -d && docker ps'")


def _post_audio(url: str, payload: dict, headers: dict, timeout: int, retries: int = _RETRIES) -> bytes:
    """POST JSON, return raw audio bytes. Retries transient 5xx/429 and transient connection
    errors with exponential backoff (Tier-1 rule 10). Raises on exhaustion -- never returns
    empty/partial audio that would masquerade as a valid render (Tier-1 rule 11)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in _RETRY_STATUS and attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning("TTS HTTP %s; retrying in %ds", e.code, wait)
                time.sleep(wait)
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"TTS error {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning("TTS connection error (%s); retrying in %ds", e, wait)
                time.sleep(wait)
                continue
            raise RuntimeError(f"TTS unreachable after {retries} attempts: {e}") from e
    raise RuntimeError(f"TTS: exhausted retries ({last_err})")


def _synth(backend: str, base_url: str, text: str, voice_id: str, speed: float) -> bytes:
    """Return WAV bytes for one chunk from the given backend. Both return WAV, so downstream
    (concat -> single MP3 encode) is backend-agnostic; only the request shape differs."""
    if backend == BACKEND_KOKORO:
        return _post_audio(
            f"{base_url}{_KOKORO_SPEECH}",
            {"model": MODEL_ID, "input": text, "voice": voice_id, "response_format": "wav", "speed": speed},
            {"Content-Type": "application/json", "Accept": "audio/wav"}, _TIMEOUT[backend])
    return _post_audio(
        f"{base_url}{_MELOTTS_SPEECH}",
        {"text": text, "language": "EN", "speaker_id": voice_id, "speed": speed},
        {"Content-Type": "application/json"}, _TIMEOUT[backend])


def synthesize(text: str, voice: str, out_path: Path, url_override: str | None = None,
               speed: float = DEFAULT_SPEED) -> Path:
    """Voice `text` in `voice` -> `out_path` (mp3). Resolves the backend, fetches WAV chunks,
    concatenates losslessly, and encodes one MP3. Raises on any failure and never writes a
    partial or silent mp3."""
    backend, voice_id = resolve_voice(voice)
    base_url = _backend_url(backend, url_override)
    _health_check(backend, base_url)
    chunks = _chunks(text)
    if not chunks:
        raise RuntimeError("narration text is empty -- nothing to voice")
    total = sum(len(c) for c in chunks)
    logger.info("voicing %d chars in %d chunk(s) as '%s' [%s:%s] via %s ...",
                total, len(chunks), voice, backend, voice_id, base_url)

    _PARTS_DIR.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []
    for i, chunk in enumerate(chunks):
        t = time.time()
        audio = _synth(backend, base_url, chunk, voice_id, speed)
        p = _PARTS_DIR / f"part_{i:02d}.wav"
        p.write_bytes(audio)
        part_paths.append(p)
        logger.info("  chunk %d/%d ok (%d chars, %.1fs)", i + 1, len(chunks), len(chunk), time.time() - t)

    listing = _PARTS_DIR / "parts.txt"
    listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in part_paths) + "\n", encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:a", "libmp3lame", "-b:a", "192k", str(out_path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{r.stderr[-2000:]}")
    return out_path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Voice the narration with a homebase TTS stack (Kokoro/MeloTTS; free, local, unlimited).")
    ap.add_argument("--voice", default=os.getenv(_ENV_VOICE) or DEFAULT_VOICE,
                    help=f"voice name or raw backend id (default {DEFAULT_VOICE}; see --list-voices)")
    ap.add_argument("--url", default=None,
                    help=f"override the active backend's base URL (else ${_ENV_KOKORO_URL}/${_ENV_MELOTTS_URL})")
    ap.add_argument("--speed", type=float, default=float(os.getenv(_ENV_SPEED) or DEFAULT_SPEED),
                    help=f"speech-rate multiplier (default {DEFAULT_SPEED}; <1 slower/longer, >1 faster)")
    ap.add_argument("--out", type=Path, default=OUT_MP3, help="output mp3 path")
    ap.add_argument("--list-voices", action="store_true", help="print the voice registry and exit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.list_voices:
        for name, (backend, vid, label) in VOICES.items():
            print(f"  {name:11s} [{backend}:{vid}]  {label}")
        print("  (raw backend ids also work: EN-*/EN_* -> MeloTTS, anything else -> Kokoro)")
        return

    if not NARRATION_TXT.exists():
        raise SystemExit(
            f"{NARRATION_TXT} not found -- generate it first:\n  python -m essays.narration")
    text = NARRATION_TXT.read_text(encoding="utf-8")

    out = synthesize(text, args.voice, args.out, url_override=args.url, speed=args.speed)
    logger.info("wrote %s  (voice: %s, speed %.2f -- free/local, no quota)", out, args.voice, args.speed)
    if out == OUT_MP3:
        logger.info("now: python -m essays.compose   (it will use this voice)")


if __name__ == "__main__":
    main()
