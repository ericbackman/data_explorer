# nba-cba — project instructions

Agentic knowledge layer over the NBA Collective Bargaining Agreement. See
[`README.md`](README.md) for layout and [`SEMANTIC_LAYER.md`](SEMANTIC_LAYER.md) for how to
navigate the CBA.

## Answering a CBA question
1. **Read `SEMANTIC_LAYER.md` first.** Never answer cap/trade questions from memory — route to
   the governing Article/Section, `Read` the corpus text, and quote it.
2. Navigate with `semantic/2023-nba-cba.toc.json` (Article/Section → corpus line) and
   `semantic/2023-nba-cba.definitions.json` (glossary → cross-refs). `L####` line numbers in
   the JSON match `corpus/text/2023-nba-cba.raw.txt` and the `Read` tool.
3. Default to the **2023** CBA (current). Use **2017** only for "what changed" / legacy deals.

## Non-obvious facts (don't rediscover)
- **Article VII is the engine** (cap, tax, aprons, exceptions, extensions, trades).
- **Trade legality is a join across § 2(e) (apron limits) + § 6(j) (salary matching) + § 8
  (procedure).** The section literally titled "Trade Rules" (§ 8) is only one-third of it.
- **Apron/Tax dollar figures are defined inline in § 2(a)**, not the Article I glossary.
- The **Transaction Restrictions Table (§ 2(e)(4))** is the second-apron "hard cap" — encoded
  in `semantic/apron-transaction-restrictions.json`.
- 2023 matching = four named TPEs (§ 6(j)(1)(i)–(iv)); the old "125%+$100k" is gone; over the
  first apron the "+$250,000" cushion → $0 (§ 6(j)(3)).

## Corpus is copyright, git-ignored
`corpus/` (PDFs + full text) is © NBA/NBPA and **not committed** — rebuild via
`python tools/fetch_cba.py`. Commit only derived analysis. **Keep this repo private** while it
holds verbatim excerpts (e.g. `definitions.json`); explainers use short attributed quotes only.

## Regenerating artifacts
`python tools/build_index.py <2023-nba-cba|2017-nba-cba>` then `verify_index.py`. The parser is
a monotonic state machine over body headers (§3-style scrambles are handled by ordering, not
regex) — if a future CBA changes header formatting, adjust `ARTICLE_HDR`/`SECTION_HDR` there.

## Standards
Follow the workspace [`STANDARDS.md`](../STANDARDS.md): `__file__`-relative paths (no hard-coded
user paths), logic behind `main()`, loud failures, `subprocess.run(..., check=True)`, HTTP with
timeout + retry. This is a personal research tool (lighter tier) but the pipeline scripts meet
the release bar so the corpus is reproducible.
