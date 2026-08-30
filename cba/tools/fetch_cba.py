"""Download the official NBA CBA PDFs and extract them to text.

Sources are the NBA's own CDN and the NBPA mirror (authoritative primary sources). The
corpus is git-ignored (copyright), so this script is how you rebuild it from scratch:

    python tools/fetch_cba.py         # fetch + extract everything
    python tools/fetch_cba.py --list  # show sources without downloading

Requires `pdftotext` (poppler) on PATH. Paths resolve relative to this file.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("fetch_cba")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = PROJECT_ROOT / "corpus" / "pdf"
TEXT_DIR = PROJECT_ROOT / "corpus" / "text"

# stem -> (url, is_full_agreement). Full agreements get a <stem>.raw.txt; the short
# summary is extracted to <stem>.txt. Primary sources only.
SOURCES: dict[str, str] = {
    "2023-nba-cba": "https://ak-static.cms.nba.com/wp-content/uploads/sites/4/2023/06/2023-NBA-Collective-Bargaining-Agreement.pdf",
    "2017-nba-cba": "https://cosmic-s3.imgix.net/3c7a0a50-8e11-11e9-875d-3d44e94ae33f-2017-NBA-NBPA-Collective-Bargaining-Agreement.pdf",
    "2023-nba-cba-summary": "https://ak-static.cms.nba.com/wp-content/uploads/sites/4/2023/06/2023-CBA-Summary.pdf",
}


def download(url: str, dest: Path, retries: int = 3, timeout: int = 120) -> None:
    """Fetch a URL to dest with a timeout and a retry on transient failure."""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nba-cba-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted hosts)
                data = resp.read()
            if not data.startswith(b"%PDF"):
                raise ValueError(f"response is not a PDF (starts with {data[:8]!r})")
            dest.write_bytes(data)
            log.info("downloaded %s (%.2f MB)", dest.name, len(data) / 1_048_576)
            return
        except Exception as exc:  # noqa: BLE001 — log and retry, then fail loudly
            log.warning("attempt %d/%d failed for %s: %s", attempt, retries, dest.name, exc)
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def extract(pdf: Path, txt: Path) -> None:
    """Run pdftotext (poppler); fail loudly if it is missing or errors."""
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext not found on PATH — install poppler.")
    subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), str(txt)], check=True)
    log.info("extracted %s -> %s (%.0f KB)", pdf.name, txt.name, txt.stat().st_size / 1024)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="list sources and exit")
    args = ap.parse_args()

    if args.list:
        for stem, url in SOURCES.items():
            print(f"{stem}\n  {url}")
        return 0

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    for stem, url in SOURCES.items():
        pdf = PDF_DIR / f"{stem}.pdf"
        suffix = ".txt" if stem.endswith("summary") else ".raw.txt"
        download(url, pdf)
        extract(pdf, TEXT_DIR / f"{stem}{suffix}")

    log.info("done. next: python tools/build_index.py 2023-nba-cba")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
