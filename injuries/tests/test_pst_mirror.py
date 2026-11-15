import csv
import io

import pytest

from injuries.pst_mirror import dedupe, normalise_name, parse_rows, season_of, season_summary


def test_season_of():
    assert season_of("2024-10-22") == "2024-25"
    assert season_of("2025-04-13") == "2024-25"
    assert season_of("2025-08-01") == "2025-26"
    assert season_of("1999-12-31") == "1999-00"


def test_normalise_name():
    assert normalise_name("Kobe Bryant / Kobe Bean Bryant") == "Kobe Bryant"
    assert normalise_name("• LeBron James") == "LeBron James"


def _reader(text):
    return csv.DictReader(io.StringIO(text))


def test_parse_rows_out_and_return():
    text = (
        ",Date,Team,Acquired,Relinquished,Notes\n"
        "0,2010-08-03,Clippers,,Craig Smith,arthroscopic surgery on right knee (out indefinitely)\n"
        "1,2010-11-01,Clippers,Craig Smith,,returned to lineup\n"
    )
    rows = parse_rows(_reader(text), source="t")
    assert [r["event_type"] for r in rows] == ["out", "return"]
    assert rows[0]["category"] == "injury" and rows[0]["location"] == "knee" and rows[0]["side"] == "right"
    assert rows[0]["season"] == "2010-11"
    assert rows[1]["category"] == "unknown"


def test_parse_rows_requires_columns():
    with pytest.raises(ValueError):
        parse_rows(_reader("Date,Team\n2010-01-01,X\n"), source="t")


def test_dedupe_and_summary():
    text = (
        ",Date,Team,Acquired,Relinquished,Notes\n"
        "0,2012-01-05,Heat,,Dwyane Wade,sprained left ankle (DNP)\n"
        "1,2012-01-05,Heat,,Dwyane Wade,sprained left ankle (DNP)\n"
        "2,2012-01-06,Heat,,Chris Bosh,flu (DNP)\n"
    )
    events = dedupe(parse_rows(_reader(text), source="a") + parse_rows(_reader(text), source="b"))
    assert len(events) == 2
    summary = season_summary(events)
    assert summary[0]["season"] == "2011-12"
    assert summary[0]["out_events"] == 2
    assert summary[0]["injury"] == 1 and summary[0]["illness"] == 1
    assert summary[0]["below_knee"] == 1
    assert summary[0]["loc_ankle"] == 1


def test_non_injury_notes_are_blanked_and_staff_rows_dropped():
    text = (
        ",Date,Team,Acquired,Relinquished,Notes\n"
        "0,2012-01-05,Heat,,A Player,death in family\n"
        "1,2012-01-06,Heat,,B Player,sprained left ankle (DNP)\n"
        "2,2012-01-07,Heat,,C Coach,head coach heart procedure\n"
        "3,2012-01-08,Heat,,D Player,flu (DNP)\n"
    )
    rows = parse_rows(_reader(text), source="t")
    assert [r["player"] for r in rows] == ["A Player", "B Player", "D Player"]
    assert rows[0]["category"] == "personal" and rows[0]["notes"] == ""
    assert rows[1]["notes"] == "sprained left ankle (DNP)"
    assert rows[2]["category"] == "illness" and rows[2]["notes"] == ""
