# nba-cba

An **agentic knowledge layer over the NBA Collective Bargaining Agreement.** The goal: make
the CBA queryable in plain English by an AI agent that always routes to — and quotes — the
governing text, instead of hallucinating from half-remembered cap rules. Almost nobody
(reporters included) reads the actual document; this project does, and builds the scaffolding
to navigate it reliably.

## What's here

```
corpus/            # official CBA PDFs + extracted text  (git-ignored — copyright)
  pdf/  text/
semantic/          # DERIVED, machine-readable navigation artifacts (committed)
  2023-nba-cba.toc.json          # Article/Section -> {corpus line, page}
  2023-nba-cba.definitions.json  # Article I glossary (88 terms) + cross-refs
  apron-transaction-restrictions.json  # the §2(e)(4) second-apron hard-cap table
tools/             # reproducible pipeline
  fetch_cba.py     # download official PDFs + extract text
  build_index.py   # parse text -> toc.json + definitions.json
  verify_index.py  # sanity-check coverage
explainers/        # plain-English deep dives (trades, contracts, team restrictions)
SEMANTIC_LAYER.md  # ← START HERE: the navigation manual for an AI agent
```

## Quick start

```bash
python tools/fetch_cba.py            # rebuild corpus/ from the official sources
python tools/build_index.py 2023-nba-cba
python tools/build_index.py 2017-nba-cba
python tools/verify_index.py 2023-nba-cba VII   # spot-check
```

Then point an agent at [`SEMANTIC_LAYER.md`](SEMANTIC_LAYER.md).

## Sources (authoritative)

- **2023 CBA** (current; 2023-24 → 2029-30): NBA CDN. 676 pp.
- **2017 CBA** (prior): NBPA mirror.

The raw corpus is copyrighted by the NBA/NBPA and is **git-ignored**. Only *derived* analysis
(indexes, the plain-English explainers, tooling) is committed. **Keep this repo private** while
it stores verbatim excerpts; the explainers use only short attributed quotes.

## Why the CBA is hard (and the design that handles it)

The rules people care about are **not** where their names suggest. Trade legality is a join
across three sections of Article VII (§ 2(e) apron restrictions + § 6(j) salary matching +
§ 8 procedure). The apron dollar figures are defined inline in § 2(a), not the glossary. The
2023 "second apron" behaves as a near-hard-cap via a single **Transaction Restrictions Table**
(§ 2(e)(4)) that maps each move to the apron it locks you under. `SEMANTIC_LAYER.md` encodes
all of this as a routing table so an agent can find the governing text every time.

## Roadmap

1. **Corpus + semantic layer** ✅ — sourced, indexed, navigation manual written.
2. **Explainers** ✅ — trades, contracts, team restrictions, and a
   [CBA-history / who-won-and-why analysis](explainers/cba-history-and-leverage.md) (`explainers/`).
3. **Trade rule engine + "Trade Universe" web app** ✅ — [`trade-machine/`](trade-machine): a
   tested TypeScript engine (§6(j) matching, §2(e) apron ceilings, the apron-cost verdict
   gradient) over real 2026-27 salary data, and a React+Vite site showing, for every max/supermax
   player, which of the 29 teams can legally acquire him and why. `classifyVerdict` is the tunable
   policy seam; simplifications are documented in-app.
