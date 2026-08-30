# NBA CBA — Agentic Semantic Layer

**Purpose.** This is the navigation manual an AI agent reads *before* answering a question
about the NBA Collective Bargaining Agreement. The CBA is ~600 pages of interlocking defined
terms; naive keyword search fails because the words fans and reporters use ("hard cap",
"poison pill", "trade kicker", "supermax") **do not appear in the document**, and the words
that do appear ("Salary", "Room", "Apron Team Salary") are terms of art that don't mean what
they look like. This layer is the translation and routing table between the two.

> **Golden rule for agents: never answer a CBA question from memory.** Route to the governing
> Article/Section using this guide, `Read` the corpus text, and quote it. The CBA is amended
> and re-numbered between agreements; a citation you "remember" is probably from an old one.

---

## 1. The corpus (what's on disk)

| Path | What it is |
|---|---|
| `corpus/pdf/2023-nba-cba.pdf` | Official 2023 CBA (676 pp) — NBA CDN. **The current agreement** (in force 2023-24 → 2029-30, mutual opt-out after 2028-29). |
| `corpus/pdf/2017-nba-cba.pdf` | Official 2017 CBA — the prior agreement (2017-18 → 2022-23). For "what changed" and legacy deals. |
| `corpus/text/2023-nba-cba.raw.txt` | Extracted text of the 2023 CBA. **Line numbers are stable and match the `Read` tool** — they are the primary navigation unit. |
| `corpus/text/2017-nba-cba.raw.txt` | Extracted text of the 2017 CBA. |
| `semantic/2023-nba-cba.toc.json` | Structural index: every Article & Section → `{line, page}`. Machine-readable routing table. |
| `semantic/2023-nba-cba.definitions.json` | The Article I glossary (88 defined terms) → each term's `cross_refs` (the Articles it points to). |
| `semantic/apron-transaction-restrictions.json` | The §2(e)(4) "Transaction Restrictions Table" encoded — the second-apron hard-cap rules. |

The `corpus/` folder is git-ignored (copyright); rebuild it with `python tools/fetch_cba.py`.

---

## 2. How the CBA is organized

- **42 Articles** (I–XLII), each divided into numbered **Sections**, then lettered
  sub-clauses: `(a) (b) (c)…`, then `(1) (2)…`, then `(i) (ii)…`. The canonical citation is
  **Article + Section + sub-clause**, e.g. *Article VII, § 6(j)(1)(iv)* — **not** a page.
- **Article VII is the engine.** ~160 pages (pp. 131–290). It contains Basketball Related
  Income, the Salary Cap, the Tax, the **Apron Levels**, the cap **Exceptions**, extensions,
  and the trade rules. **Most questions about money, trades, and roster-building route into
  Article VII.** Everything else is comparatively self-contained.
- **Two definition layers.** The master glossary is **Article I, § 1** (88 terms, lettered
  `(a)…(iiii)`). But many operative terms are defined **inline** where they're used —
  critically, the **Apron Levels and Tax Level are defined in Article VII § 2(a), not in the
  glossary.** Always check both.

---

## 3. The navigation protocol (the algorithm)

To answer *"is X allowed / how does Y work"*:

1. **Translate** the everyday phrasing into the CBA's defined term using the **Concept Map**
   (§5 below). "Hard cap" → *Apron Level restrictions*; "trade exception" → *Traded Player
   Exception*; "Bird rights" → *Qualifying Veteran Free Agent*.
2. **Route** to the Article/Section. Use the Concept Map's citation, or look the term up in
   `definitions.json` and follow its `cross_refs`, or open `toc.json`.
3. **Jump** to the corpus: `toc.json` gives the **line number** in `2023-nba-cba.raw.txt`.
   `Read` that range.
4. **Follow cross-references.** Defined terms are **Capitalized**; when the text leans on
   another Capitalized term you don't yet understand, resolve it (glossary or inline) before
   concluding. The rules are a graph, not a paragraph.
5. **Quote and cite** Article + Section + sub-clause. If the text contradicts a "well-known"
   rule, trust the text — it's probably been amended.

---

## 4. The five gotchas that make everyone wrong

