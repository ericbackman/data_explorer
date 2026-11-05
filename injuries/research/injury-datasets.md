## Question
Best openly downloadable historical NBA injury datasets (player, date, team, injury/body part, games or days missed), as far back as possible, for a public-site investigation; plus what the source sites allow. As-of 2026-11-05. Excluded: ESPN current feed (snapshot, off limits). No Kaggle login, so Kaggle items are graded by metadata only.

## Ranking (top of brief)
1. **loganlauton "NBA Injury Stats (1951 - 2023)"**: PST IL moves 1951 to 2023-04, CC0 on Kaggle. Use as the BACKBONE: longest span, free licence, ~2.5 MB single CSV, with a Notes column carrying the injury text. Needs a Kaggle login to download (Eric fetches it). Caveat: PST content is the underlying source (see terms gap).
2. **elap733/NBA-Injuries-Analysis raw CSVs** (GitHub, no login, raw URL): PST "missed games" and "IL" scrapes for 2010 to 2019. Use as the no-login cross-check and the only source here with a missed-games event type. No licence file shown.
3. **ghopkins "NBA Injuries from 2010-2020"** (Kaggle, CC0): subset of #1's span; use only to validate.
4. **jacquesoberweis "2016-2025 NBA injury data"** (Kaggle, licence Unknown): extends to 2025-01-12 but licence unknown; lead only.
5. **NBA official injury report PDFs** (primary): status plus reason text per player per game, but only machine-usable from 2021-22 per a third-party package; could not fetch PDFs myself.
Games or days missed is NOT a column in any of these: it must be derived (IL date to return date, or counting team games). Recommendation: backbone = #1; recent seasons and game-level status = #5 via the MIT `nbainjuries` package or Stat Surge CSVs (2021-10 to 2024-06).

