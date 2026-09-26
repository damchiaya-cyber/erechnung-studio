"""Plain data classes for an invoice and all money calculations.

Money is always handled with Decimal (never float) and rounded half-up to
cents, which is how EN 16931 / XRechnung expects amounts to be calculated.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def money(value) -> Decimal:
    """Round any number-like value to 2 decimals, half up."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def vat_category(rate: Decimal) -> str:
    """UNCL5305 VAT category: 'S' = standard/reduced rate, 'Z' = zero rate."""
    return "Z" if rate == 0 else "S"


@dataclass
class Party:
    name: str
    street: str
    postal_code: str
    city: str
    country: str = "DE"
    vat_id: str = ""        # USt-IdNr., e.g. DE123456789
    email: str = ""
    contact_name: str = ""  # XRechnung requires a seller contact
    phone: str = ""


@dataclass
class LineItem:
    description: str
    quantity: Decimal
    unit_code: str          # UN/ECE Rec. 20: C62 = piece, HUR = hour, DAY = day
    unit_price: Decimal     # net price per unit
    vat_rate: Decimal       # in percent, e.g. 19

    @property
    def net_amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)


@dataclass
class Invoice:
    number: str
    issue_date: date
    due_date: date
    buyer_reference: str    # Leitweg-ID for public bodies, else any reference
    seller: Party
    buyer: Party
    iban: str
    lines: list[LineItem] = field(default_factory=list)
    payment_note: str = ""
    currency: str = "EUR"

    @property
    def net_total(self) -> Decimal:
        return sum((line.net_amount for line in self.lines), Decimal("0.00"))

    def vat_breakdown(self) -> dict[Decimal, tuple[Decimal, Decimal]]:
        """Return {vat_rate: (taxable_amount, vat_amount)}, one entry per rate."""
        taxable: dict[Decimal, Decimal] = {}
        for line in self.lines:
            taxable[line.vat_rate] = taxable.get(line.vat_rate, Decimal("0.00")) + line.net_amount
        return {rate: (net, money(net * rate / 100)) for rate, net in sorted(taxable.items())}

    @property
    def vat_total(self) -> Decimal:
        return sum((vat for _, vat in self.vat_breakdown().values()), Decimal("0.00"))

    @property
    def gross_total(self) -> Decimal:
        return self.net_total + self.vat_total
