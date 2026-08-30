import { useMemo, useState } from "react";
import { league, maxPlayers, isPlaceholder } from "./data/league";
import { computeTradeUniverse } from "./engine/tradeUniverse";
import { usd } from "./engine/constants";
import { LeagueGrid } from "./components/LeagueGrid";

const teamNames: Record<string, string> = Object.fromEntries(
  league.teams.map((t) => [t.abbr, t.name]),
);

export default function App() {
  const [selected, setSelected] = useState(maxPlayers[0]?.name ?? "");
  const player = maxPlayers.find((p) => p.name === selected) ?? maxPlayers[0];

  const universe = useMemo(
    () => (player ? computeTradeUniverse(player, league) : null),
    [player],
  );

  if (!player || !universe) {
    return <div className="empty">No max/supermax players found in the dataset.</div>;
  }

  const c = league.constants;
  const supermaxLine = c.salaryCap * 0.35;

  return (
    <div className="app">
      <header className="masthead">
        <h1>The Trade Universe</h1>
        <p className="tagline">
          Which of the other 29 teams can <em>legally</em> trade for every max &amp; supermax
          player — and why not — under the 2023 CBA's apron system.
        </p>
        <p className="dataline">
          {league.season} · salaries as of {league.as_of} · cap {usd(c.salaryCap)} · tax{" "}
          {usd(c.taxLevel)} · 1st apron {usd(c.firstApron)} · 2nd apron {usd(c.secondApron)}
        </p>
        {isPlaceholder && (
          <p className="warn">
            ⚠ Showing placeholder data — real league salaries are still loading.
          </p>
        )}
      </header>

      <section className="picker">
        <label htmlFor="player">Player</label>
        <select id="player" value={selected} onChange={(e) => setSelected(e.target.value)}>
          <optgroup label={`Supermax (≥ ~${usd(supermaxLine)})`}>
            {maxPlayers
              .filter((p) => p.level === "supermax")
              .map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} — {p.team} · {usd(p.salary)}
                </option>
              ))}
          </optgroup>
          <optgroup label="Max">
            {maxPlayers
              .filter((p) => p.level === "max")
              .map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} — {p.team} · {usd(p.salary)}
                </option>
              ))}
          </optgroup>
        </select>
      </section>

      <section className="subject">
        <div className="subject-main">
          <span className={`level-badge ${player.level}`}>{player.level}</span>
          <h2>{player.name}</h2>
          <span className="subject-team">{player.teamName}</span>
        </div>
        <div className="subject-meta">
          <span className="salary">{usd(player.salary)}</span>
          <span className="salary-share">
            {((player.salary / c.salaryCap) * 100).toFixed(0)}% of the cap
          </span>
          {player.noTrade && <span className="flag">no-trade clause — can veto any deal</span>}
        </div>
      </section>

      <section className="summary">
        <div className="stat v-can_acquire">
          <span className="n">{universe.counts.can_acquire}</span>
          <span className="l">can add him under the apron</span>
        </div>
        <div className="stat v-restricted">
          <span className="n">{universe.counts.restricted}</span>
          <span className="l">only by crossing an apron / swap</span>
        </div>
        <div className="stat v-hard_blocked">
          <span className="n">{universe.counts.hard_blocked}</span>
          <span className="l">can't trade for him</span>
        </div>
      </section>

      <LeagueGrid results={universe.results} teamNames={teamNames} />

      <footer className="foot">
        <p>
          <strong>How to read this.</strong> <span className="dot can_acquire" />{" "}
          <b>Can add</b> — has cap room, or can match his salary and stay <em>under the first
          apron</em>. <span className="dot restricted" /> <b>Apron cost</b> — the team is
          <em> over an apron</em> (already hard-capped, or this trade would push it past the first
          apron), so it can only reshape — losing the aggregation / mid-level tools, and over the
          second apron it can't add net salary at all.{" "}
          <span className="dot hard_blocked" /> <b>Blocked</b> — no legal matching package at all.
          {player.noTrade && " This player also has a no-trade clause and can veto any destination."}
        </p>
        <p className="fine">
          A simplified model of the 2023 CBA's trade rules (Art VII §2(e) apron table, §6(j)
          matching, §8 procedure). Team Salary is approximated as the sum of guaranteed salaries;
          cap holds, dead money, exact Apron Team Salary add-backs, and most timing gates are not
          modeled. Matching packages are examples, not optimized, and capped at 4 pieces. Verify
          edge cases near a threshold against a real cap sheet. Built on the{" "}
          <code>nba-cba</code> corpus project.
        </p>
      </footer>
    </div>
  );
}
