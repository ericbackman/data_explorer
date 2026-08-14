"""Unit tests for the pure sumo logic — no network, no DB.

The safety-critical piece is the point-in-time measurement policy
(``physical.resolve_measurement``): every physical conclusion in the deep dive
rests on joining a bout to the size recorded *by then*, not the career-latest
weight. A regression there would not crash — it would just quietly answer a
different question. So the policy's edge cases are pinned down here.
"""

from sumo import api, physical


# ── api.enumerate_basho ───────────────────────────────────────────────────────

def test_enumerate_basho_covers_the_six_odd_months():
    assert api.enumerate_basho("200501", "200511") == [
        "200501", "200503", "200505", "200507", "200509", "200511"]


def test_enumerate_basho_is_inclusive_and_crosses_years():
    assert api.enumerate_basho("200509", "200603") == [
        "200509", "200511", "200601", "200603"]


def test_enumerate_basho_empty_when_range_holds_no_tournament():
    assert api.enumerate_basho("200502", "200502") == []


# ── api._positive: 0 kg is unknown, not real ──────────────────────────────────

def test_positive_treats_zero_and_junk_as_unknown():
    assert api._positive(158.5) == 158.5
    assert api._positive("174") == 174.0
    assert api._positive(0) is None          # the API's "no measurement" sentinel
    assert api._positive(-1) is None
    assert api._positive(None) is None
    assert api._positive("n/a") is None


# ── api.parse_bouts: only completed contests ──────────────────────────────────

def _torikumi(*records):
    return {"torikumi": list(records)}


def _bout(**over):
    base = {"bashoId": "201101", "division": "Makuuchi", "day": 1, "matchNo": 1,
            "eastId": 11, "westId": 22, "winnerId": 11, "kimarite": "yorikiri"}
    base.update(over)
    return base


def test_parse_bouts_drops_matches_with_no_winner_yet():
    rows = api.parse_bouts(_torikumi(_bout(), _bout(matchNo=2, winnerId=None)))
    assert [r["match_no"] for r in rows] == [1]


def test_parse_bouts_keeps_kimarite_so_fusen_can_be_excluded_downstream():
    rows = api.parse_bouts(_torikumi(_bout(kimarite="fusen")))
    assert rows[0]["kimarite"] == "fusen"
    assert api.parse_bouts(_torikumi(_bout(kimarite=None)))[0]["kimarite"] == ""


def test_parse_bouts_on_empty_payload_is_empty_not_an_error():
    assert api.parse_bouts({}) == []


# ── api.parse_measurements: change-points, zeros dropped ──────────────────────

def test_parse_measurements_drops_rows_with_no_usable_value():
    raw = {"id": 7, "measurementHistory": [
        {"bashoId": "200501", "height": 190, "weight": 158},
        {"bashoId": "200503", "height": 0, "weight": 0},      # sentinel-only row
        {"bashoId": "200505", "height": 0, "weight": 161},    # partial is still useful
    ]}
    rows = api.parse_measurements(raw)
    assert [r["basho_id"] for r in rows] == ["200501", "200505"]
    assert rows[1]["height_cm"] is None and rows[1]["weight_kg"] == 161.0


# ── physical.resolve_measurement — THE point-in-time policy ───────────────────

MEAS = [
    {"basho_id": "200501", "height_cm": 190.0, "weight_kg": 158.0},
    {"basho_id": "200901", "height_cm": 191.0, "weight_kg": 155.0},
    {"basho_id": "201501", "height_cm": 191.0, "weight_kg": 174.0},
]


def test_resolves_to_the_most_recent_measurement_at_or_before_the_bout():
    assert physical.resolve_measurement(MEAS, "201101") == (191.0, 155.0)


def test_a_bout_in_the_measurement_month_uses_that_measurement():
    assert physical.resolve_measurement(MEAS, "200901") == (191.0, 155.0)


def test_never_borrows_a_later_weight_for_an_earlier_bout():
    """The whole point: a 2011 bout must not see the 2015 (174 kg) weight."""
    assert physical.resolve_measurement(MEAS, "201101")[1] != 174.0


def test_a_bout_after_the_last_measurement_carries_it_forward():
    assert physical.resolve_measurement(MEAS, "202601") == (191.0, 174.0)


def test_a_bout_before_the_first_measurement_falls_back_to_the_earliest():
    """Documented fallback — keeps early-career bouts instead of dropping them."""
    assert physical.resolve_measurement(MEAS, "200301") == (190.0, 158.0)


def test_unknown_is_none_never_a_fake_zero():
    assert physical.resolve_measurement([], "201101") == (None, None)


# ── physical derived features ─────────────────────────────────────────────────

def test_bmi_and_its_unknown_handling():
    assert physical._bmi(190.0, 158.0) == 43.77
    for bad in ((None, 158.0), (190.0, None), (0, 158.0)):
        assert physical._bmi(*bad) is None


def test_age_years_is_none_without_both_dates():
    assert physical._age_years(None, "2011-01-09") is None
    assert physical._age_years("1985-03-11", None) is None


def test_age_years_matches_the_calendar_closely_enough_to_bin_on():
    age = physical._age_years("1985-03-11", "2011-01-09")
    assert 25.7 < age < 25.9


def test_sub_propagates_unknown_rather_than_inventing_a_zero_edge():
    assert physical._sub(174.0, 158.0) == 16.0
    assert physical._sub(None, 158.0) is None
    assert physical._sub(174.0, None) is None
