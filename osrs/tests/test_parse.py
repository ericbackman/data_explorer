"""Pure-function tests — no network, no DB. Run: python -m pytest osrs/"""

from osrs import parse


def test_xp_for_level_known_anchors():
    assert parse.xp_for_level(1) == 0
    assert parse.xp_for_level(2) == 83
    assert parse.xp_for_level(99) == 13_034_431   # the canonical OSRS "99" number


def test_level_for_xp_boundaries():
    assert parse.level_for_xp(0) == 1
    assert parse.level_for_xp(82) == 1            # one short of level 2 (83 xp)
    assert parse.level_for_xp(83) == 2
    assert parse.level_for_xp(13_034_431) == 99
    assert parse.level_for_xp(999_999_999) == 99  # capped at the in-game max


def test_parse_hiscores_clamps_unranked_and_keeps_overall():
    payload = {"skills": [
        {"id": 0, "name": "Overall", "rank": 50000, "level": 100, "xp": 5000},
        {"id": 1, "name": "Attack",  "rank": 40000, "level": 40,  "xp": 37224},
        {"id": 18, "name": "Slayer", "rank": -1, "level": 1, "xp": -1},  # unranked
    ]}
    by = {s["skill"]: s for s in parse.parse_hiscores(payload)}
    assert by["Slayer"]["xp"] == 0          # -1 clamped to 0
    assert by["Slayer"]["rank"] is None     # -1 rank -> None
    assert by["Attack"]["xp"] == 37224
    assert parse.overall(list(by.values()))["xp"] == 5000


def test_diff_snapshots_excludes_overall_and_floors_at_zero():
    before = [
        {"skill": "Overall", "rank": 1, "level": 100, "xp": 1000},
        {"skill": "Mining",  "rank": 1, "level": 40,  "xp": 37224},
        {"skill": "Fishing", "rank": 1, "level": 50,  "xp": 101333},
    ]
    after = [
        {"skill": "Overall", "rank": 1, "level": 103, "xp": 1500},
        {"skill": "Mining",  "rank": 1, "level": 43,  "xp": 50000},
        {"skill": "Fishing", "rank": 1, "level": 50,  "xp": 90000},  # hiccup: lower
    ]
    by = {d["skill"]: d for d in parse.diff_snapshots(before, after)}
    assert "Overall" not in by                       # derived total excluded
    assert by["Mining"]["xp_gained"] == 50000 - 37224
    assert by["Mining"]["levels_gained"] == 3
    assert by["Fishing"]["xp_gained"] == 0           # negative floored to 0


def test_canonical_rsn_normalizes_case_and_separators():
    assert parse.canonical_rsn("  Lynx_Titan ") == "lynx titan"
    assert parse.canonical_rsn("Zezima") == "zezima"