1. **The trade rules are not in "Trade Rules."** Legality of a trade is a *join* across three
   places in Article VII:
   - **§ 2(e)** — apron restrictions (the "hard cap" behaviors; the Transaction Restrictions Table).
   - **§ 6(j)** — the **Traded Player Exception**: how much salary you can take back (matching).
   - **§ 8** — trade *procedure*: cash, timing windows, sign-and-trade, consent, definition of "trade."
   A tool that reads only § 8 (labeled "Trade Rules") misses two-thirds of the machinery.
2. **The apron/tax dollar figures are defined inline in § 2(a), not the glossary.** Diffing the
   two CBAs' glossaries to find "what the second apron changed" returns **nothing** — the
   change was made by rewriting § 2 and § 6's operative text, not by adding glossary terms.
3. **Capitalized terms ≠ their English meaning.** "Salary" (§ 3), "Room" (`(kkk)`), "Team
   Salary", "Compensation" are precisely defined and differ from intuition. A number in the
   text is almost always a *defined* quantity.
4. **"Team Salary" ≠ "Apron Team Salary."** The apron is measured against **Apron Team Salary**
   (§ 2(e)(1)), a *higher* figure that adds back performance bonuses, uses the greater of
   qualifying-offer/first-refusal amounts for restricted free agents, etc. Never compare a
   team's ordinary Team Salary to an apron.
5. **The 2023 CBA restructured salary matching.** The old "125% + $100,000" tier is **gone**.
   Matching is now four named exceptions (§ 6(j)(1)(i)–(iv)) whose availability is gated by
   apron status, and over the first apron the "+$250,000" cushion drops to **$0** (§ 6(j)(3)).

---

## 5. Concept Map — everyday term → CBA term → citation

Citations are to the **2023 CBA**; `L####` is the line in `corpus/text/2023-nba-cba.raw.txt`.
✔ = verified against the text in-session; the rest are routed to the governing section (open
and confirm the sub-clause before quoting).

### Trades & salary matching
| You'll hear… | CBA term | Where | Line |
|---|---|---|---|
| "Trade exception" / "TPE" / salary matching | **Traded Player Exception** (Standard/Aggregated/Transition/Expanded) | Art VII, § 6(j) | L3207 ✔ |
| "You can take back 125% / 200%…" | § 6(j)(1)(i)–(iv) matching bands | Art VII, § 6(j)(1) | L3209 ✔ |
| "Combine salaries to match" / aggregation | **Aggregated** Standard TPE | Art VII, § 6(j)(1)(ii) | L3210 ✔ |
| "Second apron can't aggregate" | Row H of Transaction Restrictions Table | Art VII, § 2(e)(4) | L2803 ✔ |
| "Can't send cash in trades" (2nd apron) | Row I; cash cap = 5.15% of cap | Art VII, § 2(e)/§ 8(a) | L2807 / L3345 ✔ |
| "Sign-and-trade" | Signed-and-traded Contract (7-part test) | Art VII, § 8(e)(1) | L3365 ✔ |
| "Can't trade until Dec 15 / Jan 15 / 3 months" | Trade-eligibility timing | Art VII, § 8(d) | L3355 ✔ |
| "No-trade after the deadline in a contract year" | § 8(c) | Art VII, § 8(c) | L3353 ✔ |
| "Base Year Compensation / BYC" | **eliminated** — only a narrow sign-and-trade analog survives | Art VII, § 6(j)(5) | L3226 ✔ |
| "Why star trades wait until mid-January" | unprotected salary deemed protected Jan 8 | Art VII, § 6(j)(6) | L3231 ✔ |

