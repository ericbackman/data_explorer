import { describe, it, expect } from "vitest";
import type { CBAConstants, PlayerContract, Team } from "./types";
import { computeTeamState } from "./teamState";
import { canTeamAcquire, maxTakeback, computeTradeUniverse, classifyVerdict } from "./tradeUniverse";

// Round test constants (cap 140M → tax 121.5%, aprons roughly to scale).
const C: CBAConstants = {
  salaryCap: 140_000_000,
  taxLevel: 170_100_000,
  firstApron: 178_000_000,
  secondApron: 190_000_000,
  minTeamSalary: 126_000_000,
};

function team(abbr: string, salaries: number[]): Team {
  return {
    abbr,
    name: abbr,
    players: salaries.map((s, i) => ({ name: `${abbr}-p${i}`, team: abbr, salary: s })),
  };
}
const star = (name: string, tm: string, salary: number, extra: Partial<PlayerContract> = {}): PlayerContract =>
  ({ name, team: tm, salary, ...extra });

describe("maxTakeback — §6(j) matching tiers", () => {
  it("large outgoing is governed by the 125% floor band", () => {
    // 40M out: 125%*40 + 0.25 = 50.25M beats the (capped) 200% band.
    expect(maxTakeback(40_000_000, 250_000, 1)).toBeCloseTo(50_250_000, -3);
  });
  it("small outgoing is governed by the ~200% band", () => {
    // 4M out: min(8.25M, 4M+7.5M)=8.25M beats 125% floor (5.25M).
    expect(maxTakeback(4_000_000, 250_000, 1)).toBeCloseTo(8_250_000, -3);
  });
  it("over the first apron the $250k cushion disappears (§6(j)(3))", () => {
    expect(maxTakeback(40_000_000, 0, 1)).toBeCloseTo(50_000_000, -3);
  });
});

describe("classifyVerdict — the apron-cost gradient", () => {
  const fa = 178_000_000;
  it("under the first apron after the trade ⇒ can_acquire", () => {
    expect(classifyVerdict(true, "over_cap", 160_000_000, fa)).toBe("can_acquire");
  });
  it("lands over the first apron ⇒ restricted (lost tools)", () => {
    expect(classifyVerdict(true, "over_tax", 185_000_000, fa)).toBe("restricted");
  });
  it("already over the first apron ⇒ restricted regardless of the package", () => {
    expect(classifyVerdict(true, "over_first_apron", 150_000_000, fa)).toBe("restricted");
  });
  it("already over the second apron ⇒ restricted regardless of resulting salary", () => {
    expect(classifyVerdict(true, "over_second_apron", 120_000_000, fa)).toBe("restricted");
  });
  it("infeasible ⇒ hard_blocked", () => {
    expect(classifyVerdict(false, "under_cap", 0, fa)).toBe("hard_blocked");
  });
});

describe("canTeamAcquire", () => {
  it("under-cap team with room absorbs the player outright", () => {
    const t = team("ROOM", [40_000_000, 30_000_000, 20_000_000, 10_000_000]); // total 100M, room 40M
    const r = canTeamAcquire(star("Max", "XXX", 35_000_000), computeTeamState(t, C), C);
    expect(r.verdict).toBe("can_acquire");
    expect(r.method).toBe("cap_room");
    expect(r.outgoingExample).toHaveLength(0);
  });

  it("deep over the second apron with only small contracts is hard-blocked", () => {
    // 15 × $14M = $210M (well over the 2nd apron), no single ≥$45M; even 4 pieces ($56M) can't
    // net the team back under the apron, and aggregation is illegal while it stays over.
    const t = team("DEEP", Array(15).fill(14_000_000));
    const state = computeTeamState(t, C);
    expect(state.totalSalary).toBeGreaterThan(C.secondApron);
    const r = canTeamAcquire(star("Max", "XXX", 45_000_000), state, C);
    expect(r.verdict).toBe("hard_blocked");
    expect(r.reasons[0]).toMatch(/Second Apron/);
  });

  it("over the second apron with a comparable star is restricted (swap only, can't add)", () => {
    const t = team("OVER2B", [48_000_000, 30_000_000, 28_000_000, 26_000_000, 24_000_000, 22_000_000, 20_000_000]);
    const state = computeTeamState(t, C);
    expect(state.totalSalary).toBeGreaterThanOrEqual(C.secondApron);
    const r = canTeamAcquire(star("Max", "XXX", 45_000_000), state, C);
    expect(r.verdict).toBe("restricted"); // 2nd-apron team can reshape but not ADD salary
    expect(r.method).toBe("star_swap");
    expect(r.outgoingExample).toEqual(["OVER2B-p0"]); // the 48M star
  });

  it("a mid team aggregates salaries to match a max incoming", () => {
    const t = team("MID", [30_000_000, 25_000_000, 20_000_000, 15_000_000, 12_000_000, 10_000_000, 8_000_000]); // 120M, under tax
    const r = canTeamAcquire(star("Max", "XXX", 45_000_000), computeTeamState(t, C), C);
    expect(r.verdict).toBe("can_acquire");
    expect(["aggregate_match", "single_match"]).toContain(r.method);
    expect(r.outgoingSalary).toBeGreaterThanOrEqual(36_000_000); // enough to match 45M via Expanded
  });

  it("per-team verdict reflects cap feasibility, not the player's no-trade clause", () => {
    // A no-trade clause is a player-level veto (all 29 teams), surfaced in the UI — it must NOT
    // make a cap-room team look apron-restricted.
    const t = team("ROOM", [40_000_000, 30_000_000, 20_000_000, 10_000_000]);
    const r = canTeamAcquire(star("NoTrade", "XXX", 30_000_000, { noTrade: true }), computeTeamState(t, C), C);
    expect(r.verdict).toBe("can_acquire");
  });
});

describe("computeTradeUniverse", () => {
  it("excludes the player's own team and tallies verdicts", () => {
    const league = {
      season: "test",
      as_of: "test",
      source: "test",
      constants: C,
      teams: [
        team("AAA", [50_000_000, 20_000_000, 10_000_000]), // player's team — excluded
        team("BBB", [20_000_000, 10_000_000]), // lots of room → can acquire
        team("CCC", Array(15).fill(14_000_000)), // deep over 2nd apron, small contracts → blocked
      ],
    };
    const player = star("Star", "AAA", 45_000_000);
    const u = computeTradeUniverse(player, league);
    expect(u.results).toHaveLength(2); // AAA excluded
    expect(u.counts.can_acquire + u.counts.hard_blocked).toBe(2);
    expect(u.results.find((r) => r.team === "BBB")?.verdict).toBe("can_acquire");
    expect(u.results.find((r) => r.team === "CCC")?.verdict).toBe("hard_blocked");
  });
});
