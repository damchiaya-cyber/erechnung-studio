"""Turn an Invoice into an XRechnung 3.0 file (UBL 2.1 syntax)."""
import xml.etree.ElementTree as ET
from decimal import Decimal

from .models import Invoice, Party, vat_category

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
CUSTOMIZATION_ID = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
PROFILE_ID = "urn:fdc:peppol.eu:2017:poid:billing:01:1.0"

for prefix, uri in (("", NS["inv"]), ("cac", NS["cac"]), ("cbc", NS["cbc"])):
    ET.register_namespace(prefix, uri)


def _add(parent: ET.Element, tag: str, text=None, **attrs) -> ET.Element:
    """Append a child like 'cbc:ID' to parent. Tag prefix is resolved via NS."""
    prefix, name = tag.split(":")
    child = ET.SubElement(parent, f"{{{NS[prefix]}}}{name}", attrs)
    if text is not None:
        child.text = str(text)
    return child


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _quantity(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _add_party(parent: ET.Element, tag: str, party: Party, is_seller: bool) -> None:
    """Write a seller or buyer block. Element order follows the UBL schema."""
    wrapper = _add(parent, tag)
    p = _add(wrapper, "cac:Party")
    if party.email:
        _add(p, "cbc:EndpointID", party.email, schemeID="EM")
    _add(_add(p, "cac:PartyName"), "cbc:Name", party.name)
    address = _add(p, "cac:PostalAddress")
    _add(address, "cbc:StreetName", party.street)
    _add(address, "cbc:CityName", party.city)
    _add(address, "cbc:PostalZone", party.postal_code)
    _add(_add(address, "cac:Country"), "cbc:IdentificationCode", party.country)
    if party.vat_id:
        tax = _add(p, "cac:PartyTaxScheme")
        _add(tax, "cbc:CompanyID", party.vat_id)
        _add(_add(tax, "cac:TaxScheme"), "cbc:ID", "VAT")
    _add(_add(p, "cac:PartyLegalEntity"), "cbc:RegistrationName", party.name)
    if is_seller:  # XRechnung rule BR-DE-2: seller contact is mandatory
        contact = _add(p, "cac:Contact")
        _add(contact, "cbc:Name", party.contact_name)
        _add(contact, "cbc:Telephone", party.phone)
        _add(contact, "cbc:ElectronicMail", party.email)


def build_xrechnung(invoice: Invoice) -> bytes:
    """Return the invoice as UTF-8 encoded XRechnung XML."""
    root = ET.Element(f"{{{NS['inv']}}}Invoice")
    cur = invoice.currency

    _add(root, "cbc:CustomizationID", CUSTOMIZATION_ID)
    _add(root, "cbc:ProfileID", PROFILE_ID)
    _add(root, "cbc:ID", invoice.number)
    _add(root, "cbc:IssueDate", invoice.issue_date.isoformat())
    _add(root, "cbc:DueDate", invoice.due_date.isoformat())
    _add(root, "cbc:InvoiceTypeCode", "380")  # 380 = commercial invoice
    _add(root, "cbc:DocumentCurrencyCode", cur)
    _add(root, "cbc:BuyerReference", invoice.buyer_reference)

    _add_party(root, "cac:AccountingSupplierParty", invoice.seller, is_seller=True)
    _add_party(root, "cac:AccountingCustomerParty", invoice.buyer, is_seller=False)

    payment = _add(root, "cac:PaymentMeans")
    _add(payment, "cbc:PaymentMeansCode", "58")  # 58 = SEPA credit transfer
    _add(_add(payment, "cac:PayeeFinancialAccount"), "cbc:ID", invoice.iban.replace(" ", ""))
    if invoice.payment_note:
        _add(_add(root, "cac:PaymentTerms"), "cbc:Note", invoice.payment_note)

    tax_total = _add(root, "cac:TaxTotal")
    _add(tax_total, "cbc:TaxAmount", _amount(invoice.vat_total), currencyID=cur)
    for rate, (taxable, vat) in invoice.vat_breakdown().items():
        sub = _add(tax_total, "cac:TaxSubtotal")
        _add(sub, "cbc:TaxableAmount", _amount(taxable), currencyID=cur)
        _add(sub, "cbc:TaxAmount", _amount(vat), currencyID=cur)
        category = _add(sub, "cac:TaxCategory")
        _add(category, "cbc:ID", vat_category(rate))
        _add(category, "cbc:Percent", _quantity(rate))
        _add(_add(category, "cac:TaxScheme"), "cbc:ID", "VAT")

    totals = _add(root, "cac:LegalMonetaryTotal")
    _add(totals, "cbc:LineExtensionAmount", _amount(invoice.net_total), currencyID=cur)
    _add(totals, "cbc:TaxExclusiveAmount", _amount(invoice.net_total), currencyID=cur)
    _add(totals, "cbc:TaxInclusiveAmount", _amount(invoice.gross_total), currencyID=cur)
    _add(totals, "cbc:PayableAmount", _amount(invoice.gross_total), currencyID=cur)

    for position, line in enumerate(invoice.lines, start=1):
        node = _add(root, "cac:InvoiceLine")
        _add(node, "cbc:ID", position)
        _add(node, "cbc:InvoicedQuantity", _quantity(line.quantity), unitCode=line.unit_code)
        _add(node, "cbc:LineExtensionAmount", _amount(line.net_amount), currencyID=cur)
        item = _add(node, "cac:Item")
        _add(item, "cbc:Name", line.description)
        category = _add(item, "cac:ClassifiedTaxCategory")
        _add(category, "cbc:ID", vat_category(line.vat_rate))
        _add(category, "cbc:Percent", _quantity(line.vat_rate))
        _add(_add(category, "cac:TaxScheme"), "cbc:ID", "VAT")
        _add(_add(node, "cac:Price"), "cbc:PriceAmount", f"{line.unit_price:.2f}", currencyID=cur)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
