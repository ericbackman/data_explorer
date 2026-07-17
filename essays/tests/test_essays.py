"""Tests for the safety-critical pure functions: the volume-accountability sort
and the claim-audit tripwire. These are the pieces that keep wrong numbers off
YouTube, so they get tests even though the rest of the pipeline is I/O."""
import pytest
from pga.betting import _wilson_lower_bound, worst_closers

from essays.script import audit_script
from essays.tts_homebase import _backend_url, _chunks, resolve_voice


def test_wilson_penalizes_small_samples():
    # A perfect 5-for-5 must NOT outrank a proven 50-for-70: the whole point.
    assert _wilson_lower_bound(5, 5) < _wilson_lower_bound(50, 70)


def test_worst_orders_by_impact_not_wilson():
    rows = [
        {"player": "A", "led": 5, "won": 0, "above_exp": -1.8},
        {"player": "B", "led": 7, "won": 0, "above_exp": -2.6},
    ]
    # 0-for-7 is a worse collapse than 0-for-5 and must sort first.
    assert worst_closers(rows)[0]["player"] == "B"


def _payload():
    best = {"led": 27, "won": 25, "convert_pct": 92.6, "above_exp": 15.0,
            "wilson_pct": 76.6, "expected": 10.0}
    worst = {"led": 7, "won": 0, "convert_pct": 0.0, "above_exp": -2.6,
             "wilson_pct": 0.0, "expected": 2.6}
    allowed = {36.9, 1264.0}
    for r in (best, worst):
        allowed.update(float(v) for v in (r["led"], r["won"], r["convert_pct"],
                                          abs(r["above_exp"]), r["wilson_pct"], r["expected"]))
    return {"best": [best], "worst": [worst], "field_pct": 36.9,
            "total_leads": 1264, "allowed": allowed}


def test_audit_passes_grounded_numbers():
    text = "Tiger won 25 of 27 (92.6%); the field converts just 36.9%."
    assert audit_script(text, _payload()) == []


def test_audit_flags_hallucinated_number():
    assert 41.0 in audit_script("Tiger won 41 majors.", _payload())


def test_audit_allows_years_and_hole_counts():
    assert audit_script("In 2009 he lost his 54-hole lead.", _payload()) == []


# --- tts_homebase: chunking must never drop narration, endpoint must fail loud ---

def test_chunks_preserve_every_paragraph():
    # A dropped paragraph is silently missing narration -> a gap in the voiceover.
    # The chunker must be a lossless regrouping of the paragraphs, in order.
    paras = [f"Paragraph {i} carries a sentence of the script." for i in range(20)]
    chunks = _chunks("\n\n".join(paras), max_chars=120)
    rejoined = [p for c in chunks for p in c.split("\n\n")]
    assert rejoined == paras


def test_chunks_respect_max_chars_when_no_para_exceeds_it():
    paras = ["short one", "short two", "short three", "short four"]
    assert all(len(c) <= 40 for c in _chunks("\n\n".join(paras), max_chars=40))


def test_backend_url_blank_env_fails_loud(monkeypatch):
    # A set-but-blank override must raise, not silently fall back to the default host.
    monkeypatch.setenv("KOKORO_TTS_URL", "   ")
    with pytest.raises(RuntimeError):
        _backend_url("kokoro")


def test_backend_url_precedence_and_per_backend_defaults(monkeypatch):
    monkeypatch.setenv("KOKORO_TTS_URL", "http://from-env:8880/")
    assert _backend_url("kokoro", "http://explicit:9999/") == "http://explicit:9999"  # explicit wins
    assert _backend_url("kokoro") == "http://from-env:8880"                           # env, trailing / trimmed
    monkeypatch.delenv("KOKORO_TTS_URL")
    assert _backend_url("kokoro").endswith(":8880")                                   # default kokoro port
    assert _backend_url("melotts").endswith(":8881")                                  # default melotts port


def test_resolve_voice_routes_registry_and_raw_ids():
    assert resolve_voice("bm_george") == ("kokoro", "bm_george")   # registry -> Kokoro
    assert resolve_voice("aussie") == ("melotts", "EN-AU")         # friendly alias -> MeloTTS
    assert resolve_voice("indian") == ("melotts", "EN_INDIA")      # note the underscore key
    assert resolve_voice("bm_daniel") == ("kokoro", "bm_daniel")   # raw Kokoro id passes through
    assert resolve_voice("EN-AU") == ("melotts", "EN-AU")          # raw MeloTTS id routes by shape
