# injuries: the NBA injury-era dataset

Data legs behind the Data Lab investigation at `nba_site/investigations/injury-era/`
(live at datalab.ericbackman.com once the legal gate passes). Four questions,
one package: how many games do players miss by era, why, where on the body, and
what do pace, minutes, the schedule and shoe height look like against that line.

## What is measured, from what

| Series | Years | Source | Module |
|---|---|---|---|
| Games missed by rotation players, per team-game | 1951-52 on (reliable from 1976-77) | nba.com box scores in the canonical NBA database (1.48M player-game rows; host and path from `SPORTS_DB_HOST` and `SPORTS_DB_PATH`) | `missed_games.py` |
| Absence reasons and body part per DNP | 1996-97 on (body part through 2016-17) | `nba_comebacks.db` box-score comments | `box_absences.py` |
| Status and body part per player per game day | 2018-12 on | NBA official injury-report PDFs (`ak-static.cms.nba.com/referee/injury/`) | `injury_reports.py`, `classify_reports.py` |
| Injured-list moves with body part | 2010-2019 (1951-2023 with the Kaggle file) | Third-party scrapes of Pro Sports Transactions (a GitHub repository with no licence; a Kaggle upload labelled CC0 by its uploader) | `pst_mirror.py` |
| Pace, points, 3PA share | 1985-86 on (TOV complete) | canonical NBA database | `pace.py` |
| Minutes distribution, back-to-backs, season span, Finals leaders | 1976-77 on | canonical NBA database | `pace.py` |

`classify.py` is the one body-location and reason classifier every text source
goes through; `data/README.md` documents every column.

## Why games missed is the backbone

The league's own injury database is not public, and every public reason source
changes shape over the years: box scores list the whole roster only through
2002-03 and name the body part only through 2016-17; the official injury report
starts in December 2018; Pro Sports Transactions sits behind a bot challenge and
its terms could not be read. A player who appears on two dates and not in
between missed those games, and that is true in every season since minutes were
recorded. The reason sources then size the mix (injury, illness, rest) and name
the body part for the stretch each one covers.

## Running it

```powershell
$py = "$env:USERPROFILE\Github\data_explorer\.venv\Scripts\python.exe"   # has pandas, requests, pytest
& $py -m injuries.missed_games --pull --from-dir .\injuries\.cache\hb   # ~10 s remote, then local
& $py -m injuries.box_absences --db .\nba_comebacks.db
& $py -m injuries.pst_mirror --fetch                                     # GitHub mirror into injuries/raw/
$env:SPORTS_DB_HOST = "<ssh host>"; $env:SPORTS_DB_PATH = "<path to nba.db>"
& $py injuries\pace.py
& $py injuries\injury_reports.py                                         # 1,910 PDFs on 2026-11-05, cached in injuries/.cache/reports
& $py -m injuries.classify_reports
& $py nba_site\investigations\injury-era\build_data.py
& $py -m pytest injuries -q
```

`injury_reports.py` needs `pdfplumber` (see `requirements.txt` and `THIRD_PARTY.md`). It fetched 1,910 PDFs on 2026-11-05 at two requests per second with a named client string; it is a manual, one-off pull and must never be scheduled.
The Kaggle file `NBA Injury Stats(1951 - 2023).csv` would go into `injuries/raw/`
by hand (Kaggle needs a login) and `pst_mirror.py` would pick it up on the next
run. It is on hold: the uploader's CC0 label waives only the uploader's rights,
and Pro Sports Transactions' own terms could not be read (bot challenge, from
scripts and from a browser, 2026-11-05).

## What is not here

- Live injury feeds are out of scope.
- Anything scraped from prosportstransactions.com itself.
- The row-level files (`injury_reports*.csv`, `box_absences.csv`, `pst_events.csv`)
  and the five fixture PDFs: generated locally, gitignored. The repo carries the
  season aggregates and the per-player games-missed table (legal review 2026-11-05).
- A causal claim. `research/` holds the sourced briefs on the studies, the
  shoe timeline and the cross-league minutes; the page cites them by URL.
