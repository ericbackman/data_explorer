# Sports DBs on Kaggle: free hosted notebooks behind your login

Publish the local NBA / NFL / PGA SQLite DBs as a **private Kaggle Dataset**, then
open a Kaggle Notebook that queries them with the same API as `analysis/sportsdb.py`.

**Why Kaggle for this:** ~30 GPU-hours/week of free compute, a 200 GB private-dataset
cap (your full ~6 GB of DBs fits easily), and every notebook is private behind your
Kaggle login, so it's "a personal Jupyter behind email auth, connected to my DBs"
with nothing to host and no Cloudflare in the loop.

> **New here?** Follow [SETUP.md](SETUP.md). The click-by-click "for dummies" guide
> with every link and command. This README is the shorter reference version.

| File | Role |
|------|------|
| `build_duckdb.py` | Converts the SQLite DBs → one compressed `sports.duckdb` (a schema per sport). |
| `push_datasets.py` | Builds `sports.duckdb` + stages the helper and uploads them to Kaggle. |
| `kaggle_sportsdb.py` | In-notebook query layer (`q`/`pl`/`databases`/`tables`): opens `sports.duckdb` read-only; same API as `analysis/sportsdb.py`. Ships *inside* the dataset. |
| `starter_notebook.ipynb` | Minimal notebook: list DBs, run a query, draw a chart. |
| `tests/test_fingerprint.py` | Tests for the one function left for you to write (see below). |

---

## One-time setup

> The uploader uses the Kaggle Python SDK **pinned to `kaggle==1.6.17`** (the current
> default `pip install kaggle` is broken on import: `ModuleNotFoundError: kagglesdk`).
> It's already installed in your `analysis/.venv`.

### 1. Get a Kaggle API token
1. Sign in (or sign up) at **https://www.kaggle.com**.
2. Go to **https://www.kaggle.com/settings** → scroll to **API** → click **Create New Token**.
   This downloads `kaggle.json` (contains your username + key).
3. Move it to **`$env:USERPROFILE\.kaggle\kaggle.json`** (create the `.kaggle` folder if
   needed). That's where the credential lives: never commit it to a repo.

### 2. Publish the dataset (first push)
From `data_explorer/kaggle/`:
```powershell
$py = "$env:USERPROFILE\Github\data_explorer\analysis\.venv\Scripts\python.exe"
& $py push_datasets.py --create
```
This uploads ~6 GB once (slow the first time). It prints the dataset URL when done;
confirm it shows **Private**.

### 3. Create your notebook
1. Open the dataset URL → **New Notebook** (or kaggle.com → **Create → New Notebook**,
   then **Add Input** → your `sports-dbs` dataset).
2. Paste the cells from `starter_notebook.ipynb` (or **File → Import Notebook** and
   upload it). No internet toggle needed.

---

## Day-to-day

```powershell
# After re-scraping a DB, push fresh data (Kaggle versions the dataset):
& $py push_datasets.py -m "refresh nba through 2026-06"
```

In any notebook over the dataset:
```python
import sys; sys.path.append('/kaggle/input/sports-dbs')
import kaggle_sportsdb as sportsdb

sportsdb.databases()
sportsdb.q("SELECT * FROM nba.player_game LIMIT 5")     # -> pandas
sportsdb.pl("SELECT * FROM pga.tournaments")            # -> polars
```

**Add another DB:** add one line to `SOURCES` in `push_datasets.py` *and* one line to
`MANIFEST` in `kaggle_sportsdb.py`, then push again.

---

## Your contribution: `fingerprint()`

Re-uploading 6 GB every time you tweak one DB is wasteful. `push_datasets.py` has a
`--skip-unchanged` flag that only uploads when a DB actually changed, but it needs a
`fingerprint(db_path)` function, left as a stub for you to implement.

The decision that's yours: **how do you decide two versions of a 3.6 GB SQLite file are
"the same"?** Cheap-but-lies (mtime/size), correct-but-slow (hash every byte), or a
per-table content hash? The tests encode the property it must satisfy and rule out the
mtime trap; the strategy is your call.

```powershell
& $py -m pip install pytest   # once
& $py -m pytest -q            # from data_explorer/kaggle/ — red until you implement it
```

Once green, `python push_datasets.py --skip-unchanged` becomes a no-op when nothing
changed, and only pushes the DBs that did.

---

## Notes & trade-offs
- **Compressed single file:** the SQLite DBs are converted to one `sports.duckdb` (DuckDB
  columnar compression), shrinking ~6 GB to ~1.5 GB and speeding up queries. Written in
  the `v1.0.0` storage format so any DuckDB >= 1.0 can read it.
- **Read-only is enforced by Kaggle:** `/kaggle/input` is a read-only mount and the helper
  opens the file `read_only=True`: analysis can never corrupt the source.
- **Needs DuckDB in the notebook:** Kaggle's image ships it; if a cell reports it missing,
  turn Internet on and `!pip install duckdb` once. No SQLite extension needed.
- **Dirty SQLite typing:** the converter reads columns as text and `TRY_CAST`s them back
  to their intended types, so stray values (nflverse stores some as `" "`) become NULL
  instead of failing the build.
