"""Compose the final video: narration WAV + word-timed chart/card visuals + a
generated CC0 ambient music bed -> MP4.

Timing is word-proportional (TTS speaks at ~constant wpm, so a chapter's share of
the words is its share of the runtime). Frames are rendered as PNGs by Pillow
(essays.render_pil); ffmpeg concatenates the stills and mixes narration over a
ducked music bed. The music is generated here (three detuned sine tones), so it is
unambiguously license-free -- drop a real CC0 track in as music_bed.wav to swap it.

    python -m essays.compose
"""
from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

from pga.betting import DEFAULT_DB, closer_rankings
from pga.db import connect

from essays import render_pil
from essays.claims import build_claims
from essays.narration import DEFAULT_SCRIPT, extract_segments

logger = logging.getLogger(__name__)

_ASSET = Path(__file__).resolve().parent / "assets"
NARR_WAV = _ASSET / "video_zero_narration.wav"
NARR_MP3 = _ASSET / "video_zero_narration.mp3"   # ElevenLabs output, preferred when present
MUSIC = _ASSET / "music_bed.wav"
FRAMES = _ASSET / "frames"
FRAMES_TXT = _ASSET / "frames.txt"
OUT = _ASSET / "video_zero.mp4"


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{r.stderr[-2000:]}")


def _duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def _generate_music(dur: float) -> None:
    d = f"{dur:.2f}"
    _run(["ffmpeg", "-y",
          "-f", "lavfi", "-i", f"sine=frequency=146.83:duration={d}",
          "-f", "lavfi", "-i", f"sine=frequency=185:duration={d}",
          "-f", "lavfi", "-i", f"sine=frequency=220:duration={d}",
          "-filter_complex",
          "[0][1][2]amix=inputs=3:normalize=0,tremolo=f=0.2:d=0.5,lowpass=f=600,"
          f"afade=t=in:d=4,afade=t=out:st={dur - 4:.2f}:d=4,volume=0.5[a]",
          "-map", "[a]", "-ac", "2", str(MUSIC)])


def _encode_clip(png: Path, dur: float, out: Path, fade: float = 0.4) -> None:
    """One scene: a still held for `dur`, fading in from and out to black -- so
    concatenating the clips yields a clean dip-to-black transition between scenes."""
    fo = max(dur - fade, 0.01)
    vf = (f"scale=1280:720,setsar=1,"
          f"fade=t=in:d={fade},fade=t=out:st={fo:.3f}:d={fade},format=yuv420p")
    _run(["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", str(png),
          "-vf", vf, "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-preset", "veryfast", "-an", str(out)])


def build() -> None:
    conn = connect(DEFAULT_DB)
    try:
        payload = build_claims(conn)
        rows = closer_rankings(conn)["rows"]
    finally:
        conn.close()

    narration = NARR_MP3 if NARR_MP3.exists() else NARR_WAV
    segments = extract_segments(DEFAULT_SCRIPT)
    total_words = sum(s["words"] for s in segments)
    total_dur = _duration(narration)
    logger.info("segments=%d  narration=%s (%.1fs)", len(segments), narration.name, total_dur)

    FRAMES.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for i, seg in enumerate(segments):
        dur = seg["words"] / total_words * total_dur
        png = FRAMES / f"ch{i:02d}.png"
        render_pil.render_chapter(png, seg["title"], payload, rows)
        clip = FRAMES / f"clip{i:02d}.mp4"
        _encode_clip(png, dur, clip)
        clips.append(clip)
        logger.info("  %-42s %5.1fs", seg["title"][:42], dur)

    clips_txt = FRAMES / "clips.txt"
    clips_txt.write_text("\n".join(f"file '{c.as_posix()}'" for c in clips) + "\n", encoding="utf-8")
    silent = _ASSET / "_silent.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(clips_txt), "-c", "copy", str(silent)])

    if not MUSIC.exists():
        logger.info("generating CC0 ambient bed (%.0fs)...", total_dur)
        _generate_music(total_dur)

    logger.info("composing %s ...", OUT.name)
    _run(["ffmpeg", "-y", "-i", str(silent), "-i", str(narration), "-i", str(MUSIC),
          "-filter_complex",
          "[2:a]volume=0.10[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
          "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-t", f"{total_dur:.2f}", str(OUT)])
    print(f"wrote {OUT}  ({total_dur / 60:.1f} min, {len(segments)} scenes, dip transitions)")


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description="Compose the video-zero MP4.").parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    build()


if __name__ == "__main__":
    main()
