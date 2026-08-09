"""Locate the local sports databases without hardcoding machine-specific paths.

The notebooks in this folder each open a SQLite file directly. Several of those
files live inside a **git worktree** (`.claude/worktrees/<name>/…`) rather than
the usual `<sport>/data/` folder, and a worktree's directory name is generated —
it differs per machine and changes when the worktree is recreated. Spelling any
of that into a notebook pins it to one laptop.

This module resolves paths the same way ``sportsdb.py`` does — relative to
``__file__`` — and adds a search for worktree-resident databases:

    import dbpath
    DB_PATH = dbpath.worktree_db("mlb", "data", "mlb.db")   # -> Path
    con = sqlite3.connect(dbpath.ro_uri(DB_PATH), uri=True)

Every lookup honours an environment override and **raises** when the database is
absent, so a missing DB fails loudly at the top of a notebook instead of
surfacing as an empty DataFrame halfway down.
"""
from __future__ import annotations

import os
from pathlib import Path

# Workspace layout resolved relative to THIS file — never hardcode user paths,
# so the project stays portable (Windows, the macOS mirror, CI, …).
_ANALYSIS_DIR = Path(__file__).resolve().parent
DATA_EXPLORER = _ANALYSIS_DIR.parent
WORKTREES = DATA_EXPLORER / ".claude" / "worktrees"


def _override(env_var: str | None) -> Path | None:
    """Return the path named by ``env_var``, or None when it is unset/empty."""
    if not env_var:
        return None
    raw = os.getenv(env_var)
    if not raw:  # unset or deliberately blank -> fall through to the search
        return None
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"{env_var} is set to {path}, but no file exists there."
        )
    return path


def db(*parts: str, env_var: str | None = None) -> Path:
    """Path to a database under ``data_explorer/`` (e.g. ``db("nba","data","nba.db")``).

    Raises FileNotFoundError if it is missing — these DBs are gitignored and
    regenerable, so the actionable failure is "run the scraper", not "return None".
    """
    if (chosen := _override(env_var)) is not None:
        return chosen
    path = DATA_EXPLORER / Path(*parts)
    if not path.exists():
        hint = f" Set {env_var} to point at it." if env_var else ""
        raise FileNotFoundError(
            f"Database not found at {path}. It is gitignored — rebuild it with "
            f"the sport's scraper.{hint}"
        )
    return path


def worktree_db(*parts: str, env_var: str | None = None) -> Path:
    """Find a database that lives inside a git worktree, by searching every worktree.

    ``worktree_db("mlb", "data", "mlb.db")`` matches
    ``.claude/worktrees/<any-name>/mlb/data/mlb.db``. Searching instead of naming
    the worktree is the point: the generated directory name is not stable, so a
    recreated worktree keeps working.

    Falls back to the canonical ``<sport>/data/`` location when the database has
    since been promoted out of the worktree. Raises if neither exists.
    """
    if (chosen := _override(env_var)) is not None:
        return chosen

    relative = Path(*parts)
    if WORKTREES.is_dir():
        # Sorted for determinism: two worktrees holding the same DB must not
        # resolve differently between runs.
        for worktree in sorted(p for p in WORKTREES.iterdir() if p.is_dir()):
            candidate = worktree / relative
            if candidate.exists():
                return candidate

    promoted = DATA_EXPLORER / relative
    if promoted.exists():
        return promoted

    hint = f" Set {env_var} to point at it." if env_var else ""
    raise FileNotFoundError(
        f"Could not find {relative} in any worktree under {WORKTREES}, nor at "
        f"{promoted}. The sports DBs are gitignored — rebuild it with the "
        f"sport's scraper, or check `git worktree list`.{hint}"
    )


def ro_uri(path: Path) -> str:
    """SQLite read-only URI for ``path``.

    Uses ``Path.as_uri()`` rather than string-concatenating ``file:///`` — the
    manual form silently produces ``file:////home/...`` (four slashes) on POSIX.
    Queries are read-only by convention here; ``mode=ro`` enforces it.
    """
    return f"{path.as_uri()}?mode=ro"
