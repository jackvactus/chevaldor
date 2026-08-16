"""Tests moteur comptable SYSCOHADA — écritures auto équilibrées."""
import json
import os
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.models import Invoice, DocumentLine, StockItem
from app.models_erp import SupplierInvoice, JournalEntry, JournalLine
from app.models_prefs import SystemSettings
from app.models_accounting import SupplierInvoiceLine, AccountingTransaction
from app.syscohada.constants import DEFAULT_ACCOUNTS, JOURNALS, TOGO_VAT_RATES
from app.syscohada.service import import_syscohada_chart
from app.services.accounting_engine import (
    build_invoice_lines,
    build_supplier_invoice_lines,
    on_invoice_validated,
    on_supplier_invoice_validated,
    on_payment_recorded,
    post_transaction,
)
from app.services.accounting_reports import validate_entry_balance, normalize_journal_lines, normalize_journal_lines
from app.syscohada.posting import _settings


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    import app.models  # noqa: F401
    import app.models_erp  # noqa: F401
    import app.models_prefs  # noqa: F401
    import app.models_accounting  # noqa: F401
    import app.models_syscohada  # noqa: F401
    import app.models_stock  # noqa: F401

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(SystemSettings(
        id=1,
        accounting_plan="SYSCOHADA",
        journals_json=json.dumps([j["code"] for j in JOURNALS]),
        taxes_json=json.dumps(TOGO_VAT_RATES),
        default_accounts_json=json.dumps(DEFAULT_ACCOUNTS),
        inventory_method="PERMANENT",
    ))
    session.commit()
    import_syscohada_chart(session, force=True)
    yield session
    session.close()


def test_build_invoice_service_line_balanced(db):
    cfg = _settings(db)
    inv = Invoice(number="F-001", date=date(2026, 3, 1), amount=118000, vat_rate=18, status="envoyée")
    db.add(inv)
    db.flush()
    db.add(DocumentLine(
        invoice_id=inv.id,
        description="Prestation conseil",
        quantity=1,
        unit_price=100000,
        vat_rate=18,
        product_type="SERVICE",
        position=0,
    ))
    db.commit()
    doc_lines = db.query(DocumentLine).filter(DocumentLine.invoice_id == inv.id).all()
    lines = build_invoice_lines(db, inv, doc_lines, cfg)
    assert validate_entry_balance(lines)
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines)


def test_build_supplier_merchandise_stock_account(db):
    cfg = _settings(db)
    inv = SupplierInvoice(number="A-001", date=date(2026, 3, 2), amount=0, status="validée")
    db.add(inv)
    db.flush()
    db.add(SupplierInvoiceLine(
        supplier_invoice_id=inv.id,
        description="Marchandises",
        quantity=10,
        unit_price=5000,
        vat_rate=18,
        product_type="MERCHANDISE",
        line_kind="product",
        position=0,
    ))
    db.commit()
    lines = build_supplier_invoice_lines(db, inv, cfg)
    assert validate_entry_balance(lines)
    codes = {l["account_code"] for l in lines}
    assert "311100" in codes or "601100" in codes
    assert "401100" in codes


def test_on_invoice_validated_creates_journal(db):
    inv = Invoice(number="F-002", date=date(2026, 4, 1), amount=59000, vat_rate=18, status="envoyée")
    db.add(inv)
    db.commit()
    tx = on_invoice_validated(db, inv)
    assert tx is not None
    assert tx.status == "posted"
    entry = db.query(JournalEntry).filter(JournalEntry.id == tx.journal_entry_id).first()
    assert entry is not None
    assert entry.journal == "VE"
    jlines = db.query(JournalLine).filter(JournalLine.entry_id == entry.id).all()
    assert abs(sum(l.debit for l in jlines) - sum(l.credit for l in jlines)) < 0.02


def test_on_supplier_invoice_with_transport_fee(db):
    inv = SupplierInvoice(number="A-002", date=date(2026, 4, 2), amount=0, status="validée")
    db.add(inv)
    db.flush()
    db.add(SupplierInvoiceLine(
        supplier_invoice_id=inv.id, description="Matériel", quantity=5, unit_price=2000,
        vat_rate=18, product_type="MERCHANDISE", line_kind="product", position=0,
    ))
    db.add(SupplierInvoiceLine(
        supplier_invoice_id=inv.id, description="Transport", quantity=1, unit_price=5000,
        vat_rate=18, product_type="MERCHANDISE", line_kind="transport", position=1,
    ))
    db.commit()
    tx = on_supplier_invoice_validated(db, inv)
    assert tx is not None
    jlines = db.query(JournalLine).filter(JournalLine.entry_id == tx.journal_entry_id).all()
    deb = sum(l.debit for l in jlines)
    cred = sum(l.credit for l in jlines)
    assert abs(deb - cred) < 0.02


def test_payment_recorded_balanced(db):
    tx = on_payment_recorded(
        db,
        amount=50000,
        direction="in",
        payment_method="bank",
        reference="ENC-001",
        label="Encaissement client",
        source_id=1,
        entry_date=date(2026, 5, 1),
    )
    assert tx.status == "posted"
    jlines = db.query(JournalLine).filter(JournalLine.entry_id == tx.journal_entry_id).all()
    assert abs(sum(l.debit for l in jlines) - sum(l.credit for l in jlines)) < 0.02


def test_post_transaction_idempotent(db):
    payload = {
        "journal": "OD",
        "reference": "TEST-OD",
        "label": "Test OD",
        "lines": [
            {"account_code": "601100", "debit": 1000, "credit": 0, "label": "Charge"},
            {"account_code": "521100", "debit": 0, "credit": 1000, "label": "Banque"},
        ],
    }
    tx1 = post_transaction(db, "manual", 99, payload)
    tx2 = post_transaction(db, "manual", 99, payload)
    assert tx1.id == tx2.id
    assert db.query(AccountingTransaction).filter(AccountingTransaction.source_type == "manual").count() == 1


def test_normalize_journal_lines_mixed_amount_types():
    raw = [
        {"account_code": "601100", "debit": 1000, "credit": 0},
        {"account_code": "401100", "debit": 0, "credit": "1000"},
    ]
    norm = normalize_journal_lines(raw)
    assert validate_entry_balance(norm)
    assert norm[1]["credit"] == 1000.0


def test_normalize_journal_lines_dict_indexed():
    raw = {
        "0": {"account_code": "601100", "debit": "500", "credit": ""},
        "1": {"account_code": "401100", "debit": "", "credit": "500"},
    }
    norm = normalize_journal_lines(raw)
    assert len(norm) == 2
    assert validate_entry_balance(norm)
