"""Tests for injuries/injury_reports.py.

Row assertions were checked by hand against the text of each fixture PDF
(tests/fixtures/), one fixture per layout generation:
  2018-12-27  Category and Reason as separate columns, Previous Status column
  2019-10-25  same family, Reason wraps above and below the player line
  2024-03-15  Reason last, spaces missing from the PDF text layer
  2026-01-15  newest file-name family (_05_30PM), ten pages
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import injury_reports as ir  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def parse(name: str, day: dt.date, slot: str):
    # The fixture PDFs are NBA-published documents and stay out of the public repo
    # (legal review 2026-11-05). Fetch them with `python -m injuries.injury_reports`
    # (they land in injuries/.cache/reports/) and copy the five named files here.
    path = FIX / name
    if not path.exists():
        pytest.skip(f"fixture {name} not present locally; see the comment in parse()")
    return ir.parse_pdf(path, day, slot)


def find(rows, player):
    hits = [r for r in rows if r["player"] == player]
    assert len(hits) == 1, f"{player}: {len(hits)} rows"
    return hits[0]


# ---- hand-validated rows -------------------------------------------------

def test_2024_wrapped_reason_and_blank_cells():
    rows = parse("Injury-Report_2024-03-15_05PM.pdf", dt.date(2024, 3, 15), "05PM")
    # PDF text: "Injury/Illness-RightFoot;Medial" / "Herro,Tyler Out" / "Tendinitis"
    r = find(rows, "Herro, Tyler")
    assert (r["game_date"], r["game_time"], r["matchup"], r["team"]) == (
        "2024-03-15", "19:00", "MIA@DET", "Miami Heat")
    assert r["status"] == "Out"
    assert r["reason"] == "Injury/Illness - Right Foot; Medial Tendinitis"
    # Date, matchup and team are blank on this row and carry forward.
    r = find(rows, "Cunningham, Cade")
    assert (r["matchup"], r["team"], r["status"]) == ("MIA@DET", "Detroit Pistons", "Questionable")
    assert r["reason"] == "Injury/Illness - Left Knee; Injury Management"


def test_2018_category_reason_layout():
    rows = parse("Injury-Report_2018-12-27_05PM.pdf", dt.date(2018, 12, 27), "05PM")
    # PDF text: "Left Fourth Metacarpal" / "Baynes, Aron Injury/Illness Out -" / "Fracture"
    r = find(rows, "Baynes, Aron")
    assert (r["game_date"], r["game_time"], r["matchup"], r["team"]) == (
        "2018-12-27", "20:00", "BOS@HOU", "Boston Celtics")
    assert r["status"] == "Out"
    assert r["reason"] == "Injury/Illness - Left Fourth Metacarpal Fracture"
    # A game on the next calendar day, and a Category with no Reason text.
    r = find(rows, "Bonga, Isaac")
    assert (r["game_date"], r["team"], r["reason"]) == ("2018-12-27", "Los Angeles Lakers", "G League Team")
    r = find(rows, "Crabbe, Allen")
    assert (r["game_date"], r["game_time"], r["matchup"]) == ("2018-12-28", "19:00", "BKN@CHA")


def test_2019_team_marker_rows_are_dropped_and_context_carries():
    rows = parse("Injury-Report_2019-10-25_05PM.pdf", dt.date(2019, 10, 25), "05PM")
    # PDF text: "07:30 (ET) NYK@BKN Brooklyn Nets Chandler, Wilson League Suspension - Out -"
    r = find(rows, "Durant, Kevin")
    assert (r["game_time"], r["matchup"], r["team"]) == ("19:30", "NYK@BKN", "Brooklyn Nets")
    assert (r["status"], r["reason"]) == ("Out", "Injury/Illness - Right Achilles")
    # "Milwaukee Bucks  NOT YET SUBMITTED" is a team marker, not a player.
    assert not [r for r in rows if r["team"] == "Milwaukee Bucks"]
    assert all(r["player"] for r in rows)


def test_2026_new_filename_family():
    rows = parse("Injury-Report_2026-01-15_05_30PM.pdf", dt.date(2026, 1, 15), "05_30PM")
    r = find(rows, "Edey, Zach")
    assert (r["matchup"], r["team"], r["status"]) == ("MEM@ORL", "Memphis Grizzlies", "Out")
    assert r["reason"] == "Injury/Illness - Left Ankle; Stress Reaction"
    assert len(rows) == 151


# ---- pure functions ------------------------------------------------------

def raw(date=None, time=None, matchup=None, team=None, player="X", marker=False):
    return {"game_date": date, "game_time": time, "matchup": matchup, "team": team,
            "player": player, "status": "Out", "reason": "Rest", "marker": marker}


def test_carry_forward_fills_blanks_from_the_row_above():
    out = ir.carry_forward([
        raw("01/15/2026", "07:00 (ET)", "A@B", "Team A", "P1"),
        raw(player="P2"),
        raw(team="Team B", player="P3"),
        raw("01/16/2026", "08:00 (ET)", "C@D", "Team C", "P4"),
    ])
    assert [(r["player"], r["game_date"], r["matchup"], r["team"]) for r in out] == [
        ("P1", "01/15/2026", "A@B", "Team A"),
        ("P2", "01/15/2026", "A@B", "Team A"),
        ("P3", "01/15/2026", "A@B", "Team B"),
        ("P4", "01/16/2026", "C@D", "Team C"),
    ]


def test_carry_forward_context_only_row_feeds_the_next_page():
    ctx_only = {"game_date": None, "game_time": None, "matchup": "A@B", "team": "Team B",
                "player": None, "status": None, "reason": None, "marker": None}
    out = ir.carry_forward([raw("01/15/2026", "07:00 (ET)", "A@B", "Team A", "P1"), ctx_only, raw(player="P2")])
    assert [r["player"] for r in out] == ["P1", "P2"]
    assert out[1]["team"] == "Team B"


def test_carry_forward_refuses_to_invent_a_value():
    with pytest.raises(ir.ParseError, match="carry forward"):
        ir.carry_forward([raw(player="P1")])


def test_check_team_matchup_catches_a_carry_forward_slip():
    ir.check_team_matchup("Miami Heat", "MIA@DET")
    with pytest.raises(ir.ParseError):
        ir.check_team_matchup("Miami Heat", "DET@PHX")
    with pytest.raises(ir.ParseError, match="unknown team"):
        ir.check_team_matchup("Minnesota", "MIN@DEN")


def test_game_time_and_date():
    assert ir.parse_game_time("07:30 (ET)") == "19:30"
    assert ir.parse_game_time("12:30 (ET)") == "12:30"
    assert ir.parse_game_time("02:00 (ET)") == "14:00"
    assert ir.parse_game_date("03/15/2024") == "2024-03-15"
    with pytest.raises(ir.ParseError):
        ir.parse_game_time("7pm")


def test_join_category_reason():
    assert ir.join_category_reason("Injury/Illness", "Left Knee") == "Injury/Illness - Left Knee"
    assert ir.join_category_reason("Personal Reasons", "-") == "Personal Reasons"
    assert ir.join_category_reason("", "Rest") == "Rest"


def test_slots_and_seasons():
    assert ir.slots_for(dt.date(2024, 3, 15))[0] == "05PM"
    assert ir.slots_for(dt.date(2026, 1, 15))[0] == "05_30PM"
    assert "05PM" in ir.slots_for(dt.date(2025, 12, 20))
    assert ir.season_of(dt.date(2019, 7, 1)) == "2018-19"
    assert ir.season_of(dt.date(2019, 10, 22)) == "2019-20"


def test_build_coverage_flags_failures():
    d1, d2, d3 = dt.date(2019, 10, 25), dt.date(2019, 10, 26), dt.date(2019, 10, 27)
    cov = ir.build_coverage({d1: "05PM", d2: "05PM", d3: None}, {d1: 10}, {d2: "boom"})
    assert cov == [{"season": "2019-20", "days_probed": 3, "days_with_report": 2, "rows_parsed": 10,
                    "first_report_date": "2019-10-25", "last_report_date": "2019-10-26",
                    "parse_failures": 1, "failed_dates": "2019-10-26"}]


class FakeResp:
    def __init__(self, status, body=b""):
        self.status_code, self.content = status, body


class FakeSession:
    def __init__(self, script):
        self.script, self.calls, self.headers = list(script), [], {}

    def get(self, url, timeout):
        assert timeout
        self.calls.append(url)
        return self.script.pop(0)


def test_fetcher_caches_pdfs_and_403s_and_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(ir, "CACHE_DIR", tmp_path / "reports")
    monkeypatch.setattr(ir, "PROBE_CACHE", tmp_path / "probe.json")
    monkeypatch.setattr(ir, "MIN_REQUEST_GAP_S", 0)
    day = dt.date(2024, 3, 15)
    sess = FakeSession([FakeResp(403), FakeResp(503), FakeResp(200, b"%PDF-1.4 x")])
    f = ir.Fetcher(sess, sleep=lambda s: None)
    assert f.fetch_date(day) == "01PM"  # 05PM 403, 01PM 503 then 200
    f.save_misses()
    assert len(sess.calls) == 3
    # Second run: everything comes from disk, no network.
    sess2 = FakeSession([])
    f2 = ir.Fetcher(sess2, sleep=lambda s: None)
    assert f2.fetch_date(day) == "01PM"
    assert sess2.calls == []
    assert f2.misses == {"2024-03-15_05PM": 403}


def test_fetcher_raises_on_unexpected_status(tmp_path, monkeypatch):
    monkeypatch.setattr(ir, "CACHE_DIR", tmp_path / "reports")
    monkeypatch.setattr(ir, "PROBE_CACHE", tmp_path / "probe.json")
    monkeypatch.setattr(ir, "MIN_REQUEST_GAP_S", 0)
    f = ir.Fetcher(FakeSession([FakeResp(404)]), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="404"):
        f.fetch_date(dt.date(2024, 3, 15))


def test_fetcher_gives_up_after_repeated_5xx(tmp_path, monkeypatch):
    monkeypatch.setattr(ir, "CACHE_DIR", tmp_path / "reports")
    monkeypatch.setattr(ir, "PROBE_CACHE", tmp_path / "probe.json")
    monkeypatch.setattr(ir, "MIN_REQUEST_GAP_S", 0)
    f = ir.Fetcher(FakeSession([FakeResp(500)] * ir.MAX_ATTEMPTS), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="giving up"):
        f.fetch_date(dt.date(2024, 3, 15))


def test_carry_forward_appends_reason_that_wrapped_onto_the_next_page():
    cont = {"game_date": None, "game_time": None, "matchup": None, "team": None,
            "player": None, "status": None, "reason": "Tendinitis", "marker": "continuation"}
    out = ir.carry_forward([raw("01/15/2026", "07:00 (ET)", "A@B", "Team A", "P1"), cont, raw(player="P2")])
    assert [r["player"] for r in out] == ["P1", "P2"]
    assert out[0]["reason"] == "Rest Tendinitis"
    with pytest.raises(ir.ParseError, match="continuation"):
        ir.carry_forward([cont])
