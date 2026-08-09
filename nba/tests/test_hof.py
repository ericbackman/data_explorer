"""Tests for nba.hof_scrape — parsing, name normalization, resolution.

No network and no real DB: the parser gets literal rendered-table HTML and the
resolver gets plain dicts, so every rule that could silently mis-attribute a
Hall of Fame induction is pinned here.
"""

from __future__ import annotations

import pytest

from nba import db, hof_scrape


# ── normalize_name ───────────────────────────────────────────────────────────
def test_normalize_folds_diacritics():
    assert hof_scrape.normalize_name("Manu Ginóbili") == "manuginobili"
    assert hof_scrape.normalize_name("Toni Kukoč") == "tonikukoc"
    assert hof_scrape.normalize_name("Šarūnas Marčiulionis") == "sarunasmarciulionis"


def test_normalize_transliterates_stroke_letters_nfkd_cannot():
    """d-with-stroke carries no combining mark, so NFKD alone leaves it intact.
    Wikipedia's "Dino Rada" must still meet nba_api's "Dino Radja"."""
    assert hof_scrape.normalize_name("Dino Rađa") == hof_scrape.normalize_name("Dino Radja")


def test_normalize_ignores_spacing_and_punctuation():
    assert hof_scrape.normalize_name("Jo Jo White") == hof_scrape.normalize_name("Jojo White")
    assert hof_scrape.normalize_name("Amar'e Stoudemire") == "amarestoudemire"


def test_normalize_drops_parenthetical_disambiguator():
    assert (hof_scrape.normalize_name("Chris Mullin (basketball)")
            == hof_scrape.normalize_name("Chris Mullin"))


def test_normalize_keeps_generational_suffixes_distinct():
    """Stripping suffixes would collapse a father into his son and manufacture
    an ambiguity the source never had."""
    assert hof_scrape.normalize_name("Patrick Ewing") != hof_scrape.normalize_name("Patrick Ewing Jr.")
    assert hof_scrape.normalize_name("Gary Payton") != hof_scrape.normalize_name("Gary Payton II")
    assert hof_scrape.normalize_name("Tim Hardaway") != hof_scrape.normalize_name("Tim Hardaway Jr.")


def test_normalize_applies_verified_alias():
    assert (hof_scrape.normalize_name("Louie Dampier")
            == hof_scrape.normalize_name("Lou Dampier"))


def test_neil_johnston_is_not_aliased_to_nate_johnston():
    """nba_api hangs the 1990 induction on Nate Johnston (24 games) instead of
    Neil Johnston (543 games, 1951-59). They are different people."""
    assert (hof_scrape.normalize_name("Neil Johnston")
            != hof_scrape.normalize_name("Nate Johnston"))


# ── parse_inductees ──────────────────────────────────────────────────────────
def _row(year: str, inner: str) -> str:
    return f"<tr><td>{year}</td><td>{inner}</td><td>G</td><td>stuff</td></tr>"


HCARD = ('<span class="flagicon"><img alt="United States"/></span> '
         '<span data-sort-value="Bryant, Kobe"><span class="vcard"><span class="fn">'
         '<a href="/wiki/Kobe_Bryant" title="Kobe Bryant">Kobe Bryant</a>'
         '</span></span></span>')


def test_parse_reads_year_and_name_from_hcard():
    html = f'<table class="wikitable">{_row("2020", HCARD)}</table>'
    assert hof_scrape.parse_inductees(html) == [
        {"inducted_year": 2020, "name": "Kobe Bryant"}]


def test_parse_skips_header_and_layout_rows():
    html = ('<table class="wikitable">'
            '<tr><th>Year</th><th>Inductees</th></tr>'
            '<tr><td colspan="2">a note</td></tr>'
            f'{_row("2020", HCARD)}</table>')
    assert len(hof_scrape.parse_inductees(html)) == 1


def test_parse_keeps_every_class_including_the_newest():
    """The wikitext parser this replaced dropped the 2025 and 2026 classes
    outright because they use a different cell-delimiter style."""
    rows = [_row("2023", HCARD.replace("Kobe Bryant", "Dirk Nowitzki")),
            _row("2025", HCARD.replace("Kobe Bryant", "Carmelo Anthony")),
            _row("2026", HCARD.replace("Kobe Bryant", "Amar'e Stoudemire"))]
    got = hof_scrape.parse_inductees(f'<table class="wikitable">{"".join(rows)}</table>')
    assert [r["inducted_year"] for r in got] == [2023, 2025, 2026]


def test_parse_raises_when_table_yields_nothing():
    """A markup change must fail loudly, never load an empty Hall of Fame."""
    with pytest.raises(hof_scrape.HOFScrapeError):
        hof_scrape.parse_inductees("<table class='wikitable'><tr><th>Year</th></tr></table>")


