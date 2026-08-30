import type { CBAConstants, Team, TeamState, ApronTier } from "./types";

/**
 * Compute a team's position on the four-threshold ladder.
 *
 * SIMPLIFICATION: "Team Salary" here is the sum of the roster's guaranteed salaries. The real
 * figure includes cap holds, dead money, and incomplete-roster charges, and the apron is measured
 * against the higher "Apron Team Salary" (Art VII §2(e)(1)) which adds back unlikely bonuses etc.
 * For a trade-legality overview this approximation places teams on the correct side of each line in
 * the large majority of cases; exact edge cases near a threshold should be verified against a cap sheet.
 */
export function computeTeamState(team: Team, c: CBAConstants): TeamState {
  const totalSalary = team.players.reduce((sum, p) => sum + p.salary, 0);
  return {
    team,
    totalSalary,
    tier: tierFor(totalSalary, c),
    roomUnderCap: Math.max(0, c.salaryCap - totalSalary),
    headroomToFirstApron: c.firstApron - totalSalary,
    headroomToSecondApron: c.secondApron - totalSalary,
  };
}

function tierFor(total: number, c: CBAConstants): ApronTier {
  if (total < c.salaryCap) return "under_cap";
  if (total < c.taxLevel) return "over_cap";
  if (total < c.firstApron) return "over_tax";
  if (total < c.secondApron) return "over_first_apron";
  return "over_second_apron";
}
