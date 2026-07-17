"""Publish the local sports SQLite DBs to a PRIVATE Kaggle Dataset.

Why this exists
---------------
Kaggle Notebooks give you ~30 GPU-hours/week of free compute with your data sitting
on local SSD (200 GB private-dataset cap), and every notebook is private behind your
Kaggle login. So Kaggle becomes "a personal Jupyter behind email auth, connected to
my DBs" with nothing to host. This script is the *push* half: it stages the chosen
``.db`` files plus the in-notebook query helper into one folder and uploads them as a
new version of the dataset, so your Kaggle notebooks always see current data.

The *query* half lives in ``kaggle_sportsdb.py`` — the Kaggle twin of
``analysis/sportsdb.py`` (same ``q``/``pl``/``databases``/``tables`` API).

Usage (from ``data_explorer/kaggle/``; run ``pip install kaggle`` once first)
----------------------------------------------------------------------------
    python push_datasets.py --create           # first time only
    python push_datasets.py -m "refresh data"  # later updates
    python push_datasets.py --skip-unchanged   # only push changed DBs (see fingerprint())

Auth
----
Needs Kaggle API credentials, via either
  * ``~/.kaggle/kaggle.json``  (kaggle.com -> Settings -> "Create New Token"), or
  * ``KAGGLE_USERNAME`` + ``KAGGLE_KEY`` environment variables.
The username is read from whichever is present to build the dataset id, so it is
never hardcoded in source (and the secret key is never read or logged here).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve everything relative to THIS file so the tool stays portable
# (Windows, the macOS mirror, CI) — never hardcode user paths.
_KAGGLE_DIR = Path(__file__).resolve().parent
_DATA_EXPLORER = _KAGGLE_DIR.parent

_STAGING = _KAGGLE_DIR / "_staging"
_HELPER = _KAGGLE_DIR / "kaggle_sportsdb.py"
_FINGERPRINTS = _KAGGLE_DIR / ".fingerprints.json"

# Dataset slug (the part after your username). Safe to commit — not sensitive.
DATASET_SLUG = "sports-dbs"
DATASET_TITLE = "Sports DBs (NBA / NFL / PGA)"

# alias -> local SQLite file. Twin of MANIFEST in analysis/sportsdb.py, kept
# separate so this uploader needs only the stdlib + the kaggle CLI (no duckdb).
# Add a line here (and to kaggle_sportsdb.MANIFEST) to publish another DB.
SOURCES: dict[str, Path] = {
    "nba": _DATA_EXPLORER / "nba" / "data" / "nba.db",
    "nfl": _DATA_EXPLORER / "nfl" / "data" / "nfl.db",
    "pga": _DATA_EXPLORER / "pga" / "data" / "pga.db",
}

_UPLOAD_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 15


def resolve_username() -> str:
    """Return the Kaggle username from env or ``~/.kaggle/kaggle.json``, or fail loudly."""
    user = os.getenv("KAGGLE_USERNAME")
    if user:
        return user
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if cred.exists():
        username = json.loads(cred.read_text(encoding="utf-8")).get("username")
        if username:
            return username
    raise RuntimeError(
        "No Kaggle credentials found. Create a token at "
        "https://www.kaggle.com/settings -> 'Create New Token', save it to "
        f"{cred}, or set KAGGLE_USERNAME / KAGGLE_KEY. See README.md."
    )


# --------------------------------------------------------------------------- #
#  YOUR CONTRIBUTION  (see tests/test_fingerprint.py)                          #
# --------------------------------------------------------------------------- #
def fingerprint(db_path: Path) -> str:
    """Return a short string that is the SAME when two copies of ``db_path`` hold the
    same data, and DIFFERENT when the data changed.

    ``--skip-unchanged`` uses this to avoid re-uploading a multi-GB DB that hasn't
    actually changed since the last push. The trade-off you're choosing is how to
    fingerprint a 3.6 GB file: cheaply enough to run every push, yet reliably enough
    that a real data change is never skipped.

    The tests pin down the property that matters (same bytes -> same fingerprint,
    changed data -> changed fingerprint) and deliberately rule out the naive
    mtime/size approaches. How you get there — full byte hash vs. a per-table
    content hash vs. something cleverer — is your call.
    """
    raise NotImplementedError(
        "Implement fingerprint() to unlock --skip-unchanged. "
        "See tests/test_fingerprint.py and the README."
    )


def should_push(db_path: Path, recorded: str | None) -> bool:
    """True if ``db_path`` is new (no recorded fingerprint) or has changed."""
    return recorded is None or fingerprint(db_path) != recorded


def load_fingerprints() -> dict[str, str]:
    if _FINGERPRINTS.exists():
        return json.loads(_FINGERPRINTS.read_text(encoding="utf-8"))
    return {}


def save_fingerprints(fingerprints: dict[str, str]) -> None:
    _FINGERPRINTS.write_text(json.dumps(fingerprints, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Staging + upload                                                           #
# --------------------------------------------------------------------------- #
def _build_is_fresh(dest: Path, sources: dict[str, Path]) -> bool:
    """True if ``dest`` exists and is newer than every source DB — so a rebuild (and
    re-measure) can be skipped, e.g. between a ``--dry-run`` and the real upload."""
    if not dest.exists():
        return False
    built = dest.stat().st_mtime
    return all(p.stat().st_mtime <= built for p in sources.values() if p.exists())


def stage(sources: dict[str, Path], username: str) -> Path:
    """Build (or reuse) the combined DuckDB file, add the helper + Kaggle metadata,
    and return the staged DuckDB path."""
    dest = _STAGING / "sports.duckdb"
    if _build_is_fresh(dest, sources):
        logger.info("Reusing fresh build: %s (%.2f GB)", dest.name, dest.stat().st_size / 1024**3)
    else:
        if _STAGING.exists():
            shutil.rmtree(_STAGING)
        _STAGING.mkdir(parents=True)
        from build_duckdb import build_combined  # lazy: keeps module import duckdb-free

        logger.info("Building %s from %d SQLite DBs (one-time per push)…", dest.name, len(sources))
        counts = build_combined(sources, dest)
        logger.info("Built %s (%.2f GB); tables per schema: %s",
                    dest.name, dest.stat().st_size / 1024**3, counts)

    if not _HELPER.exists():
        raise RuntimeError(f"In-notebook helper missing: {_HELPER}")
    shutil.copy2(_HELPER, _STAGING / _HELPER.name)

    # Generated here (not committed) so the username never lives in source.
    metadata = {
        "title": DATASET_TITLE,
        "id": f"{username}/{DATASET_SLUG}",
        "licenses": [{"name": "CC0-1.0"}],
    }
    (_STAGING / "dataset-metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return dest


def _kaggle_api():
    """Import + authenticate the Kaggle SDK lazily.

    Lazy so importing this module (e.g. for the fingerprint tests) never needs the
    kaggle package or credentials, and so it works with any Python that has
    ``pip install kaggle`` — no ``kaggle`` CLI on PATH required.
    """
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()  # reads ~/.kaggle/kaggle.json or KAGGLE_USERNAME / KAGGLE_KEY
    return api


def _is_transient(exc: Exception) -> bool:
    """True for network / rate-limit / 5xx errors worth retrying (not auth/validation)."""
    text = f"{getattr(exc, 'status', '')} {exc}".lower()
    return any(marker in text for marker in
               ("429", "500", "502", "503", "504", "timeout", "timed out", "connection"))


def _with_retry(action, what: str):
    """Run ``action`` with backoff, retrying only transient failures."""
    for attempt in range(1, _UPLOAD_RETRIES + 1):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 — re-raised below unless clearly transient
            if attempt >= _UPLOAD_RETRIES or not _is_transient(exc):
                raise
            logger.warning("%s failed (attempt %d/%d): %s — retrying",
                           what, attempt, _UPLOAD_RETRIES, exc)
            time.sleep(_RETRY_BACKOFF_SECONDS * attempt)


def publish(create: bool, message: str) -> None:
    """Create the dataset (first time) or push a new version — PRIVATE either way.

    Uses the Kaggle Python SDK in-process (which prints its own upload progress).
    ``convert_to_csv=False`` keeps the .db files byte-for-byte; ``dir_mode='skip'``
    uploads only the top-level staged files.
    """
    api = _kaggle_api()
    if create:
        _with_retry(
            lambda: api.dataset_create_new(
                str(_STAGING), public=False, convert_to_csv=False, dir_mode="skip"),
            "dataset create",
        )
    else:
        _with_retry(
            lambda: api.dataset_create_version(
                str(_STAGING), version_notes=message,
                convert_to_csv=False, dir_mode="skip"),
            "dataset version",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish local sports DBs to a private Kaggle dataset.")
    parser.add_argument("--create", action="store_true",
                        help="first-time dataset creation (omit for updates)")
    parser.add_argument("-m", "--message", default="update data",
                        help="version message (used for updates)")
    parser.add_argument("--skip-unchanged", action="store_true",
                        help="only upload if a DB changed since last push (needs fingerprint())")
    parser.add_argument("--dry-run", action="store_true",
                        help="build + stage the DuckDB file but do NOT upload")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    username = resolve_username()

    present = {a: p for a, p in SOURCES.items() if p.exists()}
    if args.skip_unchanged:
        recorded = load_fingerprints()
        changed = [a for a, p in present.items() if should_push(p, recorded.get(a))]
        if not changed:
            logger.info("No DB changed since last push — nothing to do.")
            return 0
        logger.info("Changed since last push: %s", ", ".join(changed))

    stage(present, username)
    if args.dry_run:
        logger.info("Dry run — built and staged, not uploading. Contents of %s:", _STAGING)
        for item in sorted(_STAGING.iterdir()):
            logger.info("  %s  (%.1f MB)", item.name, item.stat().st_size / 1024**2)
        return 0
    publish(args.create, args.message)
    logger.info("Done. Dataset (PRIVATE): https://www.kaggle.com/datasets/%s/%s",
                username, DATASET_SLUG)

    if args.skip_unchanged:
        save_fingerprints({a: fingerprint(p) for a, p in present.items()})

    shutil.rmtree(_STAGING, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
