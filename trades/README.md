# trades — NBA pick-trade flowcharts

Turn a confusing conditional draft-pick trade (protections, rolling
conditions, swaps) into a clean flowchart of **every possible outcome**.

Pure Python, no database, no external binary (no graphviz). The pipeline:

```
Trade  --expand.expand-->  OutcomeTree  --render.to_svg / to_mermaid-->  graphic
```

## Quick start

```bash
python -m trades --list                       # show built-in examples
python -m trades phx_top4_rolling --svg out.svg
python -m trades swap_package --mermaid        # print Mermaid to stdout
```

From code:

```python
from trades import expand, render
from trades.model import ProtectedPick, Protection, Trade

trade = Trade(
    name="PHX 1st, top-4 protected and rolling",
    teams=("PHX", "BKN"),
    assets=[ProtectedPick(
        origin="PHX", round=1, to="BKN",
        schedule=(
            (2026, Protection.top(4)),   # protected 1-4, conveys 5-30
            (2027, Protection.top(4)),
            (2028, Protection.top(2)),   # protection tightens
        ),
        fallback="becomes 2028 + 2029 second-round picks to BKN",
    )],
)

tree = expand.expand(trade)
print(render.to_mermaid(tree))       # portable, embeds in markdown/docs
render.to_svg(tree, "phx_pick.svg")  # standalone shareable graphic
```

## The three asset types (`model.py`)

| Asset | Meaning |
|-------|---------|
| `Pick` | An unconditional pick that changes hands outright. |
| `ProtectedPick` | Conveys only if it lands outside a protected slot range; otherwise **rolls forward** a year (`schedule` = one `(year, Protection)` per year) until a `fallback`. |
| `Swap` | One team's right to exchange its pick for another's; optionally voided by a `voided_if` protection. |

`Protection.top(n)` = protected in slots `1..n` (conveys `n+1..30`).
`Protection.none()` = unprotected (always conveys).

## Who owns what (real 2026 trades)

`real_2026.py` encodes actual, **sourced** 2026-offseason trades (Giannis→Heat,
Kessler→Lakers, plus protected picks). `ownership.py` rolls a set of trades up
into a per-team ledger — which picks each team now controls, tagged
🟢 unconditional / 🟡 conditional / 🔵 swap.

```bash
python -m trades --own                 # print the ledger for recent blockbusters
python -m trades --own --svg board.svg # render the "who owns what" board
python -m trades giannis --svg g.svg   # flowchart a single real trade
```

```python
from trades import ownership
from trades.real_2026 import RECENT_BLOCKBUSTERS

led = ownership.ownership(RECENT_BLOCKBUSTERS)
print(ownership.to_markdown(led))
```

## Slot strip — where a pick conveys (best view for a protected pick)

Shows one pick across **all 30 landing slots**: each cell is a draft slot,
colored by the receiving team where it conveys and amber where it's protected.
A rolling pick renders one strip per year.

```bash
python -m trades wizards_knicks --strip --html strip.html
```

```python
from trades import board, render
from trades.real_2026 import BLAZERS_BULLS

strips = board.slot_strips(BLAZERS_BULLS.assets[0])   # one per scheduled year
open("strip.html", "w", encoding="utf-8").write(
    render.slot_strip_html(strips, "Blazers 1st to Chicago"))
```

## Draft board — who controls each team's pick

```bash
python -m trades --board --html board.html
```

`board.draft_board(year, round, trades)` returns `{team: PickCell}`; team colors
live in `teams.py` (text color is computed for contrast, never hand-picked).

## Architecture

The design is **intermediate-representation-in-the-middle**:

- `expand.py` knows about protections and swaps but nothing about rendering.
  It produces a tree of `Decision` (a draft result that fans out) and
  `Outcome` (a terminal disposition) nodes.
- `render.py` knows about SVG/Mermaid but nothing about the draft. It walks
  the `Decision`/`Outcome` tree.

So the domain logic is written once, and adding a renderer (PNG, HTML,
Graphviz) is just another function reading the same tree.

Colour legend in the SVG: **blue** = draft-result decision, **green** =
pick conveys / swap happens, **amber** = fallback / swap voided.

## Tests

```bash
python -m pytest trades/
```
