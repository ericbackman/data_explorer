# Neon: Postgres serving layer, with a database per pull request

Puts a compact NBA **serving** slice on [Neon](https://neon.com) serverless
Postgres, and gives every pull request its own copy-on-write database.

Sibling of [`../bigquery`](../bigquery). The contrast is the point:

| | BigQuery | Neon |
|---|---|---|
| Grain | 18.3M play-by-play events | 37k player-seasons |
| Shape | denormalised, partitioned, columnar | normalised, indexed, relational |
| Question | "what happened across a decade?" | "what did this player do that season?" |
| Cost model | bytes scanned | compute-hours + storage |

Same source database, two warehouses, because they answer different questions.
Neither replaces the local SQLite/DuckDB path, which stays the default.

---

## ⚠ Setup Eric has to do (once)

1. **Sign up** — <https://console.neon.tech/signup>. No card.
2. **Create a project** (region: pick the closest; the data is tiny).
3. **Copy the connection string.** Connect → connection string. It looks like
   `postgresql://USER:PASSWORD@HOST/neondb?sslmode=require`.
4. **Save it to `%USERPROFILE%\.neon\database-url`.** One line, the URL alone,
   no surrounding quotes and no `psql ` prefix. Same convention as
   `~\.cloudflare\token`, `~\.aiven\token`, `~\.gcp\service-account.json`.
   ⚠ "Save as type: All Files" so it does not become `database-url.txt`.
5. **API key.** Account settings → API keys → Create. Then wire CI:

   ```powershell
   gh secret set NEON_API_KEY --repo ericbackman/data_explorer          # paste the key
   gh variable set NEON_PROJECT_ID --repo ericbackman/data_explorer     # paste the project id
   ```

The connection string embeds a password, so nothing here ever echoes it: it is
only ever assigned into `$env:DATABASE_URL` for a child process.

---

## Running it

```powershell
. C:\Users\ericb\Github\.claude\ops\neon-url.ps1

cd C:\Users\ericb\Github\data_explorer\neon
python migrate.py --status      # what is applied vs pending
python migrate.py               # apply
python seed.py --counts-only    # what would load, touching nothing
python seed.py                  # truncate + COPY (~37k rows)
python -m pytest test_schema.py -v
```

---

## Branch per pull request

[`.github/workflows/neon-pr.yml`](../.github/workflows/neon-pr.yml). On any PR
touching `neon/`:

1. **create** a Neon branch `pr-<number>`: a copy-on-write clone of production,
   with production's data, in seconds;
2. **migrate** it;
3. **test** against it: real Postgres, real constraints, real planner;
4. **comment** the result on the PR (updated in place, not one per push);
5. **delete** the branch when the PR closes, merged or not.

**Why not a shared staging database.** Two PRs cannot corrupt each other's
schema if they are not sharing one. A migration gets proven against
production-shaped *data* rather than an empty schema, which is where migrations
actually fail. And teardown is total, so no drift accumulates.

**Two free-plan limits shape the workflow, and both bite quietly:**

- **10 branches per project.** The cleanup job is not tidiness: it is what stops
  the 11th open PR from failing outright.
- **0.5 GB storage per project, shared across every branch**, and **100
  CU-hours/month**. Writes *fail* past the storage cap. Hence the serving-slice
  design and the `paths:` filter, so an unrelated PR does not spin up a database.

---

## Schema

| Relation | Rows | Notes |
|---|---:|---|
| `teams` | 45 | dimension |
| `players` | 5,103 | dimension |
| `player_season` | ~37,472 | PK `(player_id, season, season_type)` |
| `player_season_rates` | view | per-game rates derived from the totals |

**Rates are a view, not columns.** Stored ppg/rpg/apg could disagree with the
totals the first time a season is re-seeded; a view cannot drift from its own
inputs. The `games > 0` CHECK on the base table is what makes the division safe.

**`team_id` is nullable on purpose.** `teams` holds 45 modern franchises while
the data reaches back to 1946, so some historical team ids have nothing to point
at. `seed.py` sets those NULL and **counts** them rather than dropping the row:
losing a season because a franchise folded in 1949 would be a silent data bug.

**`idx_player_season_team` is partial** (`WHERE team_id IS NOT NULL`): rows
without a team are never the answer to "who did this team roster?", so they stay
out of the index.

---

## Migrations

Plain `NNN_description.sql` applied in numeric order, tracked in
`schema_migrations`. No framework: this same script runs in CI on a throwaway
branch, so it stays readable and dependency-free.

Each migration runs in **one transaction together with its bookkeeping row**, so
a failure leaves nothing behind: never a half-applied schema recorded as
complete. Postgres has transactional DDL, so that is actually true here in a way
it would not be on MySQL.

`migrate.py` also **checksums** each applied file and warns on drift, so a
migration edited after it was applied is reported rather than silently ignored.

---

## Verified before any account existed

The migrations, constraints and view were proven against **real Postgres 17** in
a throwaway container on homebase, not just written:

- both migrations apply cleanly; all 4 relations and 5 indexes created;
- the `games > 0` CHECK rejects a zero-game row;
- the FK rejects an unknown `player_id`;
- the view math is exact — 2100 pts / 82 games → `ppg = 25.6`;
- a NULL `team_id` is accepted.

What remains unverified is Neon-specific: the branching action and the live
connection. Those need the account.
