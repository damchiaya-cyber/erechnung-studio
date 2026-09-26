"""Run with:  python -m pytest -q"""
from datetime import date
from decimal import Decimal

import pytest

from erechnung.archive import load_invoices, next_invoice_number, save_invoice
from erechnung.builder import build_xrechnung
from erechnung.demo import sample_invoice, seed_archive
from erechnung.models import LineItem, money
from erechnung.validator import iban_is_valid, validate_invoice


def rules(findings):
    return {f.rule for f in findings}


# --- calculation ---------------------------------------------------------
def test_money_rounds_half_up():
    assert money("2.675") == Decimal("2.68")
    assert money("0.004") == Decimal("0.00")


def test_totals_of_sample_invoice():
    invoice = sample_invoice()
    assert invoice.net_total == Decimal("1739.30")
    assert invoice.vat_breakdown() == {
        Decimal("7"): (Decimal("69.80"), Decimal("4.89")),
        Decimal("19"): (Decimal("1669.50"), Decimal("317.21")),
    }
    assert invoice.vat_total == Decimal("322.10")
    assert invoice.gross_total == Decimal("2061.40")


# --- builder + validator round trip -------------------------------------
def test_generated_invoice_is_valid():
    parsed, findings = validate_invoice(build_xrechnung(sample_invoice()))
    assert findings == []
    assert parsed["number"] == "RE-2026-0001"
    assert len(parsed["lines"]) == 3


def test_zero_vat_line_is_valid():
    invoice = sample_invoice()
    invoice.lines.append(LineItem("Steuerfreie Leistung", Decimal("1"), "C62", Decimal("10"), Decimal("0")))
    _, findings = validate_invoice(build_xrechnung(invoice))
    assert findings == []


@pytest.mark.parametrize("old, new, expected_rule", [
    (b"<cbc:BuyerReference>04011000-1234512345-06</cbc:BuyerReference>", b"", "BR-DE-15"),
    (b"<cbc:PayableAmount currencyID=\"EUR\">2061.40", b"<cbc:PayableAmount currencyID=\"EUR\">2000.00", "BR-CO-16"),
    (b"<cbc:TaxInclusiveAmount currencyID=\"EUR\">2061.40", b"<cbc:TaxInclusiveAmount currencyID=\"EUR\">2099.00", "BR-CO-15"),
    (b"DE89370400440532013000", b"DE89370400440532013001", "IBAN"),
    (b"<cbc:ID>RE-2026-0001</cbc:ID>", b"", "BR-02"),
    (b"<cbc:Telephone>+49 561 1234567</cbc:Telephone>", b"", "BR-DE-6"),
])
def test_validator_finds_tampering(old, new, expected_rule):
    xml = build_xrechnung(sample_invoice())
    assert old in xml, "test setup: pattern not found in generated XML"
    _, findings = validate_invoice(xml.replace(old, new, 1))
    assert expected_rule in rules(findings)


def test_seller_without_any_identifier_is_rejected():
    invoice = sample_invoice()
    invoice.seller.vat_id = ""
    _, findings = validate_invoice(build_xrechnung(invoice))
    assert rules(findings) == {"BR-CO-26"}


def test_special_characters_survive_roundtrip():
    invoice = sample_invoice()
    invoice.buyer.name = "Müller & Söhne <AG>"
    parsed, findings = validate_invoice(build_xrechnung(invoice))
    assert findings == [] and parsed["buyer"]["name"] == "Müller & Söhne <AG>"


def test_invoice_without_lines_is_rejected():
    invoice = sample_invoice()
    invoice.lines = []
    _, findings = validate_invoice(build_xrechnung(invoice))
    assert "BR-16" in rules(findings)


def test_validator_rejects_broken_and_foreign_files():
    parsed, findings = validate_invoice(b"<Invoice>")
    assert parsed is None and rules(findings) == {"XML"}
    parsed, findings = validate_invoice(b"<html></html>")
    assert parsed is None and rules(findings) == {"FORMAT"}


def test_iban_check():
    assert iban_is_valid("DE89 3704 0044 0532 0130 00")
    assert not iban_is_valid("DE89 3704 0044 0532 0130 01")
    assert not iban_is_valid("not an iban")


# --- archive ------------------------------------------------------------
def test_archive_save_update_and_numbering(tmp_path):
    db = str(tmp_path / "test.db")
    assert next_invoice_number(db, date(2027, 3, 1)) == "RE-2027-0001"
    invoice = sample_invoice("RE-2027-0001", date(2027, 3, 1))
    save_invoice(db, invoice)
    invoice.lines.pop()
    save_invoice(db, invoice)  # same number -> update, not duplicate
    table = load_invoices(db)
    assert len(table) == 1 and table.loc[0, "gross"] == float(invoice.gross_total)
    assert next_invoice_number(db, date(2027, 6, 1)) == "RE-2027-0002"


def test_demo_seed_creates_invoices(tmp_path):
    db = str(tmp_path / "demo.db")
    seed_archive(db, count=6)
    table = load_invoices(db)
    assert len(table) == 6
