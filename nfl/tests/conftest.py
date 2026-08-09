"""Skip the NFL tests when the nflverse client isn't installed.

`nfl/pull.py` imports nflreadpy at module scope - it has to, because the
`DATASETS` table is built from nflreadpy loader functions - so importing
anything from the `nfl` package pulls the dependency in. Without this guard a
fresh clone that hasn't installed the NFL extras fails COLLECTION, which aborts
the whole run and makes an otherwise-green suite look broken.

Skipping is the honest outcome: these tests are pure logic (season parsing,
spreadspoke normalization) but they cannot be imported without the dependency.
Install it with `pip install -r nfl/requirements.txt` to actually run them.

Note this uses `collect_ignore_glob` rather than `pytest.importorskip`: raising
Skipped from a conftest module body is a collection ERROR, not a skip, which is
the very failure this file exists to prevent.
"""
import importlib.util

collect_ignore_glob: list[str] = []

if importlib.util.find_spec("nflreadpy") is None:
    collect_ignore_glob = ["test_*.py"]
