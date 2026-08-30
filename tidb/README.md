# TiDB — one table, both workloads (HTAP)

Puts `player_game` (1.48M rows) on [TiDB Cloud Starter](https://tidbcloud.com)
and gives it **both** a row store (TiKV) and a columnar store (TiFlash), kept in
sync by TiDB itself.

Third sibling of [`../bigquery`](../bigquery) and [`../neon`](../neon). The three
exist to answer different questions from the same source database:

| | Grain | Storage | Answers |
|---|---:|---|---|
| BigQuery | 18.3M events | columnar only | "what happened across a decade?" |
| Neon | 37k seasons | row only | "what did this player do that season?" |
| **TiDB** | **1.48M player-games** | **row *and* columnar** | **both, on one table** |

That middle case is the whole argument. A player's game log is a point lookup; a
league-wide seasonal aggregate is a full scan. Normally you serve the first from
Postgres, ETL into a warehouse for the second, and own the sync forever. TiDB
keeps two physical representations of one table and lets the optimizer pick.

---

## ⚠ Setup Eric has to do (once)

1. **Sign up** — <https://tidbcloud.com>. No card.
2. **Create a Starter cluster** (free: 5 GiB row + 5 GiB columnar + 50M RUs;
   up to five clusters per org).
3. **Connect → Connect With → General**, and copy the values into
   `%USERPROFILE%\.tidb\connection` as `KEY=VALUE` lines:

   ```
   TIDB_HOST=gateway01.<region>.prod.aws.tidbcloud.com
   TIDB_PORT=4000
   TIDB_USER=<prefix>.root
   TIDB_PASSWORD=<password>
   TIDB_DATABASE=test
   ```

   ⚠ "Save as type: All Files" so it does not become `connection.txt`.

`KEY=VALUE` rather than a single URL on purpose: TiDB usernames contain a dot
(`<prefix>.root`) and generated passwords contain characters needing
percent-encoding inside a URL — a step that is easy to get wrong once and then
spend an hour debugging as an authentication failure.

---

## Running it

```powershell
. C:\Users\ericb\Github\.claude\ops\tidb-env.ps1

cd C:\Users\ericb\Github\data_explorer\tidb
python load.py --counts-only    # what would load, touching nothing
python load.py                  # schema + 1.48M rows + TiFlash replica
python htap_demo.py             # the comparison
```

---

## The demonstration

[`htap_demo.py`](htap_demo.py) runs the *same* analytical query twice, changing
only which engines the optimizer may read from
(`tidb_isolation_read_engines`), and prints the plan and median runtime for each.
Then it runs a point lookup to show the row store still serving OLTP.

It is written to **report an unflattering result rather than hide one**: at
1.48M rows on an auto-scaling instance the row store can genuinely win on wall
clock, and the script says so if it does. The *plan change* is the real evidence,
because it is deterministic; the timing is not, and treating a noisy number as
proof would be the easy way to fool yourself here.

Adding columnar storage is one statement:

```sql
ALTER TABLE player_game SET TIFLASH REPLICA 1;
```

No ETL, no second system, and no window where the two representations disagree.
Replica building is asynchronous, so `load.py` polls
`information_schema.tiflash_replica` until it reports available — an `EXPLAIN`
run too early simply will not choose TiFlash, and the demo would look broken
when it had merely not finished.

---

## Schema decisions

**The primary key is `(game_id, player_id) CLUSTERED`, not an AUTO_INCREMENT id.**
In a distributed store a monotonically increasing key sends every insert to the
same region, and that write hotspot is the most common way a TiDB schema is got
wrong. A natural composite key spreads writes across the keyspace for free, and
`CLUSTERED` keeps the row data in the primary key's B-tree so a box-score read
touches one structure instead of two.

**`idx_player_date (player_id, game_date DESC)`** is the OLTP access path — a
player's game log, newest first. **`idx_season (season, season_type)`** narrows
seasonal analytics before any scan is needed.

---

## Operational limits worth knowing before debugging

These are Starter-tier behaviours that do not look like limits when they bite:

- **Connections are terminated after ~30 minutes** regardless of activity, and
  **AWS public endpoints idle out after 340 seconds**. Both surface as an abrupt
  closed connection mid-script. Long jobs should reconnect, not hold one handle.
- **Transactions are capped at 30 minutes.**
- **400 concurrent connections** (5,000 with a spending limit set).
- TLS is required; the public endpoint refuses a plaintext handshake.

---

## Verified before any account existed

The schema was applied to **real TiDB v8.5.0** in a throwaway container on
homebase, not just written:

- DDL applies cleanly;
- `TIDB_PK_TYPE` reports **CLUSTERED**, confirming the primary key is what was
  intended rather than silently non-clustered;
- all three indexes exist with the right column order;
- a point lookup plans as `IndexRangeScan` on `idx_player_date` reading
  `cop[tikv]`, with the `LIMIT` pushed into the index scan — the OLTP path works
  as designed.

**Not verified, and cannot be locally:** anything TiFlash. A standalone TiDB
container has no TiFlash node, so `SET TIFLASH REPLICA`, the replica build, and
the engine comparison in `htap_demo.py` all need a real TiDB Cloud cluster.
That is the part the account unlocks.
