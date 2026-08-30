# Team-Building Restrictions: Tax, First Apron, Second Apron

*Plain-English deep dive, anchored to the 2023 NBA CBA. Every rule cites its Article/Section;
`L####` = line in `corpus/text/2023-nba-cba.raw.txt`. Where the source table was hard to
extract cleanly, that's flagged.*

The 2023 CBA layers **four spending thresholds**, and the higher two ("aprons") are the
famous new teeth. The single most important thing to understand: **the apron is not a number
you're forbidden to exceed. It's a set of transactions that become forbidden — and once you
use one, it locks you below that line for the rest of the year.** That inversion is why the
second apron behaves like a hard cap without the CBA ever using the words "hard cap."

## The four thresholds (2023-24 example figures)

| Threshold | Formula | 2023-24 | What it gates |
|---|---|---|---|
| **Salary Cap** | negotiated off BRI | $136.021M | Soft cap; exceptions let you exceed it |
| **Luxury Tax Level** | 121.5% of cap (§2(a)(4)(ii), L2548) | $165.294M* | Pay a per-dollar tax above this |
| **First Apron** | Tax Level + ~$7.0M (§2(a)(4)(iii)(A), L2552) | $172.346M* | Lose 7 roster tools (rows A–G) |
| **Second Apron** | Tax Level + flat **$17.5M** (§2(a)(4)(iii)(B), L2553) | $182.794M* | Lose 4 more (rows H–K) + draft-pick freeze |

<sub>*The CBA's own worked example (using an assumed $134M cap) gives Tax $162.81M / First Apron
$169.807M / Second Apron $180.31M (L2559–2561). Actual 2023-24 figures differ slightly because
the real cap landed at $136.021M. Use the **formulas**, not the illustrative dollars.*</sub>

Note the design: the First Apron scales with cap growth, but the Second Apron is **Tax + a flat
$17.5M** (also scaled forward by cap growth from the 2023-24 base). The gap between the aprons
is deliberately narrow.

## First, the trap everyone falls into: three different "Team Salary" figures

A team has **three** distinct salary totals in Article VII, each computed differently, each
used for a different test. Conflating them is the #1 source of bad CBA takes:

1. **Team Salary** — used for the **Salary Cap** test (§4).
2. **Tax Team Salary** — used for the **luxury tax** test; measured at the start of the team's
   last regular-season game, with incentive bonuses trued-up (§2(d)(1)(i), L2626).
3. **Apron Team Salary** — used for the **apron** tests (§2(e)(1), L2737). This is a *higher*
   number: it **adds back** all "unlikely" performance bonuses, uses the **greater of** a
   restricted free agent's qualifying-offer or first-refusal amount, adds outstanding rookie
   tenders — and **subtracts** the cap holds for *unused* exceptions.

> **Practical takeaway:** you cannot look at a team's cap-sheet Team Salary and conclude it's
> "under the second apron." The apron is measured against Apron Team Salary, which can be
> millions higher. Always compute the right figure for the question.

## The luxury tax (and the repeater surcharge)

Above the Tax Level, a team pays an escalating tax measured in brackets of the **Tax Bracket
Amount** ($5M for 2023-24, scaled by cap growth after; §2(d)(1)(ii), L2642). Teams that were
taxpayers in **3 of the prior 4 seasons** pay the harsher **Repeater** rates (§2(d)(2), L2647).

**Tax rate per $1 over the line, by bracket** *(reconstructed from the §2(d)(2) rate tables,
which extract as garbled columns, then **validated against the three worked dollar examples the
CBA embeds at L2723–2728** — treat as high-confidence but table-derived):*

| Bracket over Tax Level | Standard 2023–25 | Standard 2025-26+ | Repeater 2023–25 | Repeater 2025-26+ |
|---|---|---|---|---|
| $0–5M (0–100%) | $1.50 | $1.00 | $2.50 | $3.00 |
| next 100% | $1.75 | $1.25 | $2.75 | $3.25 |
| next 100% | $2.50 | $3.50 | $3.50 | $5.50 |
| next 100% | $3.25 | $4.75 | $4.25 | $6.75 |
| 400%+ | $3.75 (+$0.50/100%) | $5.25 (+$0.50/100%) | $4.75 (+$0.50/100%) | $7.25 (+$0.50/100%) |

The 2025-26 shift is the quiet story: rates get *cheaper* at the bottom two brackets but much
*steeper* at the top — the tax curve was made more punitive for teams spending deep, reinforcing
the aprons from below.

## First Apron — what you lose (Transaction Restrictions Table rows A–G)

Cross the First Apron (or use one of these tools, which then hard-caps you there) and you lose:

- **A** — the Bi-annual Exception (§2(e)(4), L2778)
- **B** — the Non-Taxpayer Mid-Level Exception (you drop to the smaller *taxpayer* MLE) (L2779)
- **C** — acquiring a player via **sign-and-trade** (L2780)
- **D** — signing a **waived player whose prior salary was above the Non-Taxpayer MLE** (L2781)
- **E** — the **Expanded** Traded Player Exception (the generous 125–200% match) (L2782)
- **F** — using a **banked** Standard TPE from a prior season (L2783)
- **G** — the Transition TPE (2023-24 only) (L2799)

