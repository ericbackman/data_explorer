"""Team-identity helpers: MLB id->abbr and the opt-in franchise rollup."""
from __future__ import annotations

from draft import teams


def test_mlb_abbr_known_unknown_none():
    assert teams.mlb_abbr(120) == "WSH"   # Expos/Nationals franchise id
    assert teams.mlb_abbr(147) == "NYY"
    assert teams.mlb_abbr(99999) is None  # unknown id -> None (and logs), never guesses
    assert teams.mlb_abbr(None) is None


def test_current_franchise_rollup_and_passthrough():
    assert teams.current_franchise("NBA", "SEA") == "OKC"   # SuperSonics -> Thunder
    assert teams.current_franchise("NFL", "OAK") == "LV"
    assert teams.current_franchise("NBA", "LAL") == "LAL"   # unmapped passes through
    assert teams.current_franchise("NHL", None) is None
