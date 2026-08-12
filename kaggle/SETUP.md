# Kaggle setup — the "for dummies" guide

Goal: put your NBA/NFL/PGA DBs on Kaggle so you get **free hosted notebooks, private
behind your Kaggle login**, connected to your data — nothing to host. ~15 minutes,
most of it a one-time upload.

Everything code-side is done and tested. You do 3 things: **get a token → push the
data → make a notebook.**

---

## Prerequisites (already done ✅)

- `kaggle==1.6.17` is installed in your analysis venv. *(You don't need `uv` — it's
  not on your PATH anyway.)*
- Throughout this guide, `$py` is your Python. Paste this once per PowerShell window:
  ```powershell
  $py = "$env:USERPROFILE\Github\data_explorer\analysis\.venv\Scripts\python.exe"
  ```

---

## Step 1 — Create a Kaggle account (skip if you have one)

1. Go to **https://www.kaggle.com/account/login** → **Register** (Google sign-in is
   fine — use your Gmail).
2. That's it. **You do NOT need to verify your phone** — that's only for GPUs and
   notebook internet, neither of which this setup uses.

## Step 2 — Get your API token

1. Go to **https://www.kaggle.com/settings/api**
2. Scroll to **Legacy API Credentials** → click **Create Legacy API Key**. *(Not the
   "API Tokens (Recommended) → Generate New Token" button above it — those new-style tokens
   need a newer Kaggle client than the working `kaggle==1.6.17` and don't produce a `kaggle.json`.)*
3. Your browser downloads **`kaggle.json`** (username + secret key) to your Downloads folder.
4. Move it to `$env:USERPROFILE\.kaggle\kaggle.json`. Easiest — paste into PowerShell:
   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.kaggle" | Out-Null
   Move-Item "$env:USERPROFILE\Downloads\kaggle.json" "$env:USERPROFILE\.kaggle\kaggle.json" -Force
   ```
   *(If your browser saved it somewhere other than Downloads, change the first path.)*

> 🔒 **The token is a password.** It lives in `~/.kaggle/`, never in a repo. If it ever
> leaks, click **Expire Token** on the same settings page and make a new one.

## Step 3 — Push your data (first time)

Open PowerShell and run:

```powershell
$py = "$env:USERPROFILE\Github\data_explorer\analysis\.venv\Scripts\python.exe"
cd $env:USERPROFILE\Github\data_explorer\kaggle
& $py push_datasets.py --create
```

**What to expect:**
- First it converts the three SQLite DBs into one compressed `sports.duckdb` (~a few
  minutes, one-time), then uploads it — **~1.5 GB**, not the raw 6 GB. A progress bar
  streams; don't close the window.
- When it finishes it prints:
  `Done. Dataset (PRIVATE): https://www.kaggle.com/datasets/<you>/sports-dbs`
- Open that link → confirm the badge says **Private**.

## Step 4 — Make your notebook

1. On your dataset page (the link above), click **New Notebook** (top-right). This
   opens a Kaggle notebook **with your dataset already attached** as input.
2. Delete the default cell and paste this to confirm it's wired up:
   ```python
   import sys
   sys.path.append('/kaggle/input/sports-dbs')   # the helper ships inside your dataset
   import kaggle_sportsdb as sportsdb

   sportsdb.databases()   # should list nba / nfl / pga
   ```
3. Add a cell and run a real query:
   ```python
   sportsdb.q("""
       SELECT p.player_name, g.pts, g.game_date
       FROM nba.player_game g
       JOIN nba.players p USING (player_id)
       ORDER BY g.pts DESC
       LIMIT 10
   """)
   ```
4. Hit **Run All**. No internet toggle, no `pip install` — it uses the notebook's
   built-in `sqlite3` + `pandas`.

*(Prefer the ready-made notebook? In the editor: **File → Import Notebook** → upload
`starter_notebook.ipynb`. You still need **Add Input → your `sports-dbs` dataset** so
the files are mounted.)*

**That's it — you now have a personal, private notebook over your DBs.** ✅

---

## Using it later

**Query cheatsheet** (same API as your local `analysis/sportsdb.py`):
```python
sportsdb.databases()                                 # what's attached
sportsdb.tables()                                    # every table, all DBs
sportsdb.q("SELECT * FROM nba.player_game LIMIT 5")  # -> pandas
sportsdb.pl("SELECT * FROM pga.tournaments")         # -> polars
```

**Refresh the data after re-scraping** (Kaggle keeps versions):
```powershell
$py = "$env:USERPROFILE\Github\data_explorer\analysis\.venv\Scripts\python.exe"
cd $env:USERPROFILE\Github\data_explorer\kaggle
& $py push_datasets.py -m "refresh nba through 2026-07"   # note: NO --create after the first time
```
Then in the notebook, re-attach the newest dataset version (Kaggle prompts you) and Run All.

**Add another database:** one line in `SOURCES` (`push_datasets.py`) *and* one line in
`MANIFEST` (`kaggle_sportsdb.py`), then push again.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Could not find kaggle.json` | Token isn't at `$env:USERPROFILE\.kaggle\kaggle.json`. Redo Step 2. |
| `401 - Unauthorized` | Token wrong/expired. On the settings page, create a fresh **Legacy API Key**, then redo Step 2's move. |
| `ModuleNotFoundError: kagglesdk...` | You have the broken new kaggle. Fix: `& $py -m pip install "kaggle==1.6.17"`. |
| `409 - dataset already exists` on `--create` | You already created it once. Drop `--create` and use the `-m "..."` form. |
| Notebook: `No module named 'kaggle_sportsdb'` | The dataset isn't attached (**Add Input**), or its slug isn't `sports-dbs` (then change the `sys.path.append` path to match). |
| Notebook: `ModuleNotFoundError: duckdb` | Turn **Internet** ON (right sidebar) and run `!pip install duckdb` in a cell. |
| Upload died halfway | Just re-run the same command; it resumes/replaces. |
| Prompted to "verify phone" | Optional — only needed for GPUs/internet, not this setup. Ignore it. |

**All the links in one place:**
- Sign up: https://www.kaggle.com/account/login
- API token: https://www.kaggle.com/settings
- Your datasets: https://www.kaggle.com/me/datasets
- Kaggle API reference: https://github.com/Kaggle/kaggle-api
