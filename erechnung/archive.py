"""Small SQLite archive so created invoices can be listed and analysed."""
import sqlite3
from contextlib import closing
from datetime import date

import pandas as pd

from .models import Invoice

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    number      TEXT PRIMARY KEY,
    issue_date  TEXT NOT NULL,
    buyer       TEXT NOT NULL,
    net         REAL NOT NULL,
    vat         REAL NOT NULL,
    gross       REAL NOT NULL
)
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    return conn


def save_invoice(db_path: str, invoice: Invoice) -> None:
    """Insert the invoice, or update it if the number already exists.

    Only invoices without errors should be saved: German invoice numbers must be
    unique and gap-free, so drafts with errors must not use up a number."""
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            """INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(number) DO UPDATE SET issue_date=excluded.issue_date,
               buyer=excluded.buyer, net=excluded.net, vat=excluded.vat,
               gross=excluded.gross""",
            (invoice.number, invoice.issue_date.isoformat(), invoice.buyer.name,
             float(invoice.net_total), float(invoice.vat_total), float(invoice.gross_total)),
        )


def load_invoices(db_path: str) -> pd.DataFrame:
    with closing(_connect(db_path)) as conn:
        return pd.read_sql_query("SELECT * FROM invoices ORDER BY issue_date DESC, number DESC", conn)


def next_invoice_number(db_path: str, today: date | None = None) -> str:
    """Return the next free number in the form RE-<year>-<4 digits>."""
    prefix = f"RE-{(today or date.today()).year}-"
    with closing(_connect(db_path)) as conn:
        rows = conn.execute("SELECT number FROM invoices WHERE number LIKE ?", (prefix + "%",)).fetchall()
    used = [int(n[0][len(prefix):]) for n in rows if n[0][len(prefix):].isdigit()]
    return f"{prefix}{max(used, default=0) + 1:04d}"
