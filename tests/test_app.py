"""UI smoke tests using Streamlit's headless AppTest (no browser needed)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ERECHNUNG_DB", str(tmp_path / "ui.db"))
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_create_invoice_shows_totals_and_no_errors(app):
    button(app, "XRechnung erzeugen").click().run()
    assert not app.exception
    assert [m.value for m in app.metric[:3]] == ["1.739,30 €", "322,10 €", "2.061,40 €"]
    assert "Alles in Ordnung" in " ".join(m.value for m in app.markdown)


def test_missing_buyer_reference_blocks_download(app):
    next(t for t in app.text_input if t.label.startswith("Leitweg")).set_value("").run()
    button(app, "XRechnung erzeugen").click().run()
    assert "BR-DE-15" in " ".join(m.value for m in app.markdown)
    assert not [b for b in app.get("download_button")]  # no download for an invalid invoice


def test_broken_sample_is_reported(app):
    button(app, "Fehlerhaftes Beispiel").click().run()
    text = " ".join(m.value for m in app.markdown)
    assert all(rule in text for rule in ("BR-DE-15", "IBAN", "BR-CO-16"))


def test_overview_demo_data(app):
    button(app, "Demo-Daten laden").click().run()
    assert not app.exception
    assert app.metric[0].value == "14"


def test_valid_invoice_is_archived_and_number_advances(app):
    button(app, "XRechnung erzeugen").click().run()
    number = next(t for t in app.text_input if t.label == "Rechnungsnummer")
    assert number.value == "RE-" + str(__import__("datetime").date.today().year) + "-0002"


def test_invalid_invoice_is_not_archived_and_number_stays(app):
    next(t for t in app.text_input if t.label.startswith("Leitweg")).set_value("").run()
    button(app, "XRechnung erzeugen").click().run()
    number = next(t for t in app.text_input if t.label == "Rechnungsnummer")
    assert number.value.endswith("-0001")
    assert "Noch keine Rechnungen" in " ".join(i.value for i in app.info)
