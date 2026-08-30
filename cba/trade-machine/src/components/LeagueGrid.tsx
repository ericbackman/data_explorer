import type { AcquireResult, Verdict } from "../engine/types";
import { usd } from "../engine/constants";

const VERDICT_LABEL: Record<Verdict, string> = {
  can_acquire: "Can add",
  restricted: "Apron cost",
  hard_blocked: "Blocked",
};

const METHOD_LABEL: Record<AcquireResult["method"], string> = {
  cap_room: "cap room",
  single_match: "1-for-1 match",
  aggregate_match: "aggregate salaries",
  star_swap: "star-for-star swap",
  blocked: "no legal package",
};

/** teamName lookup so cards can show full names. */
export function LeagueGrid({
  results,
  teamNames,
}: {
  results: AcquireResult[];
  teamNames: Record<string, string>;
}) {
  return (
    <div className="grid">
      {results.map((r) => (
        <article key={r.team} className={`card v-${r.verdict}`}>
          <header>
            <span className="abbr">{r.team}</span>
            <span className={`badge v-${r.verdict}`}>{VERDICT_LABEL[r.verdict]}</span>
          </header>
          <p className="team-name">{teamNames[r.team] ?? r.team}</p>
          <p className="method">{METHOD_LABEL[r.method]}</p>
          <p className="reason">{r.reasons[0]}</p>
          {r.outgoingExample.length > 0 && (
            <p className="package">
              <span className="package-label">example out ({usd(r.outgoingSalary)}):</span>{" "}
              {r.outgoingExample.join(", ")}
            </p>
          )}
        </article>
      ))}
    </div>
  );
}
