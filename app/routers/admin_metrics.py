"""Métriques admin — observabilité phase 3."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.database import get_db, DB_PATH
from app.metrics_collector import snapshot
from app.models import Client, Invoice, User
from app.models_erp import Supplier, SupplierInvoice, AuditLog
from app.server_config import is_production

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/metrics")
def admin_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("settings.manage")),
):
    db_size = 0
    try:
        if DB_PATH.is_file():
            db_size = DB_PATH.stat().st_size
    except OSError:
        pass

    counts = {
        "users": db.query(User).count(),
        "clients": db.query(Client).count(),
        "invoices": db.query(Invoice).count(),
        "suppliers": db.query(Supplier).count(),
        "supplier_invoices": db.query(SupplierInvoice).count(),
        "audit_logs": db.query(AuditLog).count(),
    }
    versions = db.execute(
        text("SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 5")
    ).fetchall() if _table_exists(db, "schema_migrations") else []

    return {
        "ok": True,
        "environment": "production" if is_production() else "development",
        "runtime": snapshot(),
        "database": {
            "path": str(DB_PATH) if not is_production() else "(masqué)",
            "size_bytes": db_size,
        },
        "counts": counts,
        "schema_versions": [r[0] for r in versions],
        "pid": os.getpid(),
    }


def _table_exists(db: Session, name: str) -> bool:
    from sqlalchemy import inspect

    return name in inspect(db.bind).get_table_names()
