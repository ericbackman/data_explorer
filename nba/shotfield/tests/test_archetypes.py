import pytest

from nba.shotfield import archetypes as a


class TestArchetype:
    @pytest.mark.parametrize("sub_type,expected", [
        ("Jump Shot", a.JUMPER),
        ("Pullup Jump shot", a.JUMPER),
        ("Step Back Jump shot", a.JUMPER),
        ("Fadeaway Jump Shot", a.JUMPER),
        ("Turnaround Jump Shot", a.JUMPER),
        ("Jump Bank Shot", a.JUMPER),
        ("Running Jump Shot", a.JUMPER),
        ("Layup Shot", a.LAYUP),
        ("Driving Layup Shot", a.LAYUP),
        ("Reverse Layup Shot", a.LAYUP),
        ("Driving Finger Roll Layup Shot", a.LAYUP),
        ("Dunk Shot", a.DUNK),
        ("Slam Dunk Shot", a.DUNK),
        ("Hook Shot", a.HOOK),
        ("Driving Hook Shot", a.HOOK),
        ("Tip Shot", a.TIP),
    ])
    def test_known_sub_types(self, sub_type, expected):
        assert a.archetype(sub_type) == expected

    def test_more_specific_finish_wins_over_family(self):
        """These match two families each; the finish is what the body does."""
        assert a.archetype("Tip Layup Shot") == a.LAYUP
        assert a.archetype("Putback Layup Shot") == a.LAYUP
        assert a.archetype("Putback Dunk Shot") == a.DUNK
        assert a.archetype("Running Finger Roll Layup Shot") == a.LAYUP

    def test_unknown_and_missing_fall_back_to_jumper(self):
        assert a.archetype(None) == a.JUMPER
        assert a.archetype("") == a.JUMPER
        assert a.archetype("No Shot") == a.JUMPER

    def test_result_is_always_a_known_archetype(self):
        for sub_type in ("Jump Shot", "Tip Layup Shot", None, "weird"):
            assert a.archetype(sub_type) in a.ARCHETYPES


class TestMotion:
    @pytest.mark.parametrize("sub_type,expected", [
        ("Driving Layup Shot", a.TOWARD),
        ("Cutting Layup Shot", a.TOWARD),
        ("Running Jump Shot", a.TOWARD),
        ("Step Back Jump shot", a.AWAY),
        ("Fadeaway Jump Shot", a.AWAY),
        ("Turnaround Jump Shot", a.AWAY),
        ("Tip Shot", a.SCRAMBLE),
        ("Putback Layup Shot", a.SCRAMBLE),
    ])
    def test_labelled_motion(self, sub_type, expected):
        assert a.motion(sub_type) == expected

    def test_plain_jumper_reports_no_label_not_stationary(self):
        """The shooter may well have moved; the data does not say. Claiming
        'stationary' would be inventing a fact."""
        assert a.motion("Jump Shot") == a.NO_LABEL
        assert a.motion(None) == a.NO_LABEL


class TestEntry:
    def test_assisted_is_a_catch(self):
        assert a.entry(True) == a.CATCH

    def test_unassisted_is_self_created(self):
        assert a.entry(False) == a.DRIBBLE

    def test_missing_is_unknown_not_unassisted(self):
        """Assists are recorded only on makes. Folding None into 'unassisted'
        would invent a self-created shot for every miss in the game."""
        assert a.entry(None) == a.UNKNOWN


class TestMissingLabels:
    def test_2006_game_predates_pullup_and_stepback(self):
        """Kobe's 81 is 2006-01-22, before the NBA recorded either label."""
        gaps = a.missing_labels("2006-01-22")
        assert "Pullup Jump shot" in gaps
        assert "Step Back Jump shot" in gaps
        assert "Jump Shot" not in gaps
        assert "Fadeaway Jump Shot" not in gaps

    def test_modern_game_has_full_taxonomy(self):
        assert a.missing_labels("2024-03-01") == []

    def test_1999_game_also_lacks_fadeaway(self):
        gaps = a.missing_labels("1999-01-01")
        assert "Fadeaway Jump Shot" in gaps
        assert "Driving Layup Shot" not in gaps


class TestClassifyAndSummarise:
    def test_classify_attaches_all_three_signals(self):
        row = a.classify({"sub_type": "Driving Layup Shot", "assisted": True})
        assert row["archetype"] == a.LAYUP
        assert row["motion"] == a.TOWARD
        assert row["entry"] == a.CATCH
        assert row["sub_type"] == "Driving Layup Shot"   # original preserved

    def test_summarise_counts_every_signal(self):
        shots = [
            {"sub_type": "Jump Shot", "assisted": True},
            {"sub_type": "Jump Shot", "assisted": None},
            {"sub_type": "Slam Dunk Shot", "assisted": False},
        ]
        counts = a.summarise(shots)
        assert counts["archetype"] == {a.JUMPER: 2, a.DUNK: 1}
        assert counts["entry"] == {a.CATCH: 1, a.UNKNOWN: 1, a.DRIBBLE: 1}
        assert sum(counts["motion"].values()) == 3
