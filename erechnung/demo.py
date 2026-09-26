"""Fictional example data (no real companies) for the form defaults and demo archive."""
import random
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from .archive import save_invoice
from .builder import build_xrechnung
from .models import Invoice, LineItem, Party

SELLER = Party(
    name="Beispiel IT-Service GmbH", street="Musterweg 12", postal_code="34117", city="Kassel",
    vat_id="DE123456789", email="rechnung@beispiel-it.example", contact_name="Aya Muster", phone="+49 561 1234567",
)
BUYER = Party(name="Stadtwerke Beispielstadt", street="Marktplatz 1", postal_code="20095", city="Hamburg")
IBAN = "DE89370400440532013000"  # public example IBAN with a valid checksum
BUYER_REFERENCE = "04011000-1234512345-06"


def sample_invoice(number: str = "RE-2026-0001", issue: date | None = None) -> Invoice:
    issue = issue or date.today()
    return Invoice(
        number=number, issue_date=issue, due_date=issue + timedelta(days=14),
        buyer_reference=BUYER_REFERENCE, seller=replace(SELLER), buyer=replace(BUYER), iban=IBAN,  # copies, so callers can edit safely
        payment_note="Zahlbar innerhalb von 14 Tagen ohne Abzug.",
        lines=[
            LineItem("Systemintegration: Anbindung ERP an Webshop", Decimal("16"), "HUR", Decimal("95.00"), Decimal("19")),
            LineItem("Wartungsvertrag Monitoring (Monat)", Decimal("1"), "C62", Decimal("149.50"), Decimal("19")),
            LineItem("Fachbuch Datenschutz in der Praxis", Decimal("2"), "C62", Decimal("34.90"), Decimal("7")),
        ],
    )


def seed_archive(db_path: str, count: int = 14) -> None:
    """Fill the archive with reproducible demo invoices spread over the last months."""
    rng = random.Random(42)
    today = date.today()
    for i in range(1, count + 1):
        issue = today - timedelta(days=rng.randint(0, 150))
        invoice = sample_invoice(f"DEMO-{i:04d}", issue)
        invoice.lines[0].quantity = Decimal(rng.randint(2, 40))
        invoice.lines[2].quantity = Decimal(rng.randint(0, 5))
        invoice.lines = [line for line in invoice.lines if line.quantity > 0]
        save_invoice(db_path, invoice)


def broken_sample_xml() -> bytes:
    """The sample invoice with three deliberate mistakes, to demonstrate the checker."""
    xml = build_xrechnung(sample_invoice())
    xml = xml.replace(f"<cbc:BuyerReference>{BUYER_REFERENCE}</cbc:BuyerReference>".encode(), b"")
    xml = xml.replace(IBAN.encode(), IBAN[:-1].encode() + b"1")
    return xml.replace(b'<cbc:PayableAmount currencyID="EUR">2061.40', b'<cbc:PayableAmount currencyID="EUR">2000.00')
