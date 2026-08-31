# NBA Contracts: Maxes, Bird Rights, Options, Extensions & the Quirks

*Plain-English deep dive, anchored to the 2023 NBA CBA. `L####` = line in
`corpus/text/2023-nba-cba.raw.txt`. Media shorthands ("supermax", "poison pill") are flagged:
none are CBA language.*

## Translation note (read first)

The CBA **never** uses the terms fans and reporters do. Keep the mapping straight or you'll
never find the governing text:

| You say… | CBA actually says… |
|---|---|
| Supermax | **Designated Veteran Player** Contract/Extension |
| Rose Rule / higher max | **Higher Max Criteria** / **5th Year Eligible Player** |
| Bird rights | **Qualifying Veteran Free Agent** (3 yrs) |
| Early Bird | **Early Qualifying Veteran Free Agent** (2 yrs) |
| Trade kicker | **Trade Bonus** (and it lives in Article XXIV, not Art II) |
| Poison pill / Gilbert Arenas | Offer Sheet to an RFA with **1–2 Years of Service** (Art XI § 5(d)) |

## 1. Maximum salary: three tiers plus a floor (Art II § 7)

Max annual salary is a share of the cap set by **Years of Service (YOS)**, OR **105% of the
player's prior salary**, whichever is greater:

| YOS | Max |
|---|---|
| 0–6 | **25%** of cap |
| 7–9 | **30%** of cap |
| 10+ | **35%** of cap *(automatic, no award criteria)* |

The **105%-of-prior-salary floor** (L1568) is underrated: it stops a player already earning near
an old-era max from being forced into a pay cut when the raw percentage would be lower. It applies
to new deals, renegotiations, extensions, and trade-bonus payouts alike.

**Raises:** 5%/yr on standard deals; **8%/yr** only when re-signing with your own team using Bird
or Early-Bird rights (§ 5(a), L3090/3095).

## 2. The "supermax": Designated Veteran Player (Art II § 7)

Two *different* jumps use the **identical Higher Max Criteria** (L1569): a huge source of
confusion, because people assume 35% needs a bigger achievement than 30%. It doesn't; the
difference is which YOS bracket you're in.

**Higher Max Criteria** (either one qualifies):
- All-NBA (any team) or Defensive Player of the Year: last season, or 2 of the last 3; or
- MVP in any of the last 3 seasons.

- **25% → 30%** for a **5th-Year-Eligible Player** (exactly 4 YOS) who meets the criteria (L1568).
  If his deal exceeds 25%, it must run **4+ seasons** (L1621).
- **30% → 35%** for a player with **8–9 YOS** who's stayed with one team: a **Designated Veteran
  Player Contract** (L1571). Rookie-scale players can pre-lock this at extension time via an award
  table: All-NBA 2nd → 27%, 1st → 28%, MVP → 30% (L1602).

**Two things the text says that "common knowledge" gets wrong:**
- **A trade in years 1–4 does *not* disqualify** a player from the supermax: the tenure test
  explicitly allows changing teams "only by trade during the first four Salary Cap Years" (L1571).
  Leaving via *free agency* is what breaks it.
