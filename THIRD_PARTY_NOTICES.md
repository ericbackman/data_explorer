# Third-party notices

The MIT licence in [`LICENSE`](LICENSE) covers this repo's code. It does not cover the material
below, which keeps whatever terms its owner set. No database is committed: the code downloads
data when you run it, and using a source is subject to that source's own terms.

## Committed files that are not MIT

| Path | What it is | Terms |
|---|---|---|
| `cba/semantic/*.toc.*` | Article and section headings of the NBA collective bargaining agreements, with line and page numbers | The agreements belong to the NBA and the NBPA. The full text is not in this repo |
| `nba_site/investigations/canada-fiscal/data.js` | Tables derived from Statistics Canada 36-10-0450, 10-10-0005 and 17-10-0009, and Canada Revenue Agency statistics | [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/reference/licence); [Open Government Licence - Canada](https://open.canada.ca/en/open-government-licence-canada). Sources are listed on the page. Adapted; no endorsement by either body |
| `pga/seeds/major_history_seed.json` | Facts about major championships, each row with its Wikipedia `source_url` | Facts only. Wikipedia text is [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) and none is copied here |
| `reports/playoff_health_2019_2025.*`, `nba_site/investigations/mitchell-top10/data.js` | Figures computed from NBA.com statistics via `nba_api` | Attribution to NBA.com; not relicensed. See [NBA.com terms](https://www.nba.com/termsofuse) |
| `osrs/` test fixtures | Sample Old School RuneScape Hiscores responses | Unofficial; not affiliated with or endorsed by Jagex |

## Data the code downloads

These are not committed. They are listed so you can check each source before running a scraper.

| Used by | Source | Licence or terms it states |
|---|---|---|
| `nfl/`, `draft/sources/nfl.py` | [nflverse](https://github.com/nflverse/nflverse-data) | CC BY 4.0 |
| `mlb/chadwick.py` | [Chadwick Bureau register](https://github.com/chadwickbureau/register), [Lahman database](https://sabr.org/lahman-database/) via SABR | ODC-BY for the register; no licence stated for Lahman |
| `nba/` | NBA.com via [`nba_api`](https://github.com/swar/nba_api) | [NBA.com terms](https://www.nba.com/termsofuse) |
| `nhl/`, `draft/sources/nhl.py` | NHL hosts | [NHL terms](https://www.nhl.com/info/terms-of-service) |
| `mlb/draft_api.py`, `draft/sources/mlb.py` | statsapi.mlb.com | [MLB copyright notice](https://gdx.mlb.com/components/copyright.txt) |
| `sumo/` | [sumo-api.com](https://sumo-api.com) | Asks for responsible use |
| `nba/hof_scrape.py`, `pga/tier2*.py` | Wikipedia | CC BY-SA 4.0 for text |
| `nba_site/investigations/canada-fiscal/build_data.py` | Statistics Canada, Canada Revenue Agency | As above |

## Names and marks

League, team, tour, event and game names belong to their owners. They are used here only to say
what the data describes.
