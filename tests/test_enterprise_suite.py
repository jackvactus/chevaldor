"""Tests Enterprise Suite P0–P5 — services critiques."""
import os
import sys

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.models import Client, Project, StockItem, Task, User
from app.models_enterprise import Company
from app.models_enterprise_suite import DocumentFile, EsignRequest
from app.models_currency import Currency
from app.services import enterprise_suite_service as svc
from app.services.esign_service import create_esign_with_provider, get_esign_by_token, sign_by_token


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    import app.models  # noqa: F401
    import app.models_erp  # noqa: F401
    import app.models_stock  # noqa: F401
    import app.models_enterprise  # noqa: F401
    import app.models_enterprise_suite  # noqa: F401
    import app.models_currency  # noqa: F401
    import app.models_prefs  # noqa: F401
    import app.models_accounting  # noqa: F401
    import app.models_enterprise_ops  # noqa: F401

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    session.add(StockItem(sku="SKU-001", name="Article test", quantity=10, barcode="123456"))
    session.add(Client(name="Client A", email="clienta@test.local", phone="+22890123456"))
    session.add(Company(code="PEYA", name="Peya Company", is_active=True))
    session.add(Currency(code="XOF", name="Franc CFA", symbol="F", rate_to_base=1.0, is_active=True))
    session.add(Currency(code="EUR", name="Euro", symbol="€", rate_to_base=655.0, is_active=True))
    p = Project(name="Projet test", status="en cours", progress=30)
    session.add(p)
    session.commit()
    session.refresh(p)
    session.add(Task(project_id=p.id, label="Tâche 1", kanban_status="todo"))
    session.add(User(username="admin", email="admin@test.local", password_hash="x", role="admin"))
    session.commit()
    yield session
    session.close()


def test_stock_scan_found(db):
    r = svc.scan_code(db, "SKU-001", user_id=1)
    assert r["found"] is True
    assert r["item"]["sku"] == "SKU-001"


def test_stock_scan_barcode(db):
    r = svc.scan_code(db, "123456")
    assert r["found"] is True


def test_stock_lot_and_serial(db):
    item = db.query(StockItem).first()
    lot = svc.create_lot(db, {"stock_item_id": item.id, "lot_number": "LOT-1", "quantity": 5})
    serial = svc.create_serial(db, {"stock_item_id": item.id, "serial_number": "SN-999"})
    assert lot.lot_number == "LOT-1"
    assert serial.serial_number == "SN-999"


def test_project_kanban_and_schedule(db):
    task = db.query(Task).first()
    moved = svc.move_task_kanban(db, task.id, "in_progress")
    assert moved["kanban_status"] == "in_progress"
    scheduled = svc.update_task_schedule(db, task.id, "2026-06-20")
    assert scheduled["date"] == "2026-06-20"


def test_project_board(db):
    board = svc.project_board(db)
    assert board["stats"]["projects"] >= 1
    assert "kanban" in board
    assert "gantt" in board


def test_consolidation(db):
    run = svc.run_consolidation(db, 2026)
    assert run.status == "completed"
    import json
    detail = json.loads(run.detail_json)
    assert "companies" in detail


def test_currency_convert(db):
    r = svc.convert_currency(db, 655.0, "XOF", "EUR")
    assert r["converted"] == 1.0
    r2 = svc.convert_currency(db, 1.0, "EUR", "XOF")
    assert r2["converted"] == 655.0


def test_ai_insights(db):
    insights = svc.generate_ai_insights(db)
    assert len(insights) >= 3


def test_ged_upload(db):
    user = db.query(User).first()
    doc = svc.upload_ged_file(db, "test.txt", b"hello", "text/plain", user.id)
    assert doc.id
    assert doc.filename == "test.txt"
    path = svc.ged_storage_root() / doc.storage_path
    assert path.is_file()


def test_esign_internal_flow(db):
    req = create_esign_with_provider(
        db, "quote", 1, "signer@test.local", "Jean Test", provider="internal",
    )
    assert req.signing_token
    assert req.signing_url.startswith("/esign-sign.html")
    row = get_esign_by_token(db, req.signing_token)
    assert row.status == "pending"
    signed = sign_by_token(db, req.signing_token, "Jean Test")
    assert signed.status == "signed"
    assert signed.signed_at


def test_esign_docusign_provider(db):
    req = create_esign_with_provider(
        db, "invoice", 2, "a@b.com", "Marie", provider="docusign",
    )
    assert req.provider == "docusign"
    assert req.provider_ref.startswith("docusign-")


def test_supplier_portal_token(db):
    from app.models_erp import Supplier
    s = Supplier(name="Fournisseur Test")
    db.add(s)
    db.commit()
    db.refresh(s)
    row = svc.create_supplier_portal_token(db, s.id, days=30)
    assert row.token
    assert row.is_active is True


def test_marketing_campaign_email_no_smtp(db):
    """Sans SMTP configuré : échec attendu mais campagne enregistrée."""
    r = svc.launch_marketing_campaign(
        db, "email", "Sujet test", "Corps", 1,
        recipient_emails=["nobody@test.local"],
    )
    assert r["id"]
    assert r["failed"] >= 1 or r["sent"] >= 0
    assert r["status"] in ("failed", "partial", "sent")


def test_logistics_summary(db):
    r = svc.logistics_summary(db)
    assert "vehicles" in r
    assert "shipments" in r
