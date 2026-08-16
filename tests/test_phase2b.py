"""Tests Phase 2B — réceptions, avoirs fournisseur, relevés, cessions."""
import os
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.models import Account, StockItem
from app.models_erp import Supplier, SupplierInvoice, BankAccount, TreasuryMovement
from app.models_syscohada import FixedAsset, AssetCategory
from app.services.goods_receipt_service import create_goods_receipt, validate_goods_receipt
from app.services.supplier_credit_service import create_supplier_credit_note
from app.services.bank_statement_service import import_bank_csv, auto_match_statement
from app.services.asset_disposal_service import dispose_fixed_asset


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    import app.models  # noqa: F401
    import app.models_erp  # noqa: F401
    import app.models_stock  # noqa: F401
    import app.models_syscohada  # noqa: F401
    import app.models_accounting  # noqa: F401

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    for code, label, cls in [
        ("601100", "Achats", "6"), ("401100", "Fournisseurs", "4"),
        ("244200", "Immo", "2"), ("284400", "Amort", "2"),
        ("521100", "Banque", "5"), ("775000", "Plus-value", "7"), ("675000", "Moins-value", "6"),
    ]:
        session.add(Account(code=code, label=label, type="actif", class_code=cls))
    session.commit()
    yield session
    session.close()


def test_goods_receipt_stock(db):
    sup = Supplier(name="Fournisseur Test", status="actif")
    db.add(sup)
    item = StockItem(name="Article A", sku="SKU1", quantity=10)
    db.add(item)
    db.commit()

    gr = create_goods_receipt(db, {
        "supplier_id": sup.id,
        "lines": [{"stock_item_id": item.id, "quantity": 5, "unit_cost": 1000}],
    })
    assert gr.number.startswith("BR-")

    result = validate_goods_receipt(db, gr.id)
    assert result["stock_movements"] == 1
    db.refresh(item)
    assert item.quantity == 15


def test_supplier_credit_note(db):
    sup = Supplier(name="F2", status="actif")
    db.add(sup)
    db.flush()
    inv = SupplierInvoice(
        number="SF-001", supplier_id=sup.id, date=date.today(),
        amount=118000, status="validée", doc_type="invoice",
    )
    db.add(inv)
    db.commit()

    cn = create_supplier_credit_note(db, inv.id, amount=50000)
    assert cn.doc_type == "credit_note"
    assert cn.related_supplier_invoice_id == inv.id


def test_bank_csv_import_and_match(db):
    bank = BankAccount(name="Compte test", balance=0)
    db.add(bank)
    db.flush()
    mov = TreasuryMovement(
        date=date.today(), type="banque_entree", bank_account_id=bank.id,
        label="Virement", amount=50000, reconciled=False,
    )
    db.add(mov)
    db.commit()

    csv_content = "date;libelle;montant\n2026-06-01;Virement;50000\n"
    imp = import_bank_csv(db, bank.id, csv_content)
    assert imp["lines"] == 1

    match = auto_match_statement(db, imp["statement_id"])
    assert match["matched"] >= 1


def test_asset_disposal(db):
    cat = AssetCategory(name="Matériel", account_asset="244200", account_depreciation="284400")
    db.add(cat)
    db.flush()
    asset = FixedAsset(
        code="IMMO-01", label="Machine", category_id=cat.id,
        acquisition_cost=100000, status="en_service", acquisition_date=date.today(),
    )
    db.add(asset)
    db.commit()

    disp = dispose_fixed_asset(db, asset.id, proceeds=80000)
    assert disp.gain_loss == -20000
    db.refresh(asset)
    assert asset.status == "cede"
