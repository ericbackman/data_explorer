"""Extract the spoken narration from a script markdown file.

Only prose paragraphs are narrated -- chapter titles appear on screen as cards,
visual cues (_Visual: ..._), the meta lines, and the verification banner are not
spoken. This is the text the TTS stage voices.

    python -m essays.narration                      # -> assets/video_zero_narration.txt
    python -m essays.narration --script path.md --out path.txt
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
DEFAULT_SCRIPT = _ROOT / "assets" / "video_zero_script.md"
DEFAULT_OUT = _ROOT / "assets" / "video_zero_narration.txt"


def extract_narration(script_path: Path) -> str:
    """Spoken prose only: drop headers (#), the banner (>), rules (---), and any
    italic line (_Visual: ..._ cues and _meta_)."""
    paras: list[str] = []
    for line in script_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ">", "---", "_", "|")):
            continue
        paras.append(s)
    return "\n\n".join(paras)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text))


def extract_segments(script_path: Path) -> list[dict]:
    """Split into chapters at '## ' headers. Each segment carries its title, the
    spoken prose, and a word count (used for word-proportional visual timing)."""
    segments: list[dict] = []
    cur: dict | None = None
    for line in script_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("## "):
            cur = {"title": s[3:].strip(), "parts": []}
            segments.append(cur)
        elif cur is not None and s and not s.startswith(("#", ">", "---", "_", "|")):
            cur["parts"].append(s)
    out = []
    for seg in segments:
        text = " ".join(seg["parts"])
        wc = word_count(text)
        if wc:
            out.append({"title": seg["title"], "text": text, "words": wc})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Extract narration text from a script.")
    ap.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    text = extract_narration(args.script)
    args.out.write_text(text, encoding="utf-8")
    wc = word_count(text)
    print(f"wrote {args.out}")
    print(f"narration: {wc} words  (~{wc/140:.1f} min at an unrushed 140 wpm)")


if __name__ == "__main__":
    main()
