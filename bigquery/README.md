# BigQuery — NBA on Google's warehouse

Puts the local NBA SQLite database on **BigQuery**, on the always-free tier
(1 TiB of query processing + 10 GiB storage per month, no expiry).

This is not a replacement for the local DuckDB/SQLite path, which stays the
default for everyday questions. It exists for the things a laptop warehouse
cannot teach: **partition pruning, clustering, bytes-scanned billing, and
slot-based execution over 18.3M rows.**

---

## ⚠ Setup Eric has to do (once)

Everything else here is automated, but the account steps cannot be — creating a
cloud account and issuing credentials is his alone.

1. **Create or pick a Google Cloud project** — <https://console.cloud.google.com/projectcreate>.
   A billing account must be attached even to use the free tier; the free
   allowances apply automatically and are not a trial.
2. **Enable the BigQuery API** — <https://console.cloud.google.com/apis/library/bigquery.googleapis.com>.
3. **Create a service account** — IAM & Admin → Service Accounts → Create.
   Grant it **BigQuery Data Editor** + **BigQuery Job User**. Add
   **BigQuery Resource Viewer** too if `bq_query.py --usage` should work (it
   reads `INFORMATION_SCHEMA`).
4. **Download a JSON key** — the service account → Keys → Add key → JSON.
5. **Save it to `%USERPROFILE%\.gcp\service-account.json`** — the same
   convention as `~\.cloudflare\token` and `~\.aiven\token`.
   ⚠ Use "Save as type: All Files" so it does not become `service-account.json.txt`
   (that is exactly how the Aiven token landed as `token.txt`).
6. **Set a budget alert** — <https://console.cloud.google.com/billing/budgets>.
   Belt and braces: the scripts cap bytes billed, but only a billing budget
   catches spend from the console or `bq` CLI.

Nothing here reads the key's contents — the Google libraries take a file path via
`GOOGLE_APPLICATION_CREDENTIALS`, so the secret never passes through PowerShell.

---

## Running it

```powershell
. C:\Users\ericb\Github\.claude\ops\gcp-credentials.ps1   # sets the env vars, fail-loud

cd C:\Users\ericb\Github\data_explorer\bigquery
python export_to_parquet.py            # SQLite -> Parquet  (~250 MB, few minutes)
python load_to_bigquery.py --dry-run   # show the plan, touch nothing
python load_to_bigquery.py             # create dataset + load
python bq_query.py --file examples/season_scoring.sql
python bq_query.py --usage             # month-to-date vs the free 1 TiB
```

---

## The schema, and why it is shaped this way

| Table | Rows | Partition | Cluster |
|---|---:|---|---|
| `games` | 73,126 | none (dimension) | `season, season_type` |
| `player_game` | 1,481,840 | `game_date` MONTH, **filter required** | `team_id, season_type` |
| `play_by_play` | 18,280,064 | `game_date` MONTH, **filter required** | `team_id, action_type` |

**`game_date` is denormalized into `play_by_play`.** That table has only
`game_id` — no date at all. BigQuery has no indexes, so partition pruning is the
only way to avoid scanning all 18.3M rows, and you cannot partition on a column
that is not in the table. `export_to_parquet.py` joins it in from `games`.

**Monthly partitions, not daily.** The data starts in 1946. Roughly 80 years of
daily partitions is ~29,000 — past BigQuery's 10,000-partition ceiling, so the
load would simply fail. Monthly is ~960 and still prunes a season query hard.

**`require_partition_filter` is on for both fact tables.** A query with no date
predicate is *rejected* rather than quietly scanning everything. This is the
single most effective guard against burning the free tier by accident, and it is
why a naive `SELECT count(*) FROM play_by_play` will error — that is working as
intended, not a bug.

---

## Cost model — the part that differs from local DuckDB

Locally, a bad query costs seconds. Here it costs **bytes scanned**, against
1 TiB a month. Three layers guard that:

| Layer | What it does |
|---|---|
| `require_partition_filter` | server-side; rejects undated queries on the fact tables |
| `bq_query.py` dry run | free; reports exact bytes *before* running |
| `maximum_bytes_billed` | server-side hard cap; BigQuery **cancels** rather than exceeds |

The dry run informs; the cap enforces. Advisory limits do not survive a
distracted afternoon, which is why every query goes through both.

`bq_query.py --usage` reads month-to-date bytes billed from
`INFORMATION_SCHEMA.JOBS_BY_PROJECT` — the same source Google bills from — rather
than a local tally, which would drift the moment a query ran from the console.

---

## Gotchas found while building this

- **SQLite's dynamic typing breaks schema inference.** Sampling the first rows to
  guess column types fails ~1M rows into `play_by_play`: `shot_x` / `shot_y` /
  `shot_distance` are NULL for the opening plays of a game (a period-start event
  has no shot), so they get typed as string and then a real shot arrives. The
  exporter uses the **declared** types from `PRAGMA table_info` instead.
- **Parquet, not CSV**, so `game_date` arrives as a real `DATE` and can be a
  partition key without a second CAST pass.
- The export is written in 250k-row batches; 18.3M rows will not fit in memory.
