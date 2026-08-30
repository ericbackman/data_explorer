# How NBA Trades Actually Work (Under the 2023 CBA)

*Plain-English deep dive, anchored to the 2023 NBA CBA. `L####` = line in
`corpus/text/2023-nba-cba.raw.txt`. Findings here were extracted from the text and
cross-checked; myths that the text contradicts are called out explicitly.*

## The one thing to internalize

**Trade legality is a join across three separate parts of Article VII** — not the section
labeled "Trade Rules":

- **§ 6(j)** — the **Traded Player Exception**: *how much salary you can take back.*
- **§ 2(e)** — the **apron restrictions**: *which matching tools you're even allowed to use.*
- **§ 8** — the **procedure**: cash, timing windows, sign-and-trade, consent, and the actual
  *definition* of a trade.

Read only § 8 (which is titled "Trade Rules") and you'll get roughly a third of the machinery.
The eventual "is this trade legal?" engine has to check all three.

## 1. Salary matching — the Traded Player Exception (§ 6(j))

Any team **at or above the cap** must justify the salary it takes back with a **Traded Player
Exception (TPE)** — an allowance sized off the salary it sends out. There are **five**
mechanisms (§ 6(j)(1), L3209–3215):

| Mechanism | Outgoing | Timing | Salary you can take back |
|---|---|---|---|
| **Standard TPE** | 1 player | simultaneous **or** non-simultaneous (within **1 year**) | 100% + $250k |
| **Aggregated Standard** | **2+ players** | simultaneous only | 100% of combined + $250k |
| **Transition TPE** *(2023-24 only)* | 1+ | simultaneous only | 110% + $250k |
| **Expanded TPE** | 1+ | simultaneous only | *greater of* {lesser of 200%+$250k, 100%+$7.5M×cap-ratio} *or* **125%+$250k** |
| **Room + $250k** *(under-cap teams)* | — | — | cap room + $250k (no matching needed) |

Two rules cut across all of them:

- **Over the First Apron, the "+$250,000" cushion becomes $0** (§ 6(j)(3), L3219). Matching
  tightens to *exactly* 100% / 125% — no rounding room.