> **Widely-misreported:** rule **D** — no signing bought-out/waived players who out-earned the
> mid-level — is a **First Apron** trigger that applies to *any* team, **not** a second-apron-only
> rule as it's usually described. (Verified: Row D maps to "First Apron Level" in the table's
> Applicable-Apron column, L2781/L2789.)

There's also a **cross-contamination rule**: if a team ever uses the *taxpayer* MLE (a second-apron
tool, row K), it's *also* barred from rows A–E/A–F for the rest of the year regardless of its
salary (§2(e)(2)(iii), L2759). The taxpayer MLE and the first-apron tools are mutually exclusive.

## Second Apron — the hard-cap teeth (rows H–K + the pick freeze)

Cross the Second Apron and, on top of everything above, you lose:

- **H** — **aggregating** two or more players' salaries in a trade (the Aggregated TPE) (L2803).
  This is the big one: second-apron teams can only match salary for **one outgoing contract at a
  time**, which severely limits blockbuster construction.
- **I** — **sending cash** in a trade (L2807).
- **J** — acquiring a player via a TPE that came from a sign-and-trade (L2813).
- **K** — the **Taxpayer Mid-Level Exception** — so a second-apron team's *only* free-agent tool
  above the minimum is… gone (L2817).

### The frozen draft pick (§2(f)) — the long-tail penalty

Beginning 2024-25, being a **Second Apron Team** (Apron Team Salary over the second apron as of
your last regular-season game, §2(f)(1)(i), L2851) **freezes your first-round pick seven drafts
out** — you can't trade it, even conditionally (§2(f)(2)(i), L2856). Then:

- Second apron in **≥2 of the next 4 seasons** → that frozen pick is **moved to the end of the
  first round** (the "Draft Pick Penalty," §2(f)(1)(ii), L2854; §2(f)(2)(ii)(A), L2858).
- Second apron in **<2 of the next 4** → the pick thaws and becomes tradable again (L2861).

*Worked example (L2862): a team over the second apron in 2024-25 has its **2032** first-rounder
frozen immediately; stay over it in 2 of the following 4 years and 2032 drops to the back of the
round.*

## The mental model to keep

1. It's a **ladder of consequences**, not one wall: tax → lose first-apron tools → lose
   second-apron tools + pick.
2. The line you're tested against is **Apron Team Salary**, not cap-sheet salary.
3. The apron "hard cap" is **transaction-triggered**: you're not forbidden a dollar figure —
   you're forbidden the *moves* that would push you past it, and using such a move locks you
   under it for the year (§2(e)(2), L2751).
4. When you read "second apron" in an article, check whether the rule is *actually* second-apron
   (rows H–K + pick) or first-apron (rows A–G, incl. the buyout rule) — reporters routinely
   mix these up.

---

## Citations

| Claim | Cite | Line |
|---|---|---|
| Tax Level = 121.5% of cap | Art VII §2(a)(4)(ii) | L2548 |
| First Apron = Tax Level + ~$7.0M (scaling) | Art VII §2(a)(4)(iii)(A) | L2552 |
| Second Apron = Tax Level + flat $17.5M | Art VII §2(a)(4)(iii)(B) | L2553 |
| Worked example dollars (Tax/1st/2nd = 162.81/169.807/180.31M) | Art VII §2(a)(4) ex. | L2559–2561 |
| Apron Team Salary defined (add-backs/subtractions) | Art VII §2(e)(1) | L2737 |
| Tax Team Salary defined | Art VII §2(d)(1)(i) | L2626 |
| Tax owed above Tax Level; repeater = taxpayer 3-of-4 yrs | Art VII §2(d)(2) | L2647 |
| Tax Bracket Amount = $5M (scaled) | Art VII §2(d)(1)(ii) | L2642 |
| Tax rate tables (reconstructed; validated vs worked examples) | Art VII §2(d)(2)(i)-(ii) | L2651–2728 |
| Hard-cap gate + lock mechanism | Art VII §2(e)(2)(i) | L2751–2753 |
| Taxpayer-MLE cross-restriction (blocks rows A–E/F) | Art VII §2(e)(2)(iii) | L2759 |
| Transaction Restrictions Table (rows A–K) | Art VII §2(e)(4) | L2775–2819 |
| Row D (waived-player) → First Apron | Art VII §2(e)(4) row D | L2781 |
| Row H (aggregation) → Second Apron | Art VII §2(e)(4) row H | L2803 |
| Row K (taxpayer MLE) → Second Apron | Art VII §2(e)(4) row K | L2817 |
| $250k TPE cushion → $0 over First Apron | Art VII §6(j)(3) | L3219 |
| Second Apron Team defined | Art VII §2(f)(1)(i) | L2851 |
| Draft Pick Penalty = final pick in round | Art VII §2(f)(1)(ii) | L2854 |
| Pick frozen 7 drafts out | Art VII §2(f)(2)(i) | L2856 |
| Penalty if 2nd-apron ≥2 of next 4 yrs | Art VII §2(f)(2)(ii) | L2858–2861 |
| League-wide cash-in-trade cap = 5.15% of cap | Art VII §8(a) | L3345 |

*Cross-refs: how these restrictions bite in an actual trade → [`trades.md`](trades.md); the
navigation layer → [`../SEMANTIC_LAYER.md`](../SEMANTIC_LAYER.md).*
