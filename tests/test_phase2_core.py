"""Tests Phase 2 — auxiliaires, contre-passation, clôture, lettrage."""
import os
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.models import Client, Account
from app.models_erp import JournalEntry, JournalLine, Supplier
from app.services.auxiliary_account_service import (
    ensure_client_auxiliary,
    ensure_supplier_auxiliary,
    auxiliary_code,
)
from app.services.journal_reversal_service import reverse_journal_entry
from app.services.lettering_service import apply_lettering, remove_lettering
from app.syscohada.constants import DEFAULT_ACCOUNTS


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    import app.models  # noqa: F401
    import app.models_erp  # noqa: F401
    import app.models_stock  # noqa: F401

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(Account(code="411100", label="Clients", type="actif", class_code="4"))
    session.add(Account(code="401100", label="Fournisseurs", type="passif", class_code="4"))
    session.add(Account(code="131000", label="Résultat", type="passif", class_code="1"))
    session.add(Account(code="121000", label="Report", type="passif", class_code="1"))
    session.add(Account(code="601100", label="Achats", type="charge", class_code="6"))
    session.add(Account(code="701100", label="Ventes", type="produit", class_code="7"))
    session.commit()
    yield session
    session.close()


def test_auxiliary_client_code(db):
    c = Client(name="Test SARL", status="actif")
    db.add(c)
    db.commit()
    db.refresh(c)
    code = ensure_client_auxiliary(db, c)
    db.commit()
    assert code == auxiliary_code("411", c.id)
    assert code.startswith("411")
    acc = db.query(Account).filter(Account.code == code).first()
    assert acc is not None
    assert acc.parent_code == DEFAULT_ACCOUNTS["clients"]


def test_auxiliary_supplier_code(db):
    s = Supplier(name="Fournisseur X", status="actif")
    db.add(s)
    db.commit()
    db.refresh(s)
    code = ensure_supplier_auxiliary(db, s)
    db.commit()
    assert code.startswith("401")


def test_journal_reversal(db):
    entry = JournalEntry(
        date=date.today(), journal="OD", reference="T1", label="Test",
        status="validée", fiscal_year=2026, period=6,
    )
    db.add(entry)
    db.flush()
    db.add(JournalLine(entry_id=entry.id, account_code="601100", debit=1000, credit=0))
    db.add(JournalLine(entry_id=entry.id, account_code="401100", debit=0, credit=1000))
    db.commit()

    result = reverse_journal_entry(db, entry.id)
    assert result["ok"] is True
    rev = db.query(JournalEntry).filter(JournalEntry.id == result["reversal_id"]).first()
    assert rev.source_type == "reversal"
    lines = db.query(JournalLine).filter(JournalLine.entry_id == rev.id).all()
    assert sum(l.debit for l in lines) == 1000
    assert sum(l.credit for l in lines) == 1000


def test_lettering_and_unletter(db):
    entry = JournalEntry(
        date=date.today(), journal="VE", reference="F1", label="Facture",
        status="validée", fiscal_year=2026, period=6,
    )
    db.add(entry)
    db.flush()
    l1 = JournalLine(entry_id=entry.id, account_code="411000001", debit=500, credit=0)
    l2 = JournalLine(entry_id=entry.id, account_code="411000001", debit=0, credit=500)
    db.add(l1)
    db.add(l2)
    db.commit()

    r = apply_lettering(db, [l1.id, l2.id], "L2026-001")
    assert r["ok"]

    ur = remove_lettering(db, "L2026-001")
    assert ur["lines"] == 2
    db.refresh(l1)
    assert l1.letter_code == ""
