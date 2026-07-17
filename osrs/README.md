# osrs/ — clan companion

Local, **read-only** stats for an Old School RuneScape friend group, built on the
public OSRS Hiscores API. It snapshots tracked players over time so the clan can
race XP gains and see who's grinding what.

**No game automation.** This never touches the game client — it only reads the
same public Hiscores anyone can view on the website. (Botting the client is a ToS
violation and a ban-wave magnet; this is the opposite — it makes you the clan's
stats guy, out in the open.)

## Layers (mirrors `nba/` `pga/` `nfl/`)

| File | Role |
|------|------|
| `client.py`   | Hiscores HTTP client — throttle, retry, loud failure, `PlayerNotFound` |
| `parse.py`    | Pure functions: XP/level curve, JSON → rows, snapshot diffing |
| `db.py`       | SQLite schema + idempotent loaders (`players`, `snapshots`, `skill_xp`) |
| `snapshot.py` | CLI: `python -m osrs.snapshot` captures everyone now |
| `scoring.py`  | Competition ranking — **your contribution** (see below) |

DB lives in `osrs/data/osrs.db` (gitignored, regenerable from snapshots).

## Usage (from the `data_explorer` repo root)

```bash
python -m osrs.snapshot --add "Zezima"     # track a friend (repeat per person)
python -m osrs.snapshot --list             # who's tracked
python -m osrs.snapshot                     # snapshot everyone now
python -m pytest osrs/                      # run the tests
```

Schedule `python -m osrs.snapshot` daily (Windows Task Scheduler). Gains are the
diff between any two snapshots, so one capture per day is plenty.

**Validate after the first real run** (workspace rule: check against a known
fact). Look up a maxed account such as `Lynx Titan` — the first player to 200M XP
in every skill — and confirm Overall XP ≈ 4.6B and each skill reads 13,034,431.
If reality matches, the pipeline is sound.

## Roadmap

1. ✅ **Snapshots** — capture hiscores over time (this).
2. **Gains + leaderboards** — `diff_snapshots` over a window → weekly board.
3. **Discord** — post the weekly board to the clan via webhook.
4. **Competitions** — XP-race seasons (reuses the picks-worker pattern).
5. **Web dashboard** — optional, on Cloudflare Pages (`osrs.ericbackman.com`).

## Your contribution — `scoring.py`

`score_player()` decides *who's winning*, and it's a genuine design call:

- **Raw XP gained** rewards grind volume but favours maxed mains.
- **Levels gained** flatters fresh accounts; a maxed main can't win.
- **Effort-normalised (EHP-ish)** is the fairest across levels — and hardest.
- **A diversity bonus** rewards training many skills — directly serving the
  "don't just grind one thing" goal.

Implement it, then `python -m pytest osrs/`. `test_scoring.py` checks the
properties any sane metric must satisfy (e.g. monotonicity) without dictating
your formula — so the leaderboard's personality is yours to set.