# ── resolve_inductees ────────────────────────────────────────────────────────
def test_resolve_matches_unique_name():
    idx = hof_scrape.build_name_index([(977, "Kobe Bryant"), (1495, "Tim Duncan")])
    rows, unresolved = hof_scrape.resolve_inductees(
        [{"inducted_year": 2020, "name": "Kobe Bryant"}], idx, {}, overrides={})
    assert rows == [{"inductee_name": "Kobe Bryant", "inducted_year": 2020,
                     "player_id": 977}]
    assert unresolved == []


def test_resolve_keeps_non_nba_inductee_with_null_player_id():
    """WNBA inductees and Globetrotters stay in the table, unmatched — the row
    is the source fact; the NULL is what consumers filter on."""
    rows, unresolved = hof_scrape.resolve_inductees(
        [{"inducted_year": 2025, "name": "Sue Bird"}],
        hof_scrape.build_name_index([(977, "Kobe Bryant")]), {}, overrides={})
    assert rows[0]["player_id"] is None
    assert unresolved[0]["reason"] == "no NBA player of this name"


def test_resolve_uses_career_window_to_separate_same_name_players():
    """Gary Payton II was still active when Gary Payton was inducted (2013)."""
    idx = hof_scrape.build_name_index([(56, "Gary Payton")])
    idx["garypayton"] = [56, 1627780]                    # force the collision
    rows, unresolved = hof_scrape.resolve_inductees(
        [{"inducted_year": 2013, "name": "Gary Payton"}],
        idx, last_season={56: 2006, 1627780: 2023}, overrides={})
    assert rows[0]["player_id"] == 56
    assert unresolved == []


def test_resolve_refuses_to_guess_when_both_careers_predate_induction():
    """Two retired Bobby Joneses: no rule separates them, so nothing is invented."""
    idx = {"bobbyjones": [77193, 200784]}
    rows, unresolved = hof_scrape.resolve_inductees(
        [{"inducted_year": 2019, "name": "Bobby Jones"}],
        idx, last_season={77193: 1985, 200784: 2007}, overrides={})
    assert rows[0]["player_id"] is None
    assert unresolved[0]["reason"].startswith("ambiguous")


def test_resolve_applies_explicit_override_for_that_case():
    idx = {"bobbyjones": [77193, 200784]}
    rows, unresolved = hof_scrape.resolve_inductees(
        [{"inducted_year": 2019, "name": "Bobby Jones"}],
        idx, last_season={77193: 1985, 200784: 2007},
        overrides={(2019, "bobbyjones"): 77193})
    assert rows[0]["player_id"] == 77193
    assert unresolved == []


def test_shipped_overrides_cover_the_known_bobby_jones_collision():
    assert hof_scrape._AMBIGUITY_OVERRIDES[(2019, "bobbyjones")] == 77193


# ── validate_against_awards ──────────────────────────────────────────────────
def test_validation_counts_agreement_on_shared_players():
    rows = [{"inductee_name": "Ray Allen", "inducted_year": 2018, "player_id": 951}]
    agreements, problems = hof_scrape.validate_against_awards(rows, {951: "2018"})
    assert (agreements, problems) == (1, [])


def test_validation_flags_year_disagreement():
    rows = [{"inductee_name": "Ray Allen", "inducted_year": 2011, "player_id": 951}]
    agreements, problems = hof_scrape.validate_against_awards(rows, {951: "2018"})
    assert agreements == 0 and len(problems) == 1


def test_validation_ignores_players_nba_api_lacks():
    """The 2019+ classes are exactly what nba_api is missing — their absence is
    the point of this scraper, not a validation failure."""
    rows = [{"inductee_name": "Kobe Bryant", "inducted_year": 2020, "player_id": 977}]
    agreements, problems = hof_scrape.validate_against_awards(rows, {951: "2018"})
    assert (agreements, problems) == (0, [])


# ── loader safety ────────────────────────────────────────────────────────────
def test_load_hall_of_fame_refuses_to_wipe_table_with_empty_parse():
    conn = db.connect(":memory:")
    db.load_hall_of_fame(conn, [
        {"inductee_name": "Kobe Bryant", "inducted_year": 2020, "player_id": 977}])
    with pytest.raises(ValueError):
        db.load_hall_of_fame(conn, [])
    assert conn.execute("SELECT COUNT(*) FROM hall_of_fame").fetchone()[0] == 1
    conn.close()


def test_load_hall_of_fame_replaces_whole_snapshot():
    conn = db.connect(":memory:")
    db.load_hall_of_fame(conn, [
        {"inductee_name": "Typo Name", "inducted_year": 2020, "player_id": None}])
    db.load_hall_of_fame(conn, [
        {"inductee_name": "Kobe Bryant", "inducted_year": 2020, "player_id": 977}])
    assert conn.execute("SELECT inductee_name FROM hall_of_fame").fetchall() == [
        ("Kobe Bryant",)]
    conn.close()
