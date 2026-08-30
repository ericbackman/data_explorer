/**
 * Domain types for the NBA Trade Universe engine.
 *
 * The engine answers one question — "which teams can legally acquire player X?" — under the
 * 2023 CBA's apron system. It is deliberately a *simplified* model of a very intricate document;
 * see engine/README notes and the `SIMPLIFICATIONS` constant in tradeUniverse.ts for exactly
 * what it does and does not account for. Rules are cited to Article VII of the 2023 CBA.
 */

export interface PlayerContract {
  name: string;
  team: string; // team abbreviation, e.g. "LAL"
  salary: number; // this season's salary, whole dollars
  yearsLeft?: number;
  playerOption?: boolean;
  teamOption?: boolean;
  noTrade?: boolean; // Art XXIV no-trade clause (8-and-4)
  tradeBonusPct?: number; // Art XXIV trade bonus, e.g. 0.15
  deadCap?: boolean; // waived/stretched money — counts toward Team Salary but is NOT tradeable
}

export interface Team {
  abbr: string;
  name: string;
  players: PlayerContract[];
}

export interface CBAConstants {
  salaryCap: number;
  taxLevel: number; // 121.5% of cap
  firstApron: number;
  secondApron: number;
  minTeamSalary: number; // 90% of cap
}

export interface League {
  season: string;
  as_of: string;
  source: string;
  constants: CBAConstants;
  teams: Team[];
}

/** Where a team sits on the four-threshold ladder (measured against summed salary — see notes). */
export type ApronTier =
  | "under_cap"
  | "over_cap" // between cap and tax
  | "over_tax" // between tax and first apron
  | "over_first_apron" // between first and second apron
  | "over_second_apron";

export interface TeamState {
  team: Team;
  totalSalary: number; // sum of guaranteed salaries ≈ Team Salary
  tier: ApronTier;
  roomUnderCap: number; // max(0, cap - total)
  headroomToFirstApron: number; // firstApron - total (can be negative)
  headroomToSecondApron: number; // secondApron - total (can be negative)
}

/** How an acquiring team would fit the incoming player under the cap. */
export type AcquireMethod =
  | "cap_room" // absorb into room under the cap (§6(j)(1)(v))
  | "single_match" // one outgoing contract, Expanded TPE (§6(j)(1)(iv))
  | "aggregate_match" // combine 2+ outgoing salaries (§6(j)(1)(ii))
  | "star_swap" // send back a comparable large contract (only path for 2nd-apron teams)
  | "blocked";

/**
 * can_acquire  — can take the player and ADD him (cap room, or match while staying under the
 *                team's apron ceiling with normal aggregation).
 * restricted   — legal only in a constrained way: a Second-Apron team that can reshape but not
 *                ADD net salary (must send ≥ what it takes), or a no-trade player who can veto.
 * hard_blocked — no legal matching package (within a realistic package size).
 */
export type Verdict = "can_acquire" | "restricted" | "hard_blocked";

export interface AcquireResult {
  team: string; // abbr
  verdict: Verdict;
  method: AcquireMethod;
  /** A concrete legal outgoing package the engine found (player names), if any. */
  outgoingExample: string[];
  outgoingSalary: number;
  resultingSalary: number; // team salary after the swap
  reasons: string[]; // plain-English, citation-tagged explanations
}