- **The Expanded TPE's rich band only helps small salaries.** At ~$2M outgoing it's ~212%; by
  ~$30M outgoing the 125% floor governs. Big-money matching is effectively 125% (and 100% once
  you're over the apron).

## 2. The wrinkle that dictates the trade calendar (§ 6(j)(6))

An outgoing player's "Salary" *for matching purposes* isn't his face salary — it's **reduced by
any Base Compensation that isn't fully protected** at the moment of the trade (§ 6(j)(6), L3227).
An unprotected $8M contract traded in October generates only a fraction of an $8M exception.

**But the text deems every contract fully protected from January 8 through the end of the regular
season** (L3231). *This is the mechanical reason star trades cluster around the deadline* — before
January 8, unprotected salary shrinks your matching; after it, the full number counts. Casual
explanations never mention this; the CBA even walks a worked example generating $1M / $2M / $8M /
$1M exceptions for the *same* contract at four different trade dates (L3234).

Also: no TPE arises from trading a Two-Way player (§ 6(j)(8)), or from a player you used a
Disabled Player Exception on that year (§ 6(j)(7)).

## 3. Aggregation and the second-apron ban

"Aggregation" = combining two or more outgoing salaries to match one incoming player. It isn't
banned by a prohibition sentence — it's gated by the **Transaction Restrictions Table** (§ 2(e)(4)):

- Using the **Aggregated Standard TPE** hard-caps you at the **Second Apron** (Row H, L2803).
  So a team **already over the second apron cannot aggregate at all** — it can only match salary
  for **one outgoing contract at a time.** This is the single biggest constraint on second-apron
  roster-building.
- The higher-ratio **Expanded TPE** (which can also combine outgoing salaries) is blocked even
  earlier, at the **First Apron** (Row E, L2782).

Separately, § 6(m) (L3261) bans combining *different exception types* (e.g., MLE + Bi-annual) to
sign one bigger player — distinct from TPE aggregation.

> Measurement reminder: all of this is tested against **Apron Team Salary** (§ 2(e)(1)), a higher
> figure than cap-sheet Team Salary. See [team-restrictions.md](team-restrictions.md).

## 4. Base Year Compensation is dead (mostly)

**"Base Year" appears zero times in the 2023 CBA** (confirmed by full-corpus search). The old BYC
rule — which deemed a just-re-signed player's tradeable salary to be less than his real salary —
**is not a general mechanism anymore.** If you've seen it invoked recently, that's stale.

The only survivor is narrow: § 6(j)(5) (L3226). *Only in a § 8(e) sign-and-trade*, when a
Qualifying/Early-Qualifying free agent re-signs above a threshold, his salary for the assignor
team's TPE math is deemed the **greater of** his prior salary or **50% of the new first-year
salary**. That 50% structure echoes BYC — but it's scoped to sign-and-trades only, not ordinary
re-sign-then-trade.

## 5. Cash (§ 8(a))

Teams may pay/receive up to **5.15% of the cap in cash across all trades per year** (L3345). Key
details:
- It's an **annual aggregate**, and it **cannot be netted** — pay the max in one trade and
  receive the max in another, and you're done sending *or* receiving cash for the year (L3346).
- **Paying cash hard-caps you at the Second Apron** (Row I, L2807) — a team over the second apron
  can't send cash in a trade at all.

## 6. Sign-and-trade (§ 8(e)) — a seven-part checklist

A free agent can sign with his prior team and be immediately traded, **but only if all seven**
hold (§ 8(e)(1), L3365):

1. He **finished the prior season** on that team's roster.
2. The deal is **3–4 seasons** (excluding option years).
3. It's **not** signed via the Non-Taxpayer MLE or Room MLE.
4. **Year 1 is fully protected** for lack of skill.
5. It's signed **before the regular season** starts.
6. A higher-max-eligible 5th-year player is capped at **25% of the cap**.
7. The **acquiring team has Room** for year-one salary.

Consequences and mechanics: the acquiring team is **hard-capped at the First Apron** (Row C,
L2780); the contract can't contain an Exhibit 6 physical clause (§ 8(e)(3)); a trade bonus doesn't
pay out on the initial sign-and-trade (Art XXIV § 2(a)); and the § 8(d) waiting periods are waived
for the *initial* trade (L3359). The whole mechanism runs on an Exhibit-8 amendment requiring the
contract be **traded within 48 hours** (Art II § 3(q), L1477).

## 7. Timing & eligibility gates (§ 8(b)–(k))

| Rule | When it bites | Cite |
|---|---|---|
| **Consent required** | one-year QVFA/EQVFA ("Bird-track") free agents can't be traded without consent | § 8(b), L3347 |
| **No trade after the deadline** in a contract's last (or possibly-last) season | § 8(c), L3353 |
| **30-day rule** | draft rookies & two-way signees, 30 days after signing | § 8(d)(i), L3357 |
| **3-month / Dec 15 rule** | newly-signed free agents (waived for a sign-and-trade's first trade) | § 8(d)(ii), L3359 |
| **3-month / Jan 15 rule** | a prior-team re-signing with a **>120% raise** that pushes the team over the cap | § 8(d)(iii), L3361 |
| **6-month lockout** | after a big extension/renegotiation (both directions) | § 8(f)(i), L3378 |
| **1-year lockout** | after a Designated Veteran (supermax) extension/contract | § 8(f)(ii), L3379 |
| **Re-sign ban** | a traded-then-waived player can't return to the trading team for ~1 year | § 8(h), L3385 |

"Trade" is defined (§ 8(k), L3391) as a negotiated inter-team assignment via a league trade
call — it **excludes** waiver claims.

## 8. No-trade clauses (Article XXIV)

The default is that **no-trade clauses are prohibited** — "No Player Contract may contain any
prohibition or limitation of an NBA Team's right to assign such Contract" (§ 1, L4695). The lone
exception (§ 2(b), L4716): a player with **8+ years of service and 4+ with his current team** may
have a real no-trade clause. (This is why they're so rare — LeBron, Bradley Beal-type situations.)

---

## The trade-legality checklist (for the phase-2 engine)

To decide if a proposed trade is legal you need, at minimum:
1. Each outgoing player's **protection-adjusted salary** (§ 6(j)(6)).
2. Which of the five **§ 6(j)(1) mechanisms** applies + its ratio and simultaneity constraint.
3. The resulting **Apron Team Salary** vs. the Row-specific apron ceiling (§ 2(e)(4) table).
4. The **§ 8(a) cumulative cash ledger** for the year.
5. The **player-specific timing gates** (§ 8(b)–(f)).
6. If a sign-and-trade: the full **§ 8(e)(1) seven-part checklist**.
7. If picks are involved: the **second-apron pick freeze** (§ 2(f), see team-restrictions.md).

---

## Citations (selected — full set mirrors the section cites above)

| Claim | Cite | Line |
|---|---|---|
| Standard TPE = 100% + $250k (sim/non-sim ≤1yr) | Art VII §6(j)(1)(i) | L3209 |
| Aggregated TPE = 100% combined + $250k (sim only) | Art VII §6(j)(1)(ii) | L3210 |
| Transition TPE = 110% + $250k (2023-24 only) | Art VII §6(j)(1)(iii) | L3213 |
| Expanded TPE formula (greater of 200%-capped / 125%) | Art VII §6(j)(1)(iv) | L3214 |
| $250k cushion → $0 over First Apron | Art VII §6(j)(3) | L3219 |
| Matching salary reduced by unprotected Base Comp | Art VII §6(j)(6) | L3227 |
| Deemed fully protected Jan 8 → season end | Art VII §6(j)(6)(i) | L3231 |
| "Base Year" — 0 occurrences in corpus | (absent) | — |
| Sign-and-trade BYC-analog (greater of prior / 50% new) | Art VII §6(j)(5) | L3226 |
| Aggregated TPE → Second Apron hard cap | Art VII §2(e)(4) Row H | L2803 |
| Cash in trade → Second Apron hard cap | Art VII §2(e)(4) Row I | L2807 |
| Sign-and-trade acquisition → First Apron hard cap | Art VII §2(e)(4) Row C | L2780 |
| Cash limit 5.15% of cap, annual, not netted | Art VII §8(a) | L3345–3346 |
| Sign-and-trade 7-part requirements | Art VII §8(e)(1) | L3365 |
| No trade after deadline in last contract year | Art VII §8(c) | L3353 |
| Dec 15 / Jan 15 / 30-day / 3-month gates | Art VII §8(d) | L3355–3364 |
| Definition of "trade" excludes waivers | Art VII §8(k) | L3391 |
| No-trade clauses prohibited; 8-and-4 exception | Art XXIV §1, §2(b) | L4695 / L4716 |

*Cross-refs: apron/tax mechanics → [team-restrictions.md](team-restrictions.md); contract terms
(max, Bird, extensions) → [contracts.md](contracts.md); navigation → [../SEMANTIC_LAYER.md](../SEMANTIC_LAYER.md).*
