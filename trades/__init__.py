"""trades — model NBA draft-pick trades (protections, swaps, sequential
conditions) and render every possible outcome as a flowchart.

Pure logic + rendering: touches no database. The pipeline is

    Trade  --expand.expand-->  OutcomeTree  --render.to_svg / to_mermaid-->  graphic

Typical use::

    from trades import expand, render
    from trades.examples import PHX_TOP4_ROLLING

    tree = expand.expand(PHX_TOP4_ROLLING)
    print(render.to_mermaid(tree))
    render.to_svg(tree, "phoenix_pick.svg")
"""

from . import model, expand, render  # noqa: F401