## Findings
| # | claim | source | date | grade |
|---|---|---|---|---|
| 1 | Kaggle loganlauton/nba-injury-stats-1951-2023: title "NBA Injury Stats (1951 - 2023)", licence "CC0: Public Domain", lastUpdated 2023-04-20, totalBytes 2,541,560, one file "NBA Injury Stats(1951 - 2023).csv"; description: IL moves since 1951 scraped from PST | [Kaggle API view](https://www.kaggle.com/api/v1/datasets/view/loganlauton/nba-injury-stats-1951-2023) and [file list](https://www.kaggle.com/api/v1/datasets/list/loganlauton/nba-injury-stats-1951-2023) (opened anonymously 2026-11-05) | 2023-04-20 | PRIMARY |
| 2 | Its scraper requests PST SearchResults.php with ILChkBx=yes, 25 rows per page, 2.38 s sleep, one call `single(1507)`; columns Date, Team, Acquired, Relinquished, Notes; writes CSV with index | [logan-lauton/nba_webscrape notebook (raw)](https://raw.githubusercontent.com/logan-lauton/nba_webscrape/main/NBA%20Player%20Injury%20Data%20Web%20Scrape.ipynb) | undated | PRIMARY |
| 3 | Row count of #1 not stated anywhere I opened. Inference only: 1507 pages x 25 = at most 37,675 rows (arithmetic from row 2, not confirmed) | derived from row 2 | n/a | UNVERIFIED |
| 4 | Kaggle ghopkins/nba-injuries-2010-2018: title "NBA Injuries from 2010-2020", CC0, lastUpdated 2020-10-13, 1,598,255 bytes; every injury 2010-11 to 2019-20 scraped from PST | [Kaggle API view](https://www.kaggle.com/api/v1/datasets/view/ghopkins/nba-injuries-2010-2018) | 2020-10-13 | PRIMARY |
| 5 | A Baselight mirror of ghopkins listed about 27,000 rows x 5 columns (date, team, acquired, ...). Baselight page now shows a shutdown notice, so the mirror is gone | search snippet (not opened); [Baselight notice](https://baselight.ai/u/kaggle/dataset/ghopkins_nba_injuries_2010_2018) | 2026-07-07 (notice) | UNVERIFIED for row count |
| 6 | Kaggle jacquesoberweis/2016-2025-nba-injury-data: licence "Unknown", lastUpdated 2025-01-25, 1,064,927 bytes, no description | [Kaggle API view](https://www.kaggle.com/api/v1/datasets/view/jacquesoberweis/2016-2025-nba-injury-data) | 2025-01-25 | PRIMARY |
| 7 | That dataset's columns date/team/player/note and range 2016-10-25 to 2025-01-12 come from a downstream repo README; the repo says it only captures IL placements, not per-game missed notes | [enriquemaldo/nba-injury-survival](https://github.com/enriquemaldo/nba-injury-survival) | undated | SECONDARY |
| 8 | GitHub elap733/NBA-Injuries-Analysis has data/01_raw with prosportstransactions_scrape_IRL_2010_2019.csv, prosportstransactions_scrape_missedgames_2010_2019.csv, all_teams_schedule_2010_2020.csv, player_stats_1994_2019.csv | [folder listing](https://github.com/elap733/NBA-Injuries-Analysis/tree/master/data/01_raw) | undated | PRIMARY |
| 9 | README states >14,000 inactive-list events and >11,000 missed-game events (2010 to 2019); no licence; no PST terms statement | [README](https://github.com/elap733/NBA-Injuries-Analysis/blob/master/README.md) | undated | PRIMARY |
| 10 | Raw missed-games CSV loads with no login. Header: index, Date, Team, Acquired, Relinquished, Notes. First row 2010-08-03 Clippers, Craig Smith, "arthroscopic surgery on right knee (out indefinitely)". Notes carry body part. File text is 757,535 characters; I read only the first 100,000 | [raw CSV](https://raw.githubusercontent.com/elap733/NBA-Injuries-Analysis/master/data/01_raw/prosportstransactions_scrape_missedgames_2010_2019.csv) | undated | PRIMARY |
| 11 | PST robots.txt and home page returned HTTP 403 to WebFetch; no PST terms text read | [robots.txt](https://www.prosportstransactions.com/robots.txt) (attempted 2026-11-05) | n/a | n/a |
| 12 | A third-party PST client's disclaimer says use of the information is "subject to all rights reserved" by PST; the same README says PST "is protected by a Cloudflare challenge" | [rsforbes/pro_sports_transactions](https://github.com/rsforbes/pro_sports_transactions) | undated | SECONDARY (not PST's own words) |
| 13 | mrees002/nba-injury-database keeps PST data only for "historical comparison" and says do not schedule the PST client until the access question is resolved with a permitted path; its production source is NBA PDFs found via Internet Archive CDX | [repo](https://github.com/mrees002/nba-injury-database) | undated | SECONDARY |
| 14 | NBA 2025-26 page lists per-15-minute PDFs at ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM.pdf (example Injury-Report_2026-11-05_12_00AM.pdf); page lists only the current day, no archive text | [official.nba.com 2025-26 page](https://official.nba.com/nba-injury-report-2025-26-season/) | 2026-11-05 | PRIMARY |
| 15 | The 2022-23 and 2020-21 season pages on official.nba.com showed only the 2026-11-05 list when fetched (the fetch returned the current page); no earlier-season link lists found | [2022-23 URL](https://official.nba.com/nba-injury-report-2022-23-season/), [2020-21 URL](https://official.nba.com/nba-injury-report-2020-21-season) | 2026-11-05 | PRIMARY (negative) |
| 16 | Search index lists PDFs under an older pattern without minutes, e.g. Injury-Report_2018-12-27_05PM.pdf, Injury-Report_2019-02-07_05PM.pdf (search titles only; I did not open them) | [example](https://ak-static.cms.nba.com/referee/injury/Injury-Report_2018-12-27_05PM.pdf) | 2018-12-27 | UNVERIFIED |
| 17 | `nbainjuries` (MIT, v1.1.1 released 2026-02-10): "Historical data in this format have been available since the 2021-2022" season; no preseason; gaps at all-star break; asks users to respect NBA Terms of Use. Columns: Game Date, Game Time, Matchup, Team, Player Name, Current Status, Reason | [PyPI](https://pypi.org/project/nbainjuries/), [GitHub](https://github.com/mxufc29/nbainjuries/) | 2026-02-10 | PRIMARY for the package, SECONDARY for NBA coverage |
| 18 | Stat Surge CSVs of parsed NBA reports: all reports Oct 2021 to June 2024, plus per-season regular and playoff files for 2021-22 to 2023-24 (bit.ly links); post 2024-11-16, update note Dec 2025 says no longer maintained; no licence or column list on page | [Stat Surge](https://statsurge.substack.com/p/downloadable-nba-injury-datasets) | 2024-11-16 | SECONDARY |
| 19 | Stat Surge says it parsed three seasons of reports into >35,000 injury designations; reports are submitted by 5 pm the day before, full report posted 2 pm gameday | [Stat Surge post](https://statsurge.substack.com/p/creating-an-nba-injury-database) | 2024-11-17 | SECONDARY |
| 20 | Box-score reasons: an ESPN box score shows "DNP" plus a reason such as a sprained left ankle; Basketball-Reference 2016-17 game logs show "Inactive" / "Did Not Play" without a reason in the snippet | [ESPN box](https://africa.espn.com/nba/boxscore/_/gameId/401365927), [BBRef log](https://aws.basketball-reference.com/players/v/varejan01/gamelog-advanced/2017) | undated | SECONDARY (snippets only, not opened) |

## Synthesis
- The longest open injury history is the PST IL-move file: 1951 to 2023-04-20, CC0 on Kaggle, 2.54 MB, columns Date/Team/Acquired/Relinquished/Notes (rows 1, 2). Row count is unconfirmed (row 3).
- A no-login GitHub copy exists only for 2010 to 2019: IL events (>14,000) and missed-game events (>11,000), as raw CSVs with a Notes field carrying body part (rows 8 to 10). The Kaggle 2010-2020 set (CC0, 2020-10-13) overlaps it (row 4).
- None has a games-missed column; it has to be derived from IL start and return rows or from the schedule. elap733 did this ("games missed per event", row 9).
- The jacquesoberweis set reaches 2025-01-12 but its licence is "Unknown" and it holds IL placements only (rows 6, 7).
- Official NBA PDFs are fetchable by URL pattern on the current page (row 14), but I could not confirm any archive page or the first season. Structured parsing is documented from 2021-22 (row 17); older PDFs may exist at a different filename pattern (row 16, unverified).
- PST's own terms were not readable (row 11). Two third parties treat reuse as needing care (rows 12, 13); the CC0 tag on Kaggle is the uploader's label, not PST's.
- Body-part text per absence: PST Notes (rows 10, 1) and NBA report Reason (row 17). The box-score "DND" cutoff is not confirmed (see gaps).

## Conflicts and gaps
- Licence: Kaggle labels the PST scrapes CC0, but the uploader does not own PST's compilation; PST's terms are unread. I would trust PST's own terms over the Kaggle tag. A definitive answer needs PST's terms page text (open in a browser) or an email to the operator. Facts like dates and injury notes are likely thin on copyright, but the compilation and any ToS are separate questions; this is not legal advice.
- Date span: 1951 start is the dataset title; I did not see the first rows. Early decades are probably sparse and inconsistent in note detail. Check the CSV before plotting trends.
- Row counts: loganlauton unknown; ghopkins about 27,105 per a mirror snippet (the mirror is now closed).
- NBA PDF start: package says 2021-22 for "this format"; the search index shows 2018-12 and 2019-02 files. Needs a successful fetch of one.
- Box-score cutoff (DND comments through 2016-17, "Injury/Illness" after): not confirmed by any source I opened. Treat as unverified; do not publish it.
- Stat Surge page says no longer maintained (Dec 2025), so there is no data after 2024-06 from that source.

## Not found or could not verify
- PST robots.txt: WebFetch got HTTP 403 twice (direct URL; Wayback blocked by the tool).
- PST terms/about page: home page and about.php returned HTTP 403; two searches found no terms text.
- NBA PDFs via HTTP: ak-static URLs for 2019-12-15, 2024-01-15, 2025-01-15 (fetch timed out at 60 s), 2018-12-27 and 2019-02-07 (timed out twice in total). Cannot say whether plain HTTP works from here; retry with curl from a normal client.
- Wayback CDX of the PDF path: blocked by the fetch tool.
- Kaggle columns and row count for loganlauton: API gave only size and file name; the HTML page gave title only. Eric must open the Data tab.
- GitHub repo search API returned 0 results twice; used web search instead. No GitHub repo with the 1951-2023 PST CSV found. data.world: not searched successfully.
- elap733 raw CSV tail and row total: only the first 100,000 of 757,535 characters read.
- Licence file of elap733: none visible on the page.
- Baselight (ghopkins mirror): shut down 2026-07-07 per its own notice.
