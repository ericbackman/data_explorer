"""Per-league draft source adapters.

Each module exposes `fetch(years=None) -> list[dict]`, returning rows already
normalized to the `draft.db` column set. The build orchestrator wires them up;
keeping them uniform means adding a sport later is one new module.
"""
