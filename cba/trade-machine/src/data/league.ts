import type { League, PlayerContract, Team } from "../engine/types";
import { classifyMaxLevel } from "../engine/constants";
import raw from "./league.json";

/** The scrape writes snake_case contract flags; the engine uses camelCase. Normalize here so the
 *  data format and the engine stay decoupled. */
interface RawPlayer {
  name: string;
  team: string;
  salary: number;
  years_left?: number;
  player_option?: boolean;
  team_option?: boolean;
  no_trade?: boolean;
  trade_bonus_pct?: number;
}

function normalizePlayer(p: RawPlayer, teamAbbr: string): PlayerContract {
  return {
    name: p.name,
    team: teamAbbr,
    salary: p.salary,
    yearsLeft: p.years_left,
    playerOption: p.player_option,
    teamOption: p.team_option,
    noTrade: p.no_trade,
    tradeBonusPct: p.trade_bonus_pct,
    // The scrape names waived/stretched money "… (dead cap)". It counts toward Team Salary but
    // can't be traded, so flag it here and exclude it from outgoing packages in the engine.
    deadCap: /\(dead cap\)/i.test(p.name),
  };
}

const rawLeague = raw as unknown as {
  season: string;
  as_of: string;
  source: string;
  constants: League["constants"];
  teams: { abbr: string; name: string; players: RawPlayer[] }[];
};

const teams: Team[] = rawLeague.teams.map((t) => ({
  abbr: t.abbr,
  name: t.name,
  players: t.players.map((p) => normalizePlayer(p, t.abbr)),
}));

export const league: League = {
  season: rawLeague.season,
  as_of: rawLeague.as_of,
  source: rawLeague.source,
  constants: rawLeague.constants,
  teams,
};

export interface MaxPlayer extends PlayerContract {
  level: "supermax" | "max";
  teamName: string;
}

/** Every max- or supermax-level player, richest first — the subjects of the tool. */
export const maxPlayers: MaxPlayer[] = teams
  .flatMap((t) =>
    t.players.map((p) => {
      const level = classifyMaxLevel(p.salary, league.constants.salaryCap);
      return level && !p.deadCap ? { ...p, level, teamName: t.name } : null;
    }),
  )
  .filter((p): p is MaxPlayer => p !== null)
  .sort((a, b) => b.salary - a.salary);

export const isPlaceholder = league.season.includes("PLACEHOLDER");
