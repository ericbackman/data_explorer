# NBA Data Explorer

A collection of NBA data tools and Claude Code skills built on top of the
[nba_api](https://github.com/swar/nba_api) library.

## Contents

| File | Description |
|---|---|
| `nba_dashboard.py` | Standalone NBA player dashboard script (CLI + importable module) |
| `nba_player_dashboard.ipynb` | Jupyter notebook version of the player dashboard |
| `sportsrc_importer.ipynb` | Jupyter notebook for the SportSRC public sports API |
| `.claude/commands/nba-dashboard.md` | Claude Code skill: `/nba-dashboard` |

---

## Requirements

```
pip install nba_api requests pandas
```

Python 3.10+ is required.

---

## Claude Code Skill — `/nba-dashboard`

This repo ships a [project-scoped Claude Code skill](https://docs.anthropic.com/en/docs/claude-code/slash-commands)
that lets you pull up a full NBA player dashboard inside Claude Code.

### Setup

Clone the repo and open it as your Claude Code working directory. The skill is
automatically available as `/nba-dashboard` because it lives in
`.claude/commands/nba-dashboard.md`.

### Usage

```
/nba-dashboard LeBron James
/nba-dashboard Nikola Jokic 2024-25
/nba-dashboard Jayson Tatum
```

The skill runs `nba_dashboard.py` and presents a formatted summary covering:

1. **Season averages** — PPG, RPG, APG, SPG, BPG, FG%, 3P%, FT%
2. **Last 5 & Last 10 game averages** — rolling per-game stats
3. **Quarter-by-quarter breakdown** — PTS per quarter with hot/cold pattern detection
4. **Recent game log** — last 5 games with box score stats
5. **Team injury report** — current injuries via the ESPN public API

---

## CLI Usage

```bash
python nba_dashboard.py "LeBron James"
python nba_dashboard.py "Nikola Jokic" 2024-25
python nba_dashboard.py "Jayson Tatum" 2025-26
```

If no season is provided, it defaults to `2025-26`.

### Example Output

```
==============================================================
  NBA PLAYER DASHBOARD
  NIKOLA JOKIC
  Denver Nuggets  |  Season: 2025-26
==============================================================

[ PER-GAME AVERAGES ]
──────────────────────────────────────────────────────────────
  Span            GP     MPG     PPG     RPG     APG     SPG ...
  ────────────────────────────────────────────────────────────
  Last 5          5     34.2    29.4    13.2     9.8     1.6 ...
  Last 10        10     33.8    28.1    12.9     9.4     1.4 ...
  Season         52     33.6    27.2    12.5     9.1     1.4 ...
...
```

---

## Module Usage

`nba_dashboard.py` is also fully importable:

```python
from nba_dashboard import get_player_dashboard, print_dashboard

# Get structured data
data = get_player_dashboard("Nikola Jokic", season="2025-26")
print(data["season_avgs"])
print(data["last5"])
print(data["qbq_last5"])

# Or print the full dashboard
print_dashboard("LeBron James")
```

---

## Notebooks

### `nba_player_dashboard.ipynb`
Interactive version of the player dashboard. Run cells top-to-bottom, setting
the `PLAYER_NAME` and `SEASON` variables at the top.

### `sportsrc_importer.ipynb`
Explores the free [SportSRC public API](https://api.sportsrc.org/) — sports
categories, match schedules, league standings, and historical scores. No API
key required.

---

## License

MIT — see [LICENSE](LICENSE).
