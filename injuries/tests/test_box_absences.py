import sqlite3

import pytest

from injuries.box_absences import ABSENCE_SQL, PLAYED_SQL, build, classify_rows, season_summary


def test_classify_rows_shapes_output():
    rows = [("001", "2015-01-10", "2014-15", 1, 10, "Amar'e Stoudemire", "DND - Sore Right Knee")]
    out = classify_rows(rows)
    assert out[0]["category"] == "injury"
    assert out[0]["location"] == "knee"
    assert out[0]["side"] == "right"
    assert out[0]["below_knee"] == 0
    assert out[0]["comment"] == "DND - Sore Right Knee"


def test_season_summary_counts_and_rate():
    absences = classify_rows(
        [
            ("001", "2015-01-10", "2014-15", 1, 10, "A", "DND - Sprained Left Ankle"),
            ("001", "2015-01-10", "2014-15", 1, 11, "B", "DNP - Coach's Decision"),
            ("002", "2015-01-11", "2014-15", 2, 12, "C", "DNP - Injury/Illness"),
            ("002", "2015-01-11", "2014-15", 2, 13, "D", "DND - Flu"),
        ]
    )
    summary = season_summary(absences, {"2014-15": (40, 2)})
    row = summary[0]
    assert row["games"] == 2 and row["team_games"] == 4
    assert row["absences_total"] == 4
    assert row["abs_injury"] == 1 and row["abs_coach"] == 1
    assert row["injury_below_knee"] == 1
    assert row["health_absences"] == 3
    assert row["health_absences_per_team_game"] == 0.75


def test_season_summary_refuses_inconsistent_db():
    absences = classify_rows([("001", "2015-01-10", "2014-15", 1, 10, "A", "DND - Flu")])
    with pytest.raises(ValueError):
        season_summary(absences, {})


def test_build_against_fixture_db(tmp_path):
    db = tmp_path / "fixture.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE games (game_id TEXT, date TEXT, season TEXT);
        CREATE TABLE players (person_id INTEGER, first_name TEXT, family_name TEXT);
        CREATE TABLE player_boxscores (game_id TEXT, person_id INTEGER, team_id INTEGER, minutes TEXT, comment TEXT);
        INSERT INTO games VALUES ('g1', '2016-11-01', '2016-17');
        INSERT INTO players VALUES (1, 'Ann', 'Able'), (2, 'Bob', 'Baker'), (3, 'Cy', 'Cole');
        INSERT INTO player_boxscores VALUES ('g1', 1, 100, '30:00', ' ');
        INSERT INTO player_boxscores VALUES ('g1', 2, 100, '', 'DND - Sprained Right Ankle');
        INSERT INTO player_boxscores VALUES ('g1', 3, 200, '', 'DNP - Coach''s Decision');
        """
    )
    con.commit()
    con.close()
    absences, summary = build(db)
    assert [a["player"] for a in absences] == ["Bob Baker"]  # coach rows dropped
    assert summary[0]["player_games_played"] == 1
    assert summary[0]["abs_coach"] == 1
    assert summary[0]["abs_injury"] == 1


def test_sql_selects_only_non_playing_rows():
    assert "minutes IS NULL OR TRIM(b.minutes) = ''" in ABSENCE_SQL
    assert "TRIM(b.minutes) != ''" in PLAYED_SQL


def test_non_injury_comments_are_blanked():
    rows = classify_rows(
        [
            ("001", "2015-01-10", "2014-15", 1, 10, "A", "NWT - Death In Family"),
            ("001", "2015-01-10", "2014-15", 1, 11, "B", "DND - Flu"),
            ("001", "2015-01-10", "2014-15", 1, 12, "C", "DND - Sore Right Knee"),
        ]
    )
    assert [r["comment"] for r in rows] == ["", "", "DND - Sore Right Knee"]
    assert [r["category"] for r in rows] == ["personal", "illness", "injury"]
