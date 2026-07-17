"""The claim-locked script contract -- the trust backbone of the channel.

In production, the Opus script agent is handed build_claims() output plus the
SYSTEM_PROMPT below and may state no number that isn't in the payload. Before the
(expensive, semantic) Opus review gate runs, audit_script() is the cheap
deterministic tripwire: it flags any non-year, non-format number in a draft that
doesn't trace to the verified data. Cheap filter first, smart review second.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from pga.betting import DEFAULT_DB
from pga.db import connect

from essays.claims import allowed_numbers, build_claims

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You write scripts for a data-driven golf video essay. You are handed a CLAIMS
payload of verified statistics, each with the database row it came from.

HARD RULES (a reviewer will reject the script otherwise):
- State ONLY numbers that appear in the CLAIMS payload. Never invent or estimate
  a statistic. If you want to say it and it isn't in a claim, cut it.
- Every statistical sentence must correspond to a claim id you were given.
- Years, event names, and hole counts (18/36/54/72) are fine as context; any
  number that is a STAT must come from a claim.
- Tone: analytical and human, never mocking. Tell collapses with pathos, not
  ridicule -- these are real people who got closest and fell short.

STRUCTURE (four beats): hook (the lead usually fails) -> the god (the dominant
closer) -> the cursed (the great player who never converted) -> myth-correction
(the player whose reputation the data overturns) -> a short close.
"""

# Numbers that are structural facts about the format, not statistical claims.
_FORMAT_CONSTANTS = {9.0, 18.0, 36.0, 54.0, 72.0}
_YEAR = re.compile(r"^(19|20)\d{2}$")
_NUM = re.compile(r"\d+\.?\d*")


def audit_script(text: str, payload: dict, tol: float = 0.6) -> list[float]:
    """Return numbers in `text` that don't trace to the data (empty == clean).

    Tolerant of rounding (`tol`), simple percentage complements (100 - x), format
    constants (hole counts), and 4-digit years -- everything else must match a
    verified value or it is flagged for the reviewer.
    """
    allowed = allowed_numbers(payload) | _FORMAT_CONSTANTS
    allowed |= {100.0 - n for n in list(allowed) if n <= 100}

    flagged: list[float] = []
    for tok in _NUM.findall(text):
        if _YEAR.match(tok):  # contextual years, not stats
            continue
        n = float(tok)
        if not any(abs(n - a) <= tol for a in allowed):
            flagged.append(n)
    return flagged


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Audit a script against the verified claims.")
    ap.add_argument("script", type=Path, help="path to the script markdown")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = connect(DEFAULT_DB)
    try:
        payload = build_claims(conn)
    finally:
        conn.close()

    text = args.script.read_text(encoding="utf-8")
    flagged = audit_script(text, payload)
    if flagged:
        print(f"FAIL: {len(flagged)} number(s) not traceable to data: {sorted(set(flagged))}")
        sys.exit(1)
    print(f"PASS: every stat in {args.script.name} traces to a verified claim "
          f"({len(payload['claims'])} claims available).")


if __name__ == "__main__":
    main()
