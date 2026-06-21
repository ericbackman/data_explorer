"""Fallback-orchestration tests — no network, no model (stubs fetch + llm)."""

from scrapekit import Extractor, ParseError


def _stubbed(tmp_path):
    ex = Extractor(tmp_path)
    ex.fetch = lambda url, use_cache=True: "<html>fake</html>"
    ex.llm_extract = lambda text, schema, prompt: {"via": "llm"}
    return ex


def test_parser_success_skips_llm(tmp_path):
    ex = _stubbed(tmp_path)
    out = ex.extract_with_fallback("u", lambda h: {"via": "parser"}, schema={}, prompt="")
    assert out == {"via": "parser"}            # LLM never consulted


def test_parse_error_falls_back_to_llm(tmp_path):
    ex = _stubbed(tmp_path)

    def boom(_html):
        raise ParseError("layout not recognized")

    out = ex.extract_with_fallback("u", boom, schema={}, prompt="")
    assert out == {"via": "llm"}


def test_empty_parse_result_falls_back_to_llm(tmp_path):
    ex = _stubbed(tmp_path)
    out = ex.extract_with_fallback("u", lambda h: None, schema={}, prompt="")
    assert out == {"via": "llm"}