### Contracts & quirks
| You'll hear… | CBA term | Where | Line |
|---|---|---|---|
| "Max contract" (25/30/35%) | **Maximum Annual Salary** | Art II, § 7 | L1566 ✔ |
| "Supermax" / "designated veteran" | Designated Veteran Player Contract/Extension | Art II, § 7 + Art VII, § 7 | L1566 ✔ |
| "Rose Rule" / higher-max criteria | 5th-Year Eligible / Higher Max Criteria | Art II, § 7 | L1566 ✔ |
| "Bird rights" | **Qualifying Veteran Free Agent** (3 yrs, 5-yr/8%) | Art I § 1(yy) + Art VII § 6(b) | L1367 ✔ |
| "Early Bird" | Early Qualifying Veteran Free Agent (2 yrs, 4-yr/8%) | Art I § 1(t) + Art VII § 6(b) | L1324 ✔ |
| "Mid-level / MLE" | Non-Taxpayer / Taxpayer / Room MLE | Art VII, § 6(e),(f),(g) | L3123+ |
| "Rookie scale" / team option years | Rookie Scale Contracts | Art VIII | L3577 ✔ |
| "Player/team option, ETO" | Option Clauses | Art XII | L3943 ✔ |
| "Extension" (vet / rookie) | Extensions, Renegotiations | Art VII, § 7 | L3274 ✔ |
| "Stretch provision" | cap stretch (2×+1), 15%-of-cap limit | Art VII, § 7(d)(6) | L3333 ✔ |
| "Trade kicker / trade bonus" | Trade Bonus (15%, first trade only) | Art XXIV, § 2(a) | L4700 ✔ |
| "No-trade clause" | Prohibition of No-Trade Contracts (8-and-4) | Art XXIV, § 2(b) | L4716 ✔ |
| "Poison pill" / Gilbert Arenas rule | RFA offer sheet, 1–2 YOS | Art XI, § 5(d) | L3850 ✔ |
| "Restricted FA / qualifying offer / offer sheet" | Restricted Free Agency | Art XI, § 5 | L3812 ✔ |

### Team-building limits (tax & aprons)
| You'll hear… | CBA term | Where | Line |
|---|---|---|---|
| "Luxury tax" / "tax level" | Tax Level = 121.5% of Cap | Art VII, § 2(a) | L2548 ✔ |
| "Repeater tax" | repeater tax rates | Art VII, § 2 | L2539+ |
| "First apron" | First Apron Level | Art VII, § 2(a)(iii) | L2551 ✔ |
| "Second apron" / "hard cap" | Second Apron Level + § 2(e) restrictions | Art VII, § 2(a)(iii)+§ 2(e) | L2551 / L2736 ✔ |
| "Frozen / movable draft pick" penalty | Draft Pick Penalty (2nd apron) | Art VII, § 2 | L2539+ |
| "Hard-capped by a move" | Transaction Restrictions Table | Art VII, § 2(e)(4) | L2775 ✔ |
| "Apron team salary" | Apron Team Salary (measurement base) | Art VII, § 2(e)(1) | L2737 ✔ |
| "Minimum team salary / salary floor" | Minimum Team Salary (90% of cap) | Art VII, § 2 | L2539+ |

---

## 6. Worked example — the protocol in action

**Q: "The Suns are over the second apron. Can they combine two players' salaries to trade for a star?"**

1. Translate: "combine two players' salaries" → **Aggregated** Traded Player Exception; "over
   the second apron" → **Apron Level restriction**.
2. Route: two places — the exception itself (§ 6(j)(1)(ii)) and whether the apron blocks it
   (§ 2(e), Transaction Restrictions Table, `apron-transaction-restrictions.json`).
3. Jump/read: `apron-transaction-restrictions.json` → **Row H (Aggregated Standard TPE) hard-caps
   at the Second Apron.** Read corpus L2803 to confirm.
4. Cross-reference: § 2(e)(2)(i) means a team already above the second apron *cannot* make a
   move that requires exceeding it — and aggregating is such a move.
5. Answer: **No.** A team above the second apron cannot aggregate salaries in a trade
   (Art VII, § 2(e), Row H of the Transaction Restrictions Table; the Aggregated TPE is
   § 6(j)(1)(ii)). It may still take back salary for a *single* outgoing contract via the
   Standard/Expanded TPE, subject to its own apron hard cap.

---

## 7. 2023 vs 2017 — which corpus to read

- Default to **2023** for anything current.
- Consult **2017** for: how a rule *used* to work, grandfathered contract terms, or to
  demonstrate what the second apron changed. Article/Section **numbers are mostly stable**
  between the two (e.g., trade rules are Art VII § 8 in both; matching is § 6(j) in both),
  which makes side-by-side diffing by citation practical.
- The headline structural changes in Article VII: § 2 gained the **Tax Level, Apron Levels,
  and Draft Pick Penalty**; § 12 changed from **"Escrow and Tax Arrangement"** to the
  **"Designated Share Arrangement"**; § 6(j) matching was split into the four named TPEs.

---

*Generated from the official corpus. Structural artifacts are rebuilt by
`tools/build_index.py`; see `explainers/` for the plain-English deep dives on trades,
contracts, and team restrictions.*
