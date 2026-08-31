# The Almanac of the Impossible: a cross-sport rarity study

> **▶ [Open the interactive version](/almanac).** The same findings plotted on one
> shared improbability scale, with tap-to-reveal odds. (Best on a wide screen, but
> works on a phone.)

**Question:** across five different sports, what are the single rarest things that
ever actually happened, and can each one be normalised onto *one* honest scale of
improbability, so a golfer's 58 and a 100-point basketball game can sit on the same
axis?

**Method.** Five parallel mining passes, one per local database in `data_explorer/`.
Each pass queried a **read-only** SQLite DB, quantified rarity with an actual `COUNT`
over the full recorded population (player-games, goalie-games, rounds, seasons, or
holes), and **validated every result against a famous known fact** before it was
allowed in. Rarity is expressed as **"1 in N chances"**, where N is the size of the
recorded population, so a once-ever feat in 2.4M skater-games sits further out than a
shocking upset the betting market still gave a 1-in-10 shot. Two different kinds of
impossible, one axis.

The most important discipline here is what got **thrown out** (see the rejected log
below): three spectacular-looking rows were discarded because they contradicted a
known fact. A record book is only as trustworthy as what it refuses to print.

---

## The 19 verified feats

Rarity = recorded chances per single occurrence in that sport's database.

| # | Sport | Feat | The number | Who / when | Rarity |
|---|-------|------|-----------|-----------|--------|
| 1 | NBA | The Hundred | 100 pts, one game | Wilt Chamberlain · Mar 2 1962 | 1 of 1,481,840 player-games |
| 2 | NBA | Eighty-One | 81 pts, one game | Kobe Bryant · Jan 22 2006 | 2 of 1,481,840 (highest since 1962) |
| 3 | NBA | Thirty Dimes | 30 assists, one game | Scott Skiles · Dec 30 1990 | 1 of 1,481,840 |
| 4 | NBA | Fourteen From Deep | 14 threes in 27 min | Klay Thompson · Oct 29 2018 | 1 of 1,481,840 (3-pt era) |
| 5 | NBA | Seventeen Rejections | 17 blocks, one game | Elmore Smith · Oct 28 1973 | only one since blocks tracked (1973-74) |
| 6 | NFL | Nine Percent | +957 dog wins | NY Jets (0-13) · Dec 20 2020 | 1 of 5,295 games w/ odds · market gave 9.5% |
| 7 | NFL | Six-Touchdown Christmas | 6 rushing TD | Alvin Kamara · Dec 25 2020 | 1 of 476,156 · ties a 1929 record |
| 8 | NFL | Seven Interceptions | 7 INT thrown | Ty Detmer · Sep 23 2001 | 1 of 476,156 (worst of the modern era) |
| 9 | NFL | Three-Twenty-Nine | 329 receiving yds | Calvin Johnson · Oct 27 2013 | 1 of 476,156 |
| 10 | NHL | Ten Points | 10 pts (6G 4A) | Darryl Sittler · Feb 7 1976 | 1 of 2,432,543 skater-games |
| 11 | NHL | Seven Goals | 7 goals, one game | Joe Malone · Jan 31 1920 | 1 of 2,432,543 (set in 1920) |
| 12 | NHL | Eighty-Five Saves, In A Loss | 85 saves on 88 shots | Joonas Korpisalo · Aug 11 2020 (5OT) | 1 of 263,860 goalie-games |
| 13 | NHL | A Defenseman's +10 | +10 plus/minus | Tom Bladon · Dec 11 1977 | 1 of ~2.23M (+/- era) |
| 14 | MLB | Seventy-Three | 73 home runs, one season | Barry Bonds · 2001 | 1 of 128,598 batting seasons |
| 15 | MLB | Fifty-Fifty | 54 HR / 59 SB, one season | Shohei Ohtani · 2024 | 1 of 128,598 (first ever) |
| 16 | MLB | The Year of the Pitcher | 1.12 ERA over 304⅔ IP | Bob Gibson · 1968 | 1 of 7,362 qualified live-ball seasons |
| 17 | PGA | The 58 | 58 (−12), one round | Jim Furyk · 2016 Travelers | 1 of 399,729 rounds |
| 18 | PGA | The Double Eagle | 125 albatrosses | rarest shot in golf · 2005-2026 | 125 of 7,068,295 holes (≈1 per 56,500) |
| 19 | PGA | Thirty-Five Under | −35 to par, 72 holes | Hideki Matsuyama · 2025 Sentry | 1 of 125,976 tournament results |

**The single rarest thing here:** Sittler's 10-point game and Malone's 7-goal game,
each the only one of its kind in **2,432,543** recorded skater-games. The most
*emotionally* shocking (the +957 Jets upset) is, honestly, the least statistically
rare on the shared axis, which is the whole point of putting them on one scale.

---

## Rejected: data that failed verification

- **NBA · corrupt row.** A raw row showed an 83-point night in 2026 requiring **36
  made free throws**. The all-time FT record in a game is 28 (Wilt, in the 100-point
  game); the same player's real career high in this DB is 41. Impossible line →
  excluded, not believed.
- **PGA · broken record.** A stray row implied a **hole-in-one on a par-4**. On
  inspection it was a partial round with the front nine missing and a null round
  total: a data artifact, not a shot. Excluded.
- **MLB · rules artifact.** Raw all-time pitching leaderboards are owned by the
  **1880s** (60-win seasons, 500+ strikeouts): a different sport under different
  rules. Filtered to the live-ball era (≥162 IP, since 1920) so Gibson's 1.12 is
  compared to seasons that were actually comparable.

---

## Provenance

Mined live, read-only, from five local databases:

| DB | Size | Population |
|----|------|-----------|
| `nba/data/nba.db` | 3.6 GB | 1.48M player-games · 18.3M play-by-play rows · since 1946-47 |
| `nfl/data/nfl.db` | 2.3 GB | 476K player-games · odds since 2006 · since 1999 |
| `pga/data/pga.db` | 498 MB | 399K rounds · 7.07M holes · 2005-2026 |
| `nhl/data/nhl.db` | 332 MB | 2.43M skater-games · 264K goalie-games · since 1917-18 |
| `mlb/data/mlb_draft.db` | 35 MB | 128K batting seasons · 57K pitching seasons · since 1871 |

Every number above is traceable to a specific source row (`game_id` / `player_id` /
`event_id`), carried on each card in the interactive version. Nothing was written to
any database; all queries were read-only.
