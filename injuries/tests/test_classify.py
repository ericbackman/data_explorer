import pytest

from injuries.classify import (
    COACH,
    ILLNESS,
    INJURY,
    INJURY_UNSPECIFIED,
    PERSONAL,
    PROTOCOL,
    REST,
    ROSTER,
    SUSPENSION,
    UNKNOWN,
    classify,
    normalise,
    publishable_text,
)


@pytest.mark.parametrize(
    "text, category, location, side, nature, below_knee",
    [
        # box-score comments
        ("DND - Sprained Left Ankle", INJURY, "ankle", "left", "sprain", True),
        ("DNP - Coach's Decision", COACH, "", "", "", False),
        ("DNP - Injury/Illness", INJURY_UNSPECIFIED, "", "", "", False),
        ("NWT - Personal Reasons", PERSONAL, "", "", "", False),
        ("NWT - League Suspension", SUSPENSION, "", "", "", False),
        ("DND - Rest", REST, "", "", "", False),
        ("DND - Flu", ILLNESS, "", "", "", False),
        ("DND - Sore Right Knee", INJURY, "knee", "right", "soreness", False),
        ("DND - Strained Left Hamstring", INJURY, "hamstring", "left", "strain", False),
        ("DND - Ruptured Achilles Tendon", INJURY, "achilles", "", "rupture", True),
        ("DND - Strained Right Calf", INJURY, "lower_leg", "right", "strain", True),
        ("DND - Concussion", INJURY, "head", "", "concussion", False),
        ("DND - Back Spasms", INJURY, "back", "", "", False),
        ("DND - Stress Fracture, Foot", INJURY, "foot", "", "fracture", True),
        ("DNP - Health and Safety Protocols", PROTOCOL, "", "", "", False),
        ("NWT - Trade Pending", ROSTER, "", "", "", False),
        ("no memo for staff", ROSTER, "", "", "", False),
        ("DND - Return to Competition Reconditioning", REST, "", "", "", False),
        ("DND - Knee Surgery", INJURY, "knee", "", "surgery", False),
        ("DND - Plantar Fasciitis", INJURY, "foot", "", "tendinitis", True),
        ("DND - Torn Meniscus, Knee", INJURY, "knee", "", "rupture", False),
        ("DND - Sprained MCL", INJURY, "knee", "", "sprain", False),
        ("DND - Irregular Heartbeat", ILLNESS, "", "", "", False),
        ("DND - Death In Family", PERSONAL, "", "", "", False),
        # official injury report format
        ("Injury/Illness - Left Ankle; Sprain", INJURY, "ankle", "left", "sprain", True),
        ("Injury/Illness - Right Achilles Tendon; Rupture", INJURY, "achilles", "right", "rupture", True),
        ("Injury/Illness - Illness", ILLNESS, "", "", "", False),
        ("Injury/Illness - Non-Covid; Illness", ILLNESS, "", "", "", False),
        ("Injury/Illness - Left Knee; Injury Management", INJURY, "knee", "left", "soreness", False),
        ("G League - Two-Way", ROSTER, "", "", "", False),
        ("Rest", REST, "", "", "", False),
        ("Health and Safety Protocols", PROTOCOL, "", "", "", False),
        ("Injury/Illness - Concussion Protocol", INJURY, "head", "", "concussion", False),
        # PST notes
        ("sprained left ankle (DNP)", INJURY, "ankle", "left", "sprain", True),
        ("placed on IL for personal reasons", PERSONAL, "", "", "", False),
        ("recovering from surgery on left knee to repair torn ACL (DNP)", INJURY, "knee", "left", "rupture", False),
        ("returned to lineup", UNKNOWN, "", "", "", False),
        ("activated from IL", UNKNOWN, "", "", "", False),
        ("plantar fasciitis in right foot (DNP)", INJURY, "foot", "right", "tendinitis", True),
        ("arthroscopic surgery on right knee (out indefinitely)", INJURY, "knee", "right", "surgery", False),
        ("strained right calf (DTD)", INJURY, "lower_leg", "right", "strain", True),
        # official report vocabulary
        ("Injury/Illness - Torn right anterior cruciate ligament", INJURY, "knee", "right", "rupture", False),
        ("Injury/Illness - Left Cuneiform; Fracture", INJURY, "foot", "left", "fracture", True),
        ("Injury/Illness - Right Iliac Wing; Fracture", INJURY, "hip_groin", "right", "fracture", False),
        ("Injury/Illness - Left Ulnar Styloid; Fracture", INJURY, "hand_wrist", "left", "fracture", False),
        ("Injury/Illness - Right Acromioclavicular; Sprain", INJURY, "shoulder", "right", "sprain", False),
        ("Injury/Illness - Left Superior Tib/fib; Sprain", INJURY, "ankle", "left", "sprain", True),
        ("Not With Team", ROSTER, "", "", "", False),
        ("NWT", ROSTER, "", "", "", False),
        # edge cases
        ("", UNKNOWN, "", "", "", False),
        ("DNP", UNKNOWN, "", "", "", False),
        ("DND - Sore Leg", INJURY, "leg_unspecified", "", "soreness", False),
        ("DND - Surgery", INJURY, "other", "", "surgery", False),
    ],
)
def test_classify(text, category, location, side, nature, below_knee):
    label = classify(text)
    assert label.category == category, text
    assert label.location == location, text
    assert label.side == side, text
    assert label.nature == nature, text
    assert label.below_knee is below_knee, text


def test_whole_word_matching():
    # "arm" must not fire on "warm-up"; "ill" must not fire on "Illinois"
    assert classify("DND - warm-up injury").location == ""  # 'arm' not matched, no body part
    assert classify("NWT - Illinois").category == ROSTER  # the NWT prefix carries the reason; 'ill' never fires
    assert classify("Illinois").category == UNKNOWN


def test_normalise_strips_prefix_and_quotes():
    assert normalise('"DNP - Sprained Ankle"') == "sprained ankle"
    assert normalise("Did Not Dress - Flu") == "flu"
    assert normalise("  DND -   Sore   Knee ") == "sore knee"


def test_region_consistency():
    assert classify("DND - Sprained Ankle").region == "below_knee"
    assert classify("DND - Sore Knee").region == "knee"
    assert classify("DND - Strained Groin").region == "upper_leg"
    assert classify("DND - Sprained Thumb").region == "upper_body"


def test_partial_tear_is_not_a_rupture():
    assert classify("DND - Partial Tear Right Achilles").nature == "partial_tear"
    assert classify("Injury/Illness - Right Achilles Tendon; Tear").nature == "rupture"


def test_publishable_text_blanks_everything_but_injury_rest_suspension():
    assert publishable_text("DND - Sprained Left Ankle", INJURY) == "DND - Sprained Left Ankle"
    assert publishable_text("DNP - Injury/Illness", INJURY_UNSPECIFIED) == "DNP - Injury/Illness"
    assert publishable_text("DND - Rest", REST) == "DND - Rest"
    assert publishable_text("NWT - League Suspension", SUSPENSION) == "NWT - League Suspension"
    for cat, text in ((ILLNESS, "DND - Flu"), (PERSONAL, "NWT - Death In Family"), (PROTOCOL, "Health and Safety Protocols"), (ROSTER, "NWT - Trade Pending"), (COACH, "DNP - Coach's Decision"), (UNKNOWN, "something odd")):
        assert publishable_text(text, cat) == "", cat
