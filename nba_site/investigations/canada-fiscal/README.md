# The Canadian Ledger

Every dollar collected by every level of government in Canada beside every dollar it
buys — one year at a time, on a single consolidation basis.

**Live:** `investigations/canada-fiscal/` on the Data Lab hub.

```powershell
python build_data.py            # rebuild data.js from the cached CSVs
python build_data.py --refresh  # re-download the three source tables first
python -m http.server 8777      # preview from nba_site/
```

## Where the numbers come from

Three Statistics Canada tables, pulled through the Web Data Service (no API key):

| Table | What it gives | Coverage |
|---|---|---|
| `36-10-0450` | Revenue and expenditure by level of government | 2007–2024, annual |
| `10-10-0005` | Spending by function (CCOFOG) | 2008–2024, annual |
| `17-10-0009` | Population estimates | 1946–2026, quarterly |

The overlap, 2008–2024, is what the page renders. Raw CSVs cache to `.cache/`
(21 MB, gitignored); `data.js` is the 71 KB extract that actually ships.

## The decisions that shaped this

**The ledger is national-only, and that is forced by the data.** CCOFOG publishes
"Consolidated Canadian general government" for Canada alone — every province carries
only the provincial-territorial-and-local component. The revenue table, meanwhile,
has no consolidated provincial+local level, and summing "Provincial and territorial"
with "Local" would double-count the transfers running between them. So exactly one
pairing of these two tables sits on a single consolidation basis, and it is Canada-wide.
Provinces therefore get the spending half only, which is the cut StatCan documents as
cross-province comparable.

**The two columns are not meant to balance, and the page says why.** Spending-by-function
is ~84% of total expenditure because CCOFOG excludes capital acquisition and consumption
of fixed capital. Rather than hide that, the bridge section shows the shortfall against
both excluded lines, which the revenue table publishes itself.

## Traps, and what the code does about them

**Estimate labels are not unique — join on the member id.** Table 36-10-0450 carries
`Capital transfers` and `From households` twice each, once under revenue and once under
expenditure. Joining the CSV on the label pairs a revenue line with an expenditure value:
the first build of this page reported revenue capital transfers as **$47,421M** when the
true figure is **$459M**, and it looked entirely plausible. `series_matrix()` now keys on
the member id parsed out of `COORDINATE`, and `validate()` asserts the revenue categories
sum to the published revenue total in every year — the check that would have caught it.

**Metadata labels and CSV labels differ.** Cube metadata gives `Defence`; the CSV gives
`Defence [702]`. Only display names are stripped; the join never depends on them.

**Consolidation means you cannot add levels together.** Transfers between governments are
already netted out. `Current transfers from general governments` therefore comes back
empty at the national level — the page drops fully-empty categories rather than rendering
a row that reads "—".

**A 2023 reclassification breaks one series.** Federal Indigenous programs moved into
*Housing and community amenities, n.e.c.* Year-over-year comparisons across 2023 for that
function are measuring an accounting change.

**CPP and QPP sit outside** the consolidated general government in CCOFOG, but appear as
their own level in the revenue table. The page uses the consolidated aggregate on both
sides, so they are consistently excluded.

## Validation

`build_data.py` refuses to write `data.js` unless every check passes:

- revenue categories reconcile to the published revenue total, all 17 years, within 0.5%
- function totals fall between 75% and 100% of total expenditure
- national revenue, expenditure and population land in sane magnitude ranges
- every province carries spending data for the latest year
- any dimension filter that matches zero rows raises rather than yielding an empty chart

Latest build: 2024 revenue $1,312B, expenditure $1,356B, functions $1,137B (84%),
population 41.3M, $31,808 revenue per person.

## Conventions

Vanilla JS, no build step, runs from `file://`. DOM is built with `createElement` +
`textContent`, never `innerHTML` with data. Colour comes from `tokens.css`, vendored from
`backman-design` — themes Shield (dark, default) and Window Wall (light), toggled in the
header. Contrast was measured in both themes; secondary text stays off `--bd-panel`
surfaces, per the gate gap recorded in `BRICKS.md`.

## Not done yet

- **The Sankey.** Tax source → level of government → function is the better picture, but
  the two tables share no classification, so it needs a deliberate bridge rather than a join.
- **Who pays.** CRA T1 statistics add the distributional half (by income band, by province)
  and lag ~2 years behind the spending data.
- **Federal-only functions.** Published separately on a non-consolidated basis, not derivable
  by subtracting the provincial component from the national one.
