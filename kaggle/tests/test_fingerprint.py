"""Red-by-design tests for YOUR fingerprint() contribution in push_datasets.py.

Run from data_explorer/kaggle/:
    uv run --with pytest python -m pytest -q

They fail until you implement fingerprint() — that's the point. They pin down the
one property that matters for change-detection (same data -> same fingerprint,
changed data -> changed fingerprint) and deliberately rule out the naive
mtime-based approach, without forcing a specific hashing strategy.
"""
import shutil
import sqlite3
from pathlib import Path

import pytest

from push_datasets import fingerprint


def _make_db(path: Path, rows: list[tuple[int, str]]) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER, v TEXT)")
    con.executemany("INSERT INTO t VALUES (?, ?)", rows)
    con.commit()
    con.close()


def test_same_data_same_fingerprint(tmp_path: Path) -> None:
    """A byte-identical copy with a *fresh* mtime must fingerprint the same.

    shutil.copy (NOT copy2) gives `b` identical bytes but a new modification time,
    so an mtime-based implementation fails here while a content/byte hash passes —
    which is exactly the discrimination we want.
    """
    a = tmp_path / "a.db"
    _make_db(a, [(1, "x"), (2, "y")])
    b = tmp_path / "b.db"
    shutil.copy(a, b)
    assert fingerprint(a) == fingerprint(b)


def test_changed_data_changes_fingerprint(tmp_path: Path) -> None:
    """Inserting a row must change the fingerprint (rules out a constant)."""
    p = tmp_path / "c.db"
    _make_db(p, [(1, "x")])
    before = fingerprint(p)

    con = sqlite3.connect(p)
    con.execute("INSERT INTO t VALUES (3, 'z')")
    con.commit()
    con.close()

    assert fingerprint(p) != before


def test_deterministic(tmp_path: Path) -> None:
    """Two reads of the same unchanged file agree."""
    p = tmp_path / "d.db"
    _make_db(p, [(1, "x")])
    assert fingerprint(p) == fingerprint(p)
