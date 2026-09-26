"""E-Rechnung Studio - create, check and archive XRechnung invoices (Streamlit UI, German)."""
import html
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

from erechnung.archive import load_invoices, next_invoice_number, save_invoice
from erechnung.builder import build_xrechnung
from erechnung.demo import BUYER, BUYER_REFERENCE, IBAN, SELLER, broken_sample_xml, sample_invoice, seed_archive
from erechnung.models import Invoice, LineItem, Party
from erechnung.validator import ERROR, Finding, validate_invoice

DB_PATH = os.environ.get("ERECHNUNG_DB", str(Path(__file__).parent / "data" / "archive.db"))
UNITS = {"Stück": "C62", "Stunde": "HUR", "Tag": "DAY"}

st.set_page_config(page_title="E-Rechnung Studio", page_icon="🧾", layout="wide")


# ---------------------------------------------------------------- helpers
def eur(value) -> str:
    """German number format: 1.234,56 €"""
    text = f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def de_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso or "-"


def inject_style() -> None:
    """Soft nude look: sand background, cocoa text, dusty-rose accent, rounded shapes."""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Nunito+Sans:wght@400;600&display=swap');
    .stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button { font-family: 'Nunito Sans', 'Segoe UI', sans-serif; }
    /* keep Streamlit's icon font, otherwise icons show up as words like 'upload' */
    [data-testid="stIconMaterial"], .material-symbols-rounded { font-family: 'Material Symbols Rounded' !important; }
    h1, h2, h3 { font-family: 'Fraunces', Georgia, serif !important; font-weight: 600; color: #4B3F3A; letter-spacing: -0.01em; }
    .block-container { max-width: 1100px; padding-top: 2.5rem; }
    .subtitle { color: #7A6A62; margin-top: -0.6rem; margin-bottom: 1.5rem; }
    button[data-baseweb="tab"] { font-size: 1.05rem; }
    .stButton button, .stDownloadButton button { border-radius: 999px; border: 0; background: #9C6F5F; color: #FFFFFF; padding: 0.5rem 1.4rem; }
    .stButton button:hover, .stDownloadButton button:hover { background: #855B4D; color: #FFFFFF; }
    [data-testid="stMetric"] { background: #F1E4DA; border: 1px solid #E3D2C4; border-radius: 16px; padding: 1rem 1.2rem; }
    [data-testid="stDataFrame"], [data-testid="stDataEditor"] { border-radius: 14px; overflow: hidden; }
    .finding { border-radius: 14px; padding: 0.7rem 1rem; margin-bottom: 0.5rem; }
    .finding b { margin-right: 0.5rem; }
    .finding.ok { background: #E3EBDD; color: #48604A; }
    .finding.error { background: #F3DADA; color: #8E4747; }
    .finding.warning { background: #F1E4C8; color: #7A5C22; }
    </style>""", unsafe_allow_html=True)


def show_findings(findings: list[Finding]) -> None:
    """Soft-coloured result list. Messages may contain text from uploaded files, so escape them."""
    if not findings:
        st.markdown('<div class="finding ok"><b>Alles in Ordnung.</b>Keine Fehler in den geprüften Regeln gefunden.</div>',
                    unsafe_allow_html=True)
        return
    for f in findings:
        css = "error" if f.severity == ERROR else "warning"
        st.markdown(f'<div class="finding {css}"><b>{html.escape(f.rule)}</b>{html.escape(f.message)}</div>',
                    unsafe_allow_html=True)


# ------------------------------------------------------------ tab 1: create
def party_inputs(prefix: str, default: Party, seller: bool) -> Party:
    name = st.text_input("Name", default.name, key=f"{prefix}_name")
    street = st.text_input("Straße und Hausnummer", default.street, key=f"{prefix}_street")
    plz, city = st.columns([1, 2])
    postal = plz.text_input("PLZ", default.postal_code, key=f"{prefix}_plz")
    town = city.text_input("Ort", default.city, key=f"{prefix}_city")
    vat_id = st.text_input("USt-IdNr.", default.vat_id, key=f"{prefix}_vat") if seller else ""
    contact = phone = email = ""
    if seller:
        contact = st.text_input("Ansprechpartner", default.contact_name, key=f"{prefix}_contact")
        phone = st.text_input("Telefon", default.phone, key=f"{prefix}_phone")
        email = st.text_input("E-Mail", default.email, key=f"{prefix}_email")
    return Party(name, street, postal, town, "DE", vat_id, email, contact, phone)


def lines_from_table(table: pd.DataFrame) -> tuple[list[LineItem], list[int]]:
    """Convert the editable table into LineItems.

    Returns (lines, incomplete_row_numbers). Completely empty rows are ignored;
    half-filled rows are reported so they are never dropped silently.
    """
    lines, incomplete = [], []
    for number, row in enumerate(table.itertuples(index=False), start=1):
        description = "" if pd.isna(row.Beschreibung) else str(row.Beschreibung).strip()
        quantity, price, vat = row.Menge, row.Einzelpreis, row[4]
        if not description and pd.isna(quantity) and pd.isna(price) and pd.isna(vat):
            continue  # untouched empty row
        if not description or pd.isna(quantity) or pd.isna(price) or pd.isna(vat):
            incomplete.append(number)
            continue
        unit = UNITS.get(row.Einheit, "C62")  # 'Stück' if the unit was left empty
        lines.append(LineItem(description, Decimal(str(quantity)), unit, Decimal(str(price)), Decimal(str(vat))))
    return lines, incomplete


def tab_create() -> None:
    demo = sample_invoice()
    st.subheader("Rechnung erstellen")

    # The number is kept in session state so it stays stable while typing and only
    # moves on to the next free number after an invoice was saved.
    if "number" not in st.session_state or st.session_state.pop("advance_number", False):
        st.session_state["number"] = next_invoice_number(DB_PATH)

    head = st.columns(4)
    number = head[0].text_input("Rechnungsnummer", key="number")
    issue = head[1].date_input("Rechnungsdatum", date.today(), format="DD.MM.YYYY")
    due = head[2].date_input("Fällig am", date.today() + timedelta(days=14), format="DD.MM.YYYY")
    reference = head[3].text_input("Leitweg-ID / Käuferreferenz", BUYER_REFERENCE)

    left, right = st.columns(2)
    with left:
        st.markdown("**Rechnungssteller**")
        seller = party_inputs("seller", SELLER, seller=True)
    with right:
        st.markdown("**Rechnungsempfänger**")
        buyer = party_inputs("buyer", BUYER, seller=False)
        iban = st.text_input("IBAN des Rechnungsstellers", IBAN)
        note = st.text_input("Zahlungsbedingungen", demo.payment_note)

    st.markdown("**Positionen**")
    start = pd.DataFrame([{"Beschreibung": l.description, "Menge": float(l.quantity),
                           "Einheit": {v: k for k, v in UNITS.items()}[l.unit_code],
                           "Einzelpreis": float(l.unit_price), "USt %": int(l.vat_rate)} for l in demo.lines])
    table = st.data_editor(start, num_rows="dynamic", use_container_width=True, hide_index=True, column_config={
        "Menge": st.column_config.NumberColumn(min_value=0.0, step=1.0),
        "Einheit": st.column_config.SelectboxColumn(options=list(UNITS)),
        "Einzelpreis": st.column_config.NumberColumn("Einzelpreis (netto)", min_value=0.0, format="%.2f"),
        "USt %": st.column_config.SelectboxColumn(options=[19, 7, 0]),
    })

    if st.button("XRechnung erzeugen"):
        lines, incomplete = lines_from_table(table)
        invoice = Invoice(number.strip(), issue, due, reference.strip(), seller, buyer, iban, lines, note)
        xml = build_xrechnung(invoice)
        _, findings = validate_invoice(xml)
        findings += [Finding("POSITION", ERROR, f"Position {n} ist unvollständig: Beschreibung, Menge, Einzelpreis und USt % ausfüllen.")
                     for n in incomplete]
        valid = not any(f.severity == ERROR for f in findings)
        st.session_state["result"] = {"xml": xml, "findings": findings, "valid": valid, "invoice": invoice}
        if valid:  # invoices with errors are not archived, so they never use up a number
            save_invoice(DB_PATH, invoice)
            st.session_state["advance_number"] = True
            st.rerun()

    result = st.session_state.get("result")
    if result:
        invoice = result["invoice"]
        st.divider()
        cols = st.columns(3)
        cols[0].metric("Netto", eur(invoice.net_total))
        cols[1].metric("Umsatzsteuer", eur(invoice.vat_total))
        cols[2].metric("Brutto", eur(invoice.gross_total))
        show_findings(result["findings"])
        if result["valid"]:
            st.download_button("XML herunterladen", result["xml"], file_name=f"{invoice.number}.xml", mime="application/xml")
        else:
            st.caption("Bitte die Fehler oben beheben, dann kann die Datei heruntergeladen werden.")


# ------------------------------------------------------------- tab 2: check
def tab_check() -> None:
    st.subheader("Eingehende Rechnung prüfen")
    st.caption("Seit 2025 müssen Unternehmen in Deutschland E-Rechnungen empfangen können. "
               "Hier lässt sich eine XRechnung (UBL) prüfen und lesbar anzeigen.")
    uploaded = st.file_uploader("XRechnung-Datei (.xml)", type=["xml"])
    cols = st.columns([1, 1, 3])
    if cols[0].button("Beispiel prüfen"):
        st.session_state["check_bytes"] = build_xrechnung(sample_invoice())
    if cols[1].button("Fehlerhaftes Beispiel"):
        st.session_state["check_bytes"] = broken_sample_xml()
    if uploaded is not None:
        st.session_state["check_bytes"] = uploaded.getvalue()

    xml = st.session_state.get("check_bytes")
    if xml is None:
        return
    data, findings = validate_invoice(xml)
    st.divider()
    show_findings(findings)
    if data is None:
        return

    st.markdown(f"### Rechnung {html.escape(data['number'])}")
    a, b = st.columns(2)
    for column, title, key in ((a, "Von", "seller"), (b, "An", "buyer")):
        party = data[key]
        column.markdown(f"**{title}**  \n{party['name']}  \n{party['street']}  \n{party['postal_code']} {party['city']}")
    st.write(f"Datum: {de_date(data['issue_date'])} · Fällig: {de_date(data['due_date'])} · Referenz: {data['buyer_reference'] or '-'}")
    lines = pd.DataFrame(data["lines"]).rename(columns={"id": "Pos.", "name": "Beschreibung", "quantity": "Menge",
                                                       "unit": "Einheit", "price": "Einzelpreis", "net": "Netto", "vat_rate": "USt %"})
    st.dataframe(lines, hide_index=True, use_container_width=True)
    totals = st.columns(3)
    for column, label, key in zip(totals, ("Netto", "Umsatzsteuer", "Zahlbetrag"), ("net_total", "vat_total", "payable")):
        column.metric(label, eur(data[key]) if data[key] else "-")


# --------------------------------------------------------- tab 3: overview
def tab_overview() -> None:
    st.subheader("Übersicht")
    table = load_invoices(DB_PATH)
    if table.empty:
        st.info("Noch keine Rechnungen archiviert. Erstelle eine Rechnung oder lade Demo-Daten.")
        if st.button("Demo-Daten laden"):
            seed_archive(DB_PATH)
            st.rerun()
        return

    cols = st.columns(4)
    cols[0].metric("Rechnungen", len(table))
    cols[1].metric("Netto gesamt", eur(table["net"].sum()))
    cols[2].metric("Brutto gesamt", eur(table["gross"].sum()))
    cols[3].metric("Ø Rechnungsbetrag", eur(table["gross"].mean()))

    monthly = table.assign(Monat=table["issue_date"].str[:7]).groupby("Monat")["gross"].sum().sort_index()
    st.markdown("**Brutto-Umsatz pro Monat**")
    st.bar_chart(monthly, color="#B68D7C")

    shown = table.assign(issue_date=table["issue_date"].map(de_date), net=table["net"].map(eur),
                         vat=table["vat"].map(eur), gross=table["gross"].map(eur))
    shown.columns = ["Nummer", "Datum", "Empfänger", "Netto", "USt", "Brutto"]
    st.dataframe(shown, hide_index=True, use_container_width=True)
    st.download_button("Als CSV exportieren", table.to_csv(index=False, sep=";", decimal=",", float_format="%.2f"), file_name="rechnungen.csv", mime="text/csv")


# --------------------------------------------------------------------- main
inject_style()
st.title("E-Rechnung Studio")
st.markdown('<p class="subtitle">XRechnung erstellen, prüfen und archivieren</p>', unsafe_allow_html=True)
create, check, overview = st.tabs(["Erstellen", "Prüfen", "Übersicht"])
with create:
    tab_create()
with check:
    tab_check()
with overview:
    tab_overview()
