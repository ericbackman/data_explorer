import type {
  AcquireResult,
  ApronTier,
  CBAConstants,
  League,
  PlayerContract,
  TeamState,
  Verdict,
} from "./types";
import { CAP_2023_24, usd } from "./constants";
import { computeTeamState } from "./teamState";

/** Realistic cap on how many contracts a team will bundle to match one incoming star. Real
 *  matching packages are 1–3 salaries plus filler; the roster minimum (Art XXIX) prevents gutting.
 *  Bounding it here is what lets "hard_blocked" mean something. */
export const MAX_OUTGOING_PIECES = 4;

/**
 * Maximum salary an acquiring team may take back for a given outgoing salary, under the
 * Expanded Traded Player Exception (Art VII §6(j)(1)(iv), 2023 CBA):
 *
 *   greater of  { lesser of [ 200% + $250k ] and [ 100% + $7.5M×capRatio ] }
 *               and { 125% + $250k }
 *
 * The $250k cushion is zeroed once the post-trade team salary would exceed the First Apron
 * (§6(j)(3)) — the caller passes `cushion` accordingly. This is the single most-misquoted rule
 * in the CBA; the old "125% + $100k" tier no longer exists.
 */
export function maxTakeback(outgoing: number, cushion: number, capRatio: number): number {
  const scaled = 7_500_000 * capRatio;
  const richBand = Math.min(2 * outgoing + cushion, outgoing + scaled);
  const floorBand = 1.25 * outgoing + cushion;
  return Math.max(richBand, floorBand);
}

/**
 * ── TASTE SEAM (Eric) ──────────────────────────────────────────────────────────────────────
 * Turn raw cap-feasibility + player flags into the destination's final verdict. This is the
 * "how strict is a possibility?" policy — the one place opinion lives, not CBA math.
 *
 * The tiers capture the apron COST, not just yes/no — because under the 2023 rules almost any
 * team can build *a* legal package; what differs is where it leaves them on the ladder:
 *   - no legal package ⇒ "hard_blocked"
 *   - lands the team OVER the first apron (loses the aggregation/MLE tools), or it's already over
 *     the second apron and can only swap ⇒ "restricted"
 *   - lands the team UNDER the first apron (cap room or a clean match) ⇒ "can_acquire"
 *
 * A no-trade clause is deliberately NOT folded in here — it applies equally to all 29 destinations
 * (the player can veto any), so it's surfaced once as a player-level flag in the UI rather than
 * making every cap-room team look apron-restricted.
 */
export function classifyVerdict(
  feasible: boolean,
  tier: ApronTier,
  resultingSalary: number,
  firstApron: number,
): Verdict {
  if (!feasible) return "hard_blocked";
  if (tier === "over_second_apron") return "restricted"; // swap-only, can't add net salary
  if (tier === "over_first_apron") return "restricted"; // already apron-hard-capped today
  if (resultingSalary > firstApron) return "restricted"; // this trade would push them over
  return "can_acquire";
}

