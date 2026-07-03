"""CLI: render a trade to Mermaid and/or SVG.

    python -m trades --list
    python -m trades phx_top4_rolling --svg out.svg
    python -m trades swap_package --mermaid          # print Mermaid to stdout

By default (no --svg / --mermaid) it writes ``<example>.svg`` next to the cwd
and prints the Mermaid source.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import board, expand, ownership, render
from .examples import ALL as _EXAMPLES
from .real_2026 import ALL as _REAL, BOARD_2026_R1, RECENT_BLOCKBUSTERS

ALL = {**_EXAMPLES, **_REAL}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m trades", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("example", nargs="?", help="named example (see --list)")
    parser.add_argument("--list", action="store_true", help="list built-in examples")
    parser.add_argument("--svg", metavar="PATH", help="write SVG to PATH")
    parser.add_argument("--mermaid", action="store_true", help="print Mermaid to stdout")
    parser.add_argument("--own", action="store_true",
                        help="print the 'who owns what' ledger for the recent blockbusters "
                             "(with --svg, write the ownership board instead)")
    parser.add_argument("--board", action="store_true",
                        help="write the 2026 R1 full-draft ownership grid to --html")
    parser.add_argument("--strip", action="store_true",
                        help="write the slot strip (1-30 outcome map) for a protected pick "
                             "example to --html")
    parser.add_argument("--html", metavar="PATH", help="write an HTML fragment to PATH")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Mermaid/labels use → and — ; the Windows console defaults to cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # non-reconfigurable stream (e.g. a pipe wrapper) — best effort

    if args.board:
        cells = board.draft_board(2026, 1, BOARD_2026_R1)
        board_html = render.board_html(
            cells, "2026 First-Round Pick Ownership",
            "Colored by who controls each pick · sourced obligations only")
        out = args.html or "board.html"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(board_html)
        logging.getLogger(__name__).info("wrote draft board to %s", out)
        return 0

    if args.own:
        title = "Who owns what — 2026 offseason blockbusters"
        ledger = ownership.ownership(RECENT_BLOCKBUSTERS)
        if args.svg:
            render.ownership_svg(ledger, title, args.svg)
        else:
            print(title + "\n")
            print(ownership.to_markdown(ledger))
        return 0

    if args.list or not args.example:
        print("Available examples:")
        for key, trade in ALL.items():
            print(f"  {key:20s} {trade.name}")
        return 0

    trade = ALL.get(args.example)
    if trade is None:
        print(f"unknown example {args.example!r}; try --list", file=sys.stderr)
        return 2

    if args.strip:
        from .model import ProtectedPick
        pp = next((a for a in trade.assets if isinstance(a, ProtectedPick)), None)
        if pp is None:
            print(f"{args.example!r} has no protected pick to strip", file=sys.stderr)
            return 2
        strips = board.slot_strips(pp)
        out_html = render.slot_strip_html(strips, trade.name)
        out = args.html or f"{args.example}_strip.html"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(out_html)
        logging.getLogger(__name__).info("wrote slot strip to %s", out)
        return 0

    tree = expand.expand(trade)

    # Default behaviour when neither flag is given: do both.
    do_svg = args.svg or not args.mermaid
    do_mermaid = args.mermaid or not args.svg

    if do_mermaid:
        print(render.to_mermaid(tree))
    if do_svg:
        out = args.svg or f"{args.example}.svg"
        render.to_svg(tree, out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
