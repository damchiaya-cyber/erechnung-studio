"""Read and check an incoming XRechnung (UBL) file.

This is a plausibility check for the most important EN 16931 / XRechnung
rules (rule IDs like BR-CO-15 are kept so findings are easy to look up).
It is NOT a replacement for the official KoSIT validator.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .builder import NS
from .models import money

ERROR, WARNING = "Fehler", "Warnung"


@dataclass
class Finding:
    rule: str
    severity: str  # ERROR or WARNING
    message: str   # German, shown to the user


def iban_is_valid(iban: str) -> bool:
    """ISO 13616 check: move first 4 chars to the end, letters -> numbers, mod 97 == 1."""
    iban = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _text(node: ET.Element | None, path: str) -> str:
    """Text of the first element at 'path' below node ('' if missing)."""
    if node is None:
        return ""
    found = node.find(path, NS)
    return (found.text or "").strip() if found is not None else ""


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _party(root: ET.Element, tag: str) -> dict:
    party = root.find(f"cac:{tag}/cac:Party", NS)
    return {
        "name": _text(party, "cac:PartyLegalEntity/cbc:RegistrationName") or _text(party, "cac:PartyName/cbc:Name"),
        "street": _text(party, "cac:PostalAddress/cbc:StreetName"),
        "postal_code": _text(party, "cac:PostalAddress/cbc:PostalZone"),
        "city": _text(party, "cac:PostalAddress/cbc:CityName"),
        "country": _text(party, "cac:PostalAddress/cac:Country/cbc:IdentificationCode"),
        "vat_id": _text(party, "cac:PartyTaxScheme/cbc:CompanyID"),
        "identifier": _text(party, "cac:PartyIdentification/cbc:ID"),
        "legal_id": _text(party, "cac:PartyLegalEntity/cbc:CompanyID"),
        "contact_name": _text(party, "cac:Contact/cbc:Name"),
        "phone": _text(party, "cac:Contact/cbc:Telephone"),
        "email": _text(party, "cac:Contact/cbc:ElectronicMail"),
        "has_contact": party is not None and party.find("cac:Contact", NS) is not None,
    }


def parse_invoice(xml_bytes: bytes) -> dict:
    """Extract the fields we care about into a plain dict (raises ET.ParseError)."""
    root = ET.fromstring(xml_bytes)
    if root.tag != f"{{{NS['inv']}}}Invoice":
        raise ValueError("Keine UBL-Rechnung (Wurzelelement <Invoice> fehlt). CII-Dateien werden noch nicht unterstützt.")

    lines = []
    for node in root.findall("cac:InvoiceLine", NS):
        quantity = node.find("cbc:InvoicedQuantity", NS)
        lines.append({
            "id": _text(node, "cbc:ID"),
            "name": _text(node, "cac:Item/cbc:Name"),
            "quantity": _text(node, "cbc:InvoicedQuantity"),
            "unit": quantity.get("unitCode", "") if quantity is not None else "",
            "price": _text(node, "cac:Price/cbc:PriceAmount"),
            "net": _text(node, "cbc:LineExtensionAmount"),
            "vat_rate": _text(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
        })

    subtotals = [{
        "taxable": _text(sub, "cbc:TaxableAmount"),
        "vat": _text(sub, "cbc:TaxAmount"),
        "rate": _text(sub, "cac:TaxCategory/cbc:Percent"),
    } for sub in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS)]

    return {
        "customization_id": _text(root, "cbc:CustomizationID"),
        "number": _text(root, "cbc:ID"),
        "issue_date": _text(root, "cbc:IssueDate"),
        "due_date": _text(root, "cbc:DueDate"),
        "type_code": _text(root, "cbc:InvoiceTypeCode"),
        "currency": _text(root, "cbc:DocumentCurrencyCode"),
        "buyer_reference": _text(root, "cbc:BuyerReference"),
        "seller": _party(root, "AccountingSupplierParty"),
        "buyer": _party(root, "AccountingCustomerParty"),
        "payment_code": _text(root, "cac:PaymentMeans/cbc:PaymentMeansCode"),
        "iban": _text(root, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID"),
        "lines": lines,
        "vat_subtotals": subtotals,
        "vat_total": _text(root, "cac:TaxTotal/cbc:TaxAmount"),
        "line_total": _text(root, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount"),
        "net_total": _text(root, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"),
        "gross_total": _text(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"),
        "payable": _text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount"),
    }


def validate_invoice(xml_bytes: bytes) -> tuple[dict | None, list[Finding]]:
    """Return (parsed invoice, findings). An empty findings list means 'all good'."""
    try:
        data = parse_invoice(xml_bytes)
    except ET.ParseError as exc:
        return None, [Finding("XML", ERROR, f"Die Datei ist kein gültiges XML: {exc}")]
    except ValueError as exc:
        return None, [Finding("FORMAT", ERROR, str(exc))]

    findings: list[Finding] = []

    def need(condition: bool, rule: str, message: str, severity: str = ERROR) -> None:
        if not condition:
            findings.append(Finding(rule, severity, message))

    # --- Mandatory header fields (EN 16931) -------------------------------
    need(bool(data["customization_id"]), "BR-01", "Die Spezifikationskennung (CustomizationID) fehlt.")
    need(data["customization_id"].startswith("urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3")
         or not data["customization_id"], "BR-DE-21",
         "Die Kennung verweist nicht auf XRechnung 3.x.", WARNING)
    need(bool(data["number"]), "BR-02", "Die Rechnungsnummer fehlt.")
    issue = _parse_date(data["issue_date"])
    need(issue is not None, "BR-03", "Das Rechnungsdatum fehlt oder ist kein gültiges Datum (JJJJ-MM-TT).")
    need(bool(data["type_code"]), "BR-04", "Der Rechnungstyp (InvoiceTypeCode) fehlt.")
    need(bool(data["currency"]), "BR-05", "Die Währung fehlt.")
    need(bool(data["seller"]["name"]), "BR-06", "Der Name des Verkäufers fehlt.")
    need(bool(data["buyer"]["name"]), "BR-07", "Der Name des Käufers fehlt.")
    need(len(data["lines"]) > 0, "BR-16", "Die Rechnung enthält keine Position.")

    seller = data["seller"]
    need(bool(seller["identifier"] or seller["legal_id"] or seller["vat_id"]), "BR-CO-26",
         "Der Verkäufer muss identifizierbar sein: USt-IdNr., Kennung oder Handelsregisternummer fehlt.")

    # --- German XRechnung extras ------------------------------------------
    need(bool(data["buyer_reference"]), "BR-DE-15", "Die Käuferreferenz (Leitweg-ID) fehlt.")
    need(bool(data["payment_code"]), "BR-DE-1", "Zahlungsinformationen (PaymentMeans) fehlen.")
    need(seller["has_contact"], "BR-DE-2", "Der Verkäufer benötigt eine Kontaktstelle (Ansprechpartner).")
    if seller["has_contact"]:
        need(bool(seller["contact_name"]), "BR-DE-5", "Der Name des Ansprechpartners fehlt.")
        need(bool(seller["phone"]), "BR-DE-6", "Die Telefonnummer des Ansprechpartners fehlt.")
        need(bool(seller["email"]), "BR-DE-7", "Die E-Mail-Adresse des Ansprechpartners fehlt.")

    # --- Plausibility ------------------------------------------------------
    if data["iban"]:
        need(iban_is_valid(data["iban"]), "IBAN", "Die IBAN hat eine ungültige Prüfsumme.")
    if seller["country"] == "DE" and seller["vat_id"]:
        need(re.fullmatch(r"DE\d{9}", seller["vat_id"]) is not None, "USt-IdNr",
             "Die USt-IdNr. des Verkäufers hat kein gültiges Format (DE + 9 Ziffern).", WARNING)
    due = _parse_date(data["due_date"])
    if issue and due:
        need(due >= issue, "FRIST", "Das Fälligkeitsdatum liegt vor dem Rechnungsdatum.", WARNING)

    _check_amounts(data, need)
    return data, findings


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _check_amounts(data: dict, need) -> None:
    """Cross-check every calculated amount against the values in the file."""
    def amount(value: str) -> Decimal | None:
        parsed = _decimal(value)
        return money(parsed) if parsed is not None else None

    # Line level: net = quantity x price
    line_nets = []
    for line in data["lines"]:
        qty, price, net = _decimal(line["quantity"]), amount(line["price"]), amount(line["net"])
        if qty is None or price is None or net is None:
            need(False, "BR-24", f"Position {line['id'] or '?'}: Menge, Preis oder Betrag fehlt oder ist keine Zahl.")
            continue
        need(money(qty * price) == net, "POSITION",
             f"Position {line['id']}: Nettobetrag {net} passt nicht zu Menge × Preis ({money(qty * price)}).")
        line_nets.append(net)

    line_total, net_total = amount(data["line_total"]), amount(data["net_total"])
    gross, vat_total, payable = amount(data["gross_total"]), amount(data["vat_total"]), amount(data["payable"])
    if None in (line_total, net_total, gross, vat_total, payable):
        need(False, "BR-CO-13", "Die Summenfelder (Netto, USt, Brutto, Zahlbetrag) sind unvollständig.")
        return

    need(sum(line_nets, Decimal("0")) == line_total, "BR-CO-10",
         "Die Summe der Positionsbeträge stimmt nicht mit dem Gesamt-Positionsbetrag überein.")
    need(net_total == line_total, "BR-CO-13", "Der Gesamtbetrag ohne USt weicht von der Positionssumme ab.")

    # VAT level: every rate group must be tax = taxable x rate, and add up to the total
    subtotal_vat = Decimal("0")
    for sub in data["vat_subtotals"]:
        taxable, vat, rate = amount(sub["taxable"]), amount(sub["vat"]), _decimal(sub["rate"])
        if taxable is None or vat is None or rate is None:
            need(False, "BR-CO-17", "Eine USt-Aufschlüsselung ist unvollständig.")
            continue
        need(money(taxable * rate / 100) == vat, "BR-CO-17",
             f"USt-Betrag {vat} passt nicht zu {taxable} × {rate} %.")
        subtotal_vat += vat
    need(subtotal_vat == vat_total, "BR-CO-14", "Die Summe der USt-Beträge stimmt nicht mit der Gesamt-USt überein.")

    need(net_total + vat_total == gross, "BR-CO-15", "Brutto ist nicht Netto + USt.")
    need(gross == payable, "BR-CO-16", "Der Zahlbetrag entspricht nicht dem Bruttobetrag.")
