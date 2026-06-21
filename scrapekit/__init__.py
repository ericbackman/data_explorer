"""Credit-free extraction toolkit shared across data_explorer projects.

No paid APIs. Two strategies, cheapest first:
  1. read_tables(url)   -> list[DataFrame]   (pandas.read_html; $0, no model)
  2. llm_extract(...)   -> dict              (local Ollama; $0 after one install)

extract_with_fallback() runs a caller's parser first and only invokes the local
LLM when the parser fails — so the LLM (and its install) is needed only for the
genuinely messy pages. All fetches are polite, retrying, and disk-cached.
"""

from .extract import Extractor, ParseError, OLLAMA_INSTALL_HINT

__all__ = ["Extractor", "ParseError", "OLLAMA_INSTALL_HINT"]
