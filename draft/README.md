# draft — unified cross-sport draft database

Every NBA, NFL, NHL and MLB draft pick in **one** table (`drafts.db` → `draft_picks`),
because a draft pick is the same shape in every league: *(year, round, overall
pick, team, player, where-they-came-from)*. One `sport` column discriminates, so
cross-sport questions are a single query and Jupyter exploration is one
`read_sql`.

```bash
python -m draft.build                          # all sports, all history
python -m draft.build --sports nba,nfl         # a subset
python -m draft.build --sports mlb --years 2000-2025
python -m draft.build --dry-run                # fetch + validate, write nothing
python schema_doc.py                           # refresh SCHEMA.md after building
```

## Sources (all free)

| Sport | Source | Coverage | Player join key |
|-------|--------|----------|-----------------|
| NBA | `nba_api` `DraftHistory` | 1947+ | `native_player_id` = `PERSON_ID` → `nba.db` `players` |
| NFL | nflverse `draft_picks` release CSV | 1980+ | `native_player_id` = `gsis_id` → `nfl.db` `player_game` |
| NHL | `records.nhl.com` draft records | 1963+ | `native_player_id` = `playerId` |
| MLB | `statsapi.mlb.com` `/draft/{year}` | 1965+ | `native_player_id` = MLBAM `person.id` |

## Design

- **Raw facts, derived analysis.** We store what each league's record says; busts,
  steals and positional trends are query-time, not baked in.
- **Faithful team identity.** `team_abbr` is the code *as drafted* (+ `team_name`
  for provenance). Franchise rollups (Sonics → Thunder) are an opt-in helper in
  [`teams.py`](teams.py) — never a lossy mutation at load, because codes are
  era-ambiguous (NFL `STL` was the Rams *and*, earlier, the Cardinals).
- **Idempotent + fail-loud.** Every load is `INSERT OR REPLACE` on
  `(sport, draft_year, draft_type, overall_pick)`; a duplicate natural key raises
  instead of silently overwriting (see `db.assert_unique_keys`).
- **Joins back to careers.** Keep the native id and you can `ATTACH` `nba.db` /
  `nfl.db` (or pandas-merge) to ask what a draft pick went on to do.

```sql
-- NBA #1 overall picks and the franchise that took them
SELECT draft_year, player_name, team_abbr
FROM draft_picks WHERE sport='NBA' AND overall_pick=1 ORDER BY draft_year DESC;
```

```python
# Jupyter: every draft, one DataFrame
import sqlite3, pandas as pd
picks = pd.read_sql("SELECT * FROM draft_picks", sqlite3.connect("drafts.db"))
picks.groupby("sport").draft_year.agg(["min", "max", "count"])
```

## Adding a sport

Drop a `sources/<sport>.py` exposing `fetch(years=None) -> list[dict]` (rows keyed
to `db.COLUMNS`, `SPORT` set), register it in `build.SOURCES`. The schema, loader
and dashboard wiring are already generic.
