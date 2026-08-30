/** Fixed reference points and formatters for the engine. */

/** The 2023-24 Salary Cap ($136.021M) — the CBA scales several trade allowances off it
 *  (e.g. the Expanded TPE's "$7.5M × currentCap / 2023-24 cap" branch, Art VII §6(j)(1)(iv)). */
export const CAP_2023_24 = 136_021_000;

/** Max-salary tiers as a share of the cap (Art II §7). A player at/above these is "max-level."
 *  Note: many max deals were signed in prior years at a lower cap, so a current salary slightly
 *  under the tier can still be a max contract — we classify off current salary as an approximation. */
export const MAX_TIER_SHARE = 0.25; // 25% of cap (0-6 YOS max)
export const SUPERMAX_TIER_SHARE = 0.34; // ~35% tier (designated veteran), with rounding slack

export function classifyMaxLevel(salary: number, cap: number): "supermax" | "max" | null {
  if (salary >= SUPERMAX_TIER_SHARE * cap) return "supermax";
  if (salary >= MAX_TIER_SHARE * cap) return "max";
  return null;
}

export function usd(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}
