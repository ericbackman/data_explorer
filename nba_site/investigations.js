// ─────────────────────────────────────────────────────────────────────────────
// INVESTIGATIONS MANIFEST
//
// This is the single registration point for the hub. To add a new investigation:
//   1. Create a folder under investigations/<slug>/ with its own index.html
//   2. Add one object to the array below
//   3. Done — the hub renders the card automatically
//
// Field reference:
//   slug        folder name under investigations/ (also the URL path)
//   title       headline shown on the card
//   subtitle    short kicker under the title
//   description 1–2 sentence summary of the argument/finding
//   date        ISO date (YYYY-MM-DD) — used for sorting (newest first)
//   tags        array of category strings — drives the filter bar
//   accent      hex color for the card's left border / tag (per-investigation theme)
//   headline    optional { stat, label } shown as the card's big number
//   status      "live" | "draft" — draft cards render dimmed with a badge
// ─────────────────────────────────────────────────────────────────────────────

const INVESTIGATIONS = [
  {
    slug:        "mitchell-top10",
    title:       "The Case for Donovan Mitchell",
    subtitle:    "Top 10, No Debate",
    description: "A data-driven argument that Mitchell is a top-10 NBA player — built on career playoff production (27.8 PPG across 81 games) and a head-to-head teardown of the 7–25 ranking tier, including a direct rebuttal to the Cade Cunningham series loss.",
    date:        "2026-06-01",
    tags:        ["Player Profile", "Playoffs", "Advanced Stats", "Debate Settler"],
    accent:      "#f0b429",
    headline:    { stat: "27.8", label: "Career Playoff PPG" },
    status:      "live",
  },

  // ↓ Add new investigations here. Example scaffold:
  // {
  //   slug:        "clutch-kings-2025",
  //   title:       "Clutch Kings",
  //   subtitle:    "Who Actually Hits in the Last 5 Minutes",
  //   description: "Ranking the league's true clutch scorers by efficiency in the final 5 minutes of games within 5 points.",
  //   date:        "2026-06-15",
  //   tags:        ["Clutch", "League-Wide", "Advanced Stats"],
  //   accent:      "#4f8ff7",
  //   headline:    { stat: "TBD", label: "Clutch FG%" },
  //   status:      "draft",
  // },
];

// Expose for the hub (works as a plain <script> include — no modules needed)
if (typeof window !== "undefined") window.INVESTIGATIONS = INVESTIGATIONS;
