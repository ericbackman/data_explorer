# Narration voices: stages, backends, and how to pick one

`essays.compose` selects the narration track by this precedence (see `compose.py`):
**`video_zero_narration.mp3` (if present) → `video_zero_narration.wav`**. Whichever stage last
wrote the `.mp3` wins; delete it to fall back to the SAPI `.wav`. All stages are kept for A/B.

## The stages

| Stage | Module | Cost / limits | License | Voices |
|---|---|---|---|---|
| SAPI (v1) | `tts_sapi.ps1` | free · local · unlimited | OS | one robotic Windows voice |
| ElevenLabs | `tts_elevenlabs.py` | ~2 renders/mo free · **non-commercial** | metered | "George" (British male, top-tier) |
| **Homebase** (default) | `tts_homebase.py` | **free · local · unlimited** | **Apache-2.0 / MIT (commercial-clean)** | Kokoro + MeloTTS (below) |

The homebase stage is **one client over two self-hosted, tailnet-only Docker stacks** on homebase
(HOMEBASE_PLAYBOOK **OP-K1/OP-K2**): **Kokoro-82M** (US/UK English, the narrator) and **MeloTTS**
(the accents Kokoro lacks). Both are free/unlimited/local and safe for a monetized channel.

## Homebase voices: `python -m essays.tts_homebase --list-voices`

| `--voice` | Backend | Accent / character |
|---|---|---|
| **`bm_george`** (default) | Kokoro | British male, documentary register: the narrator |
| `bm_fable`, `bm_lewis` | Kokoro | British male (alternates) |
| `am_michael`, `am_fenrir` | Kokoro | American male (General / "Middle American") |
| `aussie` | MeloTTS | Australian English (`EN-AU`) |
| `indian` | MeloTTS | Indian English (`EN_INDIA`) |

Raw backend ids also work (`EN-*`/`EN_*` → MeloTTS, anything else → Kokoro), so e.g. `--voice af_bella`
reaches any Kokoro voice directly. One-sentence A/B samples for every voice live in `assets/voice_samples/`.

    python -m essays.narration                    # (re)generate the narration .txt
    python -m essays.tts_homebase                  # bm_george -> video_zero_narration.mp3
    python -m essays.tts_homebase --voice aussie --out assets/narration.aussie.mp3   # A/B an accent
    python -m essays.compose                       # build video_zero.mp4 (prefers the .mp3)

Swap the narrator with `--voice` or `HOMEBASE_VOICE`; pace with `--speed 0.85` (1.0 ≈ 158 wpm ≈ 9 min).

## Why homebase is the permanent voice
No quota, no metering, and, unlike the ElevenLabs free tier, no "non-commercial + Powered-by
attribution" string (Kokoro = Apache-2.0, MeloTTS = MIT). Adding an accent is a `--voice` flag, not a new bill.

## Quality notes
On a like-for-like render of the ~1,400-word golf script, Kokoro's `bm_george` lands **decisively
above SAPI and just short of ElevenLabs**. SAPI is unmistakably synthetic: flat affect, mechanical
word-joins, no sentence-level prosody. Kokoro (an 82M-param StyleTTS2 neural model) is a different
class: natural British intonation, sensible emphasis, and clean handling of the script's rhetorical
pauses at a broadcast-standard ~158 wpm. Against ElevenLabs "George" (a far larger commercial model)
Kokoro trails on the last few percent of realism (breath, micro-dynamics) and its 24 kHz mono is
lower-fidelity than ElevenLabs' 44.1 kHz, but that gap is small next to what it buys: unlimited free
local renders under a commercial-clean license. `bm_george` is the right permanent narrator;
ElevenLabs stays available as a one-off "hero render."

**MeloTTS (accents)** is a separate model with a slightly brighter, quicker-read delivery, and its
44.1 kHz output is actually higher-fidelity than Kokoro's 24 kHz. `aussie`/`indian` are single fixed
speakers (no "upbeat" dial): natural regional English; judge by ear against the samples. Accents
beyond these (Kiwi, Eastern-European, Latin-American, Letterkenny-Canadian) aren't presets in any
commercial-clean model: they'd need voice-*cloning* (e.g. Chatterbox, MIT) from a legally-clean
reference clip, which is a separate, GPU-hungry project (deferred; homebase has no GPU).
