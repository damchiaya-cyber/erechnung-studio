# E-Rechnung Studio

**Deutsch:** Web-App zum Erstellen, Prüfen und Archivieren von E-Rechnungen im Format **XRechnung 3.0 (UBL)**.
**English:** Web app to create, check and archive German e-invoices (XRechnung 3.0, UBL syntax).

## Warum dieses Projekt? / Why this project?

Seit dem 01.01.2025 müssen alle Unternehmen in Deutschland E-Rechnungen **empfangen** können; das **Ausstellen**
wird stufenweise Pflicht (2027 bzw. 2028, je nach Umsatz). Unternehmen brauchen dafür Software und Schnittstellen zwischen
Buchhaltung, ERP und Rechnungsformaten. Dieses Projekt zeigt genau diese Bausteine im Kleinen:
Datenmodell, XML-Erzeugung, Regelprüfung, Datenbank, Oberfläche und Tests.
*(Fristen bitte vor Verwendung aktuell prüfen.)*

## Funktionen

| Bereich | Was es kann |
|---|---|
| Erstellen | Rechnung erfassen, Summen und USt pro Steuersatz berechnen (Decimal, kaufmännisch gerundet), XRechnung-XML erzeugen und herunterladen |
| Prüfen | XML hochladen, EN-16931-/XRechnung-Regeln prüfen (z. B. BR-DE-15, BR-CO-15, IBAN-Prüfsumme), lesbare Ansicht |
| Übersicht | SQLite-Archiv (nur fehlerfreie Rechnungen, damit Nummern lückenlos bleiben), Kennzahlen, Monatsumsatz, CSV-Export, automatische Rechnungsnummer |

## Starten

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
python -m pytest -q                                   # 23 Tests
```

## Aufbau

```
app.py                  Oberfläche (Streamlit, deutsch), nur Darstellung
erechnung/models.py     Datenklassen + Berechnung (Invoice, LineItem, Party)
erechnung/builder.py    Invoice -> XRechnung-XML (UBL 2.1)
erechnung/validator.py  XML einlesen + Regeln prüfen (Finding-Liste)
erechnung/archive.py    SQLite: speichern, laden, nächste Rechnungsnummer
erechnung/demo.py       Fiktive Beispieldaten
tests/                  Berechnung, XML-Roundtrip, Regeln, Archiv, UI-Smoke-Tests
sample_data/            Eine gültige und eine absichtlich fehlerhafte Beispieldatei
```

Die Schichten sind getrennt: Die Oberfläche enthält keine Geschäftslogik, alles Wichtige ist ohne Streamlit testbar.

## Grenzen (bitte ehrlich benennen)

- Die erzeugte Datei ist gegen das offizielle **UBL-2.1-XSD** geprüft. Die vollständigen Schematron-Regeln des
  KoSIT-Prüftools sind **nicht** umgesetzt; `validator.py` prüft eine Auswahl der wichtigsten Regeln.
  Vor dem produktiven Einsatz immer mit dem offiziellen KoSIT-Validator gegenprüfen.
- Nur UBL (kein CII), nur Rechnungstyp 380, keine Rabatte/Zuschläge, kein ZUGFeRD-PDF, keine Anmeldung/Versand über Peppol.
- Alle Firmen, Adressen und die IBAN im Projekt sind fiktive bzw. öffentliche Beispiele.

## Ideen zum Ausbauen

CII-Syntax ergänzen, ZUGFeRD-PDF erzeugen, Schematron-Prüfung über den KoSIT-Validator anbinden, REST-API mit FastAPI, Docker-Image.