- **There is no numeric limit** in the 2023 CBA on how many Designated Veteran players a team may
  carry. I searched for it; it isn't there. If you've heard "only one supermax per team," treat it
  as a myth (it may be a lapsed 2011-CBA feature; the current text doesn't impose it).

A Designated Veteran Contract runs **exactly 5 seasons**; the Extension version, **exactly 6**
(Art I defs, L1310/1316), and can't be re-traded for **1 year** (§ 8(f)(ii), L3379).

## 3. Bird rights (Art I defs + Art VII § 6(b))

| Type | Years w/ team | Max length (own team) | Max raise |
|---|---|---|---|
| **Qualifying VFA** (full Bird) | 3 | **5 seasons** | 8% |
| **Early Qualifying VFA** (Early Bird) | 2 | **4 seasons** | 8% |
| **Non-Qualifying VFA** (Non-Bird) | — | 4 seasons | 5% |

The precise nuance: **Early Bird gets the same 8% raise as full Bird, but only full Bird gets the
5th year** (Art IX § 1 lists only the Qualifying VFA for the length exception, L3612). First-year
salary ceilings: full Bird → the § 7 max; Early Bird → greater of 175% of prior or 105% of league
average (L3131); Non-Bird → greater of 120% of prior or 120% of the minimum (L3128).

## 4. Rookie scale (Art VIII)

First-round picks sign a **2-guaranteed + team-option (yr 3) + team-option (yr 4)** deal (L3577).
Negotiable pay runs from an **80% floor to a 120% ceiling** of the Rookie Scale Amount (L3594),
and that 80% is also the minimum guaranteed protection. After year 4, a **Qualifying Offer** makes
the player a Restricted Free Agent; no QO → Unrestricted (L3812). Teams can also make a **Maximum
Qualifying Offer**, a full 5-year max, alongside the 1-year QO; the player picks one (L3814).

## 5. Options (Art XII)

The CBA separates two things fans blur:
- **Team / Player Option.** *adds* at most **1 year**, exercisable once, pays **≥100%** of the
  prior year, all other terms frozen (L3943/3946).
- **Early Termination Option (ETO).** Lets a player *leave early*; **can't take effect before the
  end of the 4th season** (L3953), so it's only meaningful on 5+ year deals. Can't be added to a
  contract that didn't have one (except a rookie-scale extension may add one).
- **No conditional options.** The right to exercise, and an ETO's effective year, are fixed at
  signing (L3957).

## 6. Extensions (Art VII § 7)

- **Veteran extension:** a 3–4 yr deal is extendable after its **2nd anniversary**, a 5–6 yr deal
  after its **3rd**; 1–2 yr deals can't be extended (L3276). New first-year salary up to **140%**
  of the final year (L3285); max **5 total** seasons from signing; 8% raises.
- **Rookie-scale extension:** signed in the window before the 4th-year season; up to the § 7 max
  (L3303).
- **Extend-and-trade:** capped at **3 seasons** (pre-2024-25) / **4** (after), and the raise rate
  drops to **5%.** The penalty for tying an extension to a trade (L3369, L3291).
- **Renegotiation:** only for **4+ year** deals, after the 3rd anniversary, and **only by a team
  under the cap** (L3311). Over-the-cap teams simply can't renegotiate, which is why they're rare.

## 7. The special clauses everyone name-drops

### Stretch provision: two mechanisms, same 2×+1 formula
1. **Cash** (Art II § 4(k), L1538): what a team actually still *pays* a waived player with >$500k
   guaranteed: spread over **twice the remaining seasons + 1**.
2. **Cap** (Art VII § 7(d)(6), L3333): a team's *election* to spread the waived player's cap hit
   the same way: capped so stretched money can't exceed **15% of the cap** in any year (L3338).

### Trade Bonus ("trade kicker"): Art XXIV, not Art II
Capped at **15% of remaining Base Compensation** (L4700), payable only the first time a
contract is traded (L4699), and re-clipped if paying it would push the player over his max
(Art II § 7(f)). It lives in the No-Trade-Contracts article: an easy place to miss it.

### No-trade clause: Art XXIV
**Prohibited by default** (§ 1, L4695). The lone exception (§ 2(b), L4716): **8+ years of service
and 4+ with the team**. It's purely a tenure gate, not about stardom or salary, which is why
they're vanishingly rare.

### Poison pill / "Gilbert Arenas": Art XI § 5(d)
For offer sheets to a restricted free agent with **1–2 YOS** (L3850): years 1–2 are capped at the
**Non-Taxpayer MLE**, but years 3–4 can leap to the player's real max (yr 4 limited to a 4.5%
raise, fully guaranteed, no bonuses). The "poison": for the new team's cap-**Room** test, the salary
counts as the **4-year average** (L3852), so only a team with big room can even make the offer,
and if the original team declines to match, the player's salary is flattened to that average.

---

## Myths this text debunks
- **"Only one supermax per team".** Not in the 2023 CBA (no numeric limit found).
- **"A traded player can't get the supermax".** False; a trade in years 1–4 is allowed.
- **"Supermax / Rose Rule / trade kicker / poison pill / Gilbert Arenas provision"**: all media
  coinages; none appear in the document. Use the CBA's terms to stay traceable to the text.

---

## Citations (selected)

| Claim | Cite | Line |
|---|---|---|
| Max tiers 25/30/35% + 105% floor | Art II §7(a) | L1568 |
| Higher Max Criteria (All-NBA/DPOY/MVP) | Art II §7(a)(i) | L1569 |
| Designated Veteran 35% + trade-in-yrs-1–4 tenure | Art II §7(a)(ii) | L1571 |
| 35% automatic at 10+ YOS | Art II §7(a)(iii) | L1575 |
| Rookie-scale supermax award table (27/28/30%) | Art II §7(e) | L1602 |
| Designated Veteran Contract = 5 yrs / Extension = 6 | Art I §1(q),(r) | L1310/1316 |
| Non-Bird 5% / Bird 8% raises | Art VII §5(a) | L3090/3095 |
| Qualifying VFA (Bird) = 3 seasons | Art I §1(yy) | L1367 |
| Early Qualifying VFA (Early Bird) = 2 seasons | Art I §1(t) | L1324 |
| Bird 5-yr length; general 4-yr max | Art IX §1 | L3612 |
| Early Bird first-year formula (175%/105% avg) | Art VII §6(b)(3) | L3131 |
| Rookie scale 2+option+option | Art VIII §1(a) | L3577 |
| Rookie scale 80% floor / 120% ceiling | Art VIII §1(c) | L3594 |
| Qualifying Offer → RFA; Maximum Qualifying Offer | Art XI §4(a) | L3812/3814 |
| Options add 1 yr, ≥100% | Art XII §1–2 | L3943 |
| ETO no earlier than end of 4th season | Art XII §2(b) | L3953 |
| Veteran extension timing + 140% cap | Art VII §7(a) | L3276/3285 |
| Extend-and-trade 3/4-yr + 5% raise | Art VII §8(e)(2), §7(a)(3)(iii) | L3369/3291 |
| Renegotiation only by under-cap team | Art VII §7(c)(3) | L3311 |
| Stretch: cash (2×+1) | Art II §4(k) | L1538 |
| Stretch: cap election, 15%-of-cap limit | Art VII §7(d)(6) | L3333/3338 |
| Trade Bonus 15%, first trade only | Art XXIV §2(a) | L4699/4700 |
| No-trade prohibited; 8-and-4 exception | Art XXIV §1, §2(b) | L4695/4716 |
| Poison pill (RFA 1–2 YOS), 4-yr-average Room | Art XI §5(d) | L3850/3852 |

*Cross-refs: trade mechanics → [trades.md](trades.md); tax/apron limits →
[team-restrictions.md](team-restrictions.md); navigation → [../SEMANTIC_LAYER.md](../SEMANTIC_LAYER.md).*