/** Can `state.team` legally acquire `player`? Tries methods from least to most costly. */
export function canTeamAcquire(
  player: PlayerContract,
  state: TeamState,
  c: CBAConstants,
): AcquireResult {
  const S = player.salary;
  const abbr = state.team.abbr;
  const capRatio = c.salaryCap / CAP_2023_24;
  const T = state.totalSalary;

  const done = (
    feasible: boolean,
    method: AcquireResult["method"],
    names: string[],
    out: number,
    resulting: number,
    reasons: string[],
  ): AcquireResult => ({
    team: abbr,
    verdict: classifyVerdict(feasible, state.tier, resulting, c.firstApron),
    method,
    outgoingExample: names,
    outgoingSalary: out,
    resultingSalary: resulting,
    reasons,
  });

  // 1) Absorb into cap room (§6(j)(1)(v)) — the cleanest path.
  if (state.roomUnderCap >= S) {
    return done(true, "cap_room", [], 0, T + S, [
      `Has ${usd(state.roomUnderCap)} in cap room — absorbs ${player.name}'s ${usd(S)} outright, no matching salary needed (§6(j)(1)(v)).`,
    ]);
  }

  // 2) Match salary by sending contracts out. Dead-cap money counts toward Team Salary but can't
  //    be traded, so exclude it. Grow the outgoing package largest-first.
  const roster = state.team.players.filter((p) => !p.deadCap).sort((a, b) => b.salary - a.salary);
  const outNames: string[] = [];
  let out = 0;
  for (const p of roster) {
    if (outNames.length >= MAX_OUTGOING_PIECES) break; // realistic matching-package limit
    outNames.push(p.name);
    out += p.salary;
    const resulting = T - out + S;
    const cushion = resulting > c.firstApron ? 0 : 250_000;
    const names = [...outNames];
    const aggregating = names.length > 1;

    // (a) Expanded TPE — richest ratio, but the move can't leave the team over the First Apron.
    if (resulting <= c.firstApron && maxTakeback(out, cushion, capRatio) >= S) {
      return done(true, aggregating ? "aggregate_match" : "single_match", names, out, resulting, [
        aggregating
          ? `Combine ${names.length} salaries (${usd(out)}) to match ${usd(S)} via the Expanded TPE, staying under the First Apron (§6(j)(1)(iv)).`
          : `Send ${usd(out)} to match ${usd(S)} via the Expanded TPE — take-back up to 125–200% (§6(j)(1)(iv)).`,
      ]);
    }
    // (b) Aggregated Standard TPE — 100% match, but the move can't leave the team over the 2nd Apron.
    if (resulting <= c.secondApron && out + cushion >= S) {
      return done(true, aggregating ? "aggregate_match" : "single_match", names, out, resulting, [
        aggregating
          ? `Combine ${names.length} salaries (${usd(out)}) to match ${usd(S)} at 100% — allowed only up to the Second Apron (§2(e) Row H, §6(j)(1)(ii)).`
          : `Send ${usd(out)} to match ${usd(S)} at 100% (§6(j)(1)(i)).`,
      ]);
    }
    // (c) Single-contract 100% match — the ONLY path once over the Second Apron (no aggregation).
    if (names.length === 1 && out >= S) {
      const overSecond = T >= c.secondApron;
      return done(true, overSecond ? "star_swap" : "single_match", names, out, resulting, [
        overSecond
          ? `Over the Second Apron — salaries can't be combined (§2(e) Row H). Only a star-for-star swap works: ${p.name}'s ${usd(out)} matches ${usd(S)}.`
          : `Send ${p.name} (${usd(out)}) to match ${usd(S)} outright.`,
      ]);
    }
  }

  // 3) No legal package exists.
  return done(false, "blocked", [], 0, NaN, [blockedReason(state, S, c)]);
}

function blockedReason(state: TeamState, S: number, c: CBAConstants): string {
  if (state.totalSalary >= c.secondApron) {
    return `Over the Second Apron (${usd(state.totalSalary)}). Can't aggregate salaries (§2(e) Row H) and has no single contract of ${usd(S)}+ to match — so it can't acquire a ${usd(S)} player.`;
  }
  if (state.totalSalary >= c.firstApron) {
    return `Over the First Apron. Matching ${usd(S)} would push it past the Second Apron, which the aggregation rules forbid (§2(e) Row H).`;
  }
  return `Can't assemble a package that matches ${usd(S)} without crossing an apron it isn't allowed to cross.`;
}

export interface TradeUniverse {
  player: PlayerContract;
  fromTeam: string;
  results: AcquireResult[]; // one per other team
  counts: Record<Verdict, number>;
}

/** Compute which of the other 29 teams can legally acquire `player`. */
export function computeTradeUniverse(player: PlayerContract, league: League): TradeUniverse {
  const results: AcquireResult[] = [];
  const counts: Record<Verdict, number> = {
    can_acquire: 0,
    restricted: 0,
    hard_blocked: 0,
  };
  for (const team of league.teams) {
    if (team.abbr === player.team) continue;
    const state = computeTeamState(team, league.constants);
    const r = canTeamAcquire(player, state, league.constants);
    if (r.verdict === "restricted") {
      r.reasons = [apronContextNote(state, r.resultingSalary, league.constants), ...r.reasons];
    }
    results.push(r);
    counts[r.verdict] += 1;
  }
  results.sort((a, b) => rank(a.verdict) - rank(b.verdict) || a.team.localeCompare(b.team));
  return { player, fromTeam: player.team, results, counts };
}

function rank(v: Verdict): number {
  return v === "can_acquire" ? 0 : v === "restricted" ? 1 : 2;
}

/** Leading sentence explaining WHY a destination is apron-restricted (prepended to the mechanism). */
function apronContextNote(state: TeamState, resulting: number, c: CBAConstants): string {
  if (state.tier === "over_second_apron") {
    return `${state.team.abbr} is over the second apron (${usd(state.totalSalary)}) — it can't add net salary, only swap or shed, so any deal must send out at least as much as it takes back:`;
  }
  if (state.tier === "over_first_apron") {
    return `${state.team.abbr} is already over the first apron (${usd(state.totalSalary)}) — hard-capped, so it must reshape rather than simply add:`;
  }
  return `Adding him pushes ${state.team.abbr} to ${usd(resulting)}, over the first apron (${usd(c.firstApron)}) — into hard-cap territory:`;
}
