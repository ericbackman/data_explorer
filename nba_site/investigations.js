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
    slug:        "canada-fiscal",
    title:       "The Canadian Ledger",
    subtitle:    "Every Tax Dollar In, Every Dollar Out",
    description: "All government revenue in Canada beside everything it buys, on one consolidation basis — every tax against every function, from social protection down to street lighting, per person or as a share. Then who actually paid: 31.6M tax filers by income band, for Canada and all 13 provinces and territories, where the 16.6% earning over $100,000 carry 69.9% of the personal income tax — and the same income taxed province by province. A Sankey ties the year together end to end — both sides balancing exactly, because borrowing enters on the left and the capital that spending-by-function excludes is its own band. Includes the reconciliations neither source advertises.",
    date:        "2026-08-29",
    tags:        ["Government", "Reference", "Canada", "Public Finance", "Taxes"],
    accent:      "#AFA238",
    headline:    { stat: "69.9%", label: "Of Income Tax From The Top 16.6%" },
    status:      "live",
  },
  {
    slug:        "registry",
    title:       "The Registry",
    subtitle:    "Where the Big Public Datasets Live",
    description: "A curated, re-verified catalog of the registries, archives, and live feeds people actually pull from — meta-hubs like Hugging Face and AWS Open Data, the ocean & marine record, official statistics, climate, and markets. Filter by domain and by how often the data moves.",
    date:        "2026-06-14",
    tags:        ["Reference", "Registries", "Ocean", "Government", "Climate", "Finance"],
    accent:      "#22d3ee",
    headline:    { stat: "40+", label: "Sources Cataloged" },
    status:      "live",
  },
  {
    slug:        "betting-tracker",
    url:         "https://bets.ericbackman.com",
    title:       "Betting Tracker",
    subtitle:    "Live P&L, Tracked & Charted",
    description: "Every bet logged: balance curve, sportsbook vs casino split, and performance over time. A live tool, not a writeup — data updates with every wager.",
    date:        "2026-06-10",
    tags:        ["Betting", "Live Tool", "Bankroll"],
    accent:      "#41d98d",
    headline:    { stat: "LIVE", label: "Updated Per Bet" },
    status:      "live",
  },
  {
    slug:        "health-curse",
    title:       "The Health Curse",
    subtitle:    "NBA Playoff Injuries & the No-Repeat Era",
    description: "Why no NBA team has repeated as champion since the 2018 Warriors — a data story about catastrophic playoff injuries and the rise of soft-tissue breakdowns.",
    date:        "2026-05-31",
    tags:        ["Injuries", "Playoffs", "League Trends"],
    accent:      "#ff5d5d",
    headline:    { stat: "2018", label: "Last Repeat Champion" },
    status:      "live",
  },
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
