"""Modification tracée des dates — factures, écritures, achats, ventes."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models_business_ext import DateChangeLog
from app.services.audit_log import log_audit

_ALLOWED_FIELDS = {
    "invoice": ("date", "due_date", "delivery_date", "payment_date"),
    "journal_entry": ("date", "value_date"),
    "supplier_invoice": ("date", "due_date", "payment_date"),
    "deal": ("close_date",),
    "quote": ("date", "valid_until"),
    "purchase_order": ("date",),
    "goods_receipt": ("date",),
}

_MODEL_MAP = {
    "invoice": ("app.models", "Invoice"),
    "journal_entry": ("app.models_erp", "JournalEntry"),
    "supplier_invoice": ("app.models_erp", "SupplierInvoice"),
    "deal": ("app.models", "Deal"),
    "quote": ("app.models", "Quote"),
    "purchase_order": ("app.models_erp", "PurchaseOrder"),
    "goods_receipt": ("app.models_erp", "GoodsReceipt"),
}


def _resolve_model(entity_type: str):
    mod_name, cls_name = _MODEL_MAP[entity_type]
    import importlib
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


def change_entity_date(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    field_name: str,
    new_value: date | str | None,
    user_id: int | None = None,
    user_email: str = "",
    ip: str = "",
    detail: str = "",
) -> dict[str, Any]:
    if entity_type not in _ALLOWED_FIELDS:
        raise ValueError(f"Type d'entité non supporté : {entity_type}")
    if field_name not in _ALLOWED_FIELDS[entity_type]:
        raise ValueError(f"Champ date non autorisé : {field_name}")

    Model = _resolve_model(entity_type)
    obj = db.query(Model).filter(Model.id == entity_id).first()
    if not obj:
        raise ValueError("Entité introuvable")

    if entity_type == "journal_entry" and getattr(obj, "status", "") == "validée":
        raise ValueError("Impossible de modifier la date d'une écriture validée — utilisez une extourne")

    old_raw = getattr(obj, field_name, None)
    old_str = str(old_raw) if old_raw is not None else ""

    if isinstance(new_value, str):
        from datetime import datetime as dt
        parsed = dt.strptime(new_value[:10], "%Y-%m-%d").date()
    else:
        parsed = new_value

    setattr(obj, field_name, parsed)
    if hasattr(obj, "updated_at"):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        obj.updated_at = now
    if hasattr(obj, "updated_by") and user_id:
        obj.updated_by = user_id

    logged = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.add(DateChangeLog(
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        old_value=old_str,
        new_value=str(parsed) if parsed else "",
        user_id=user_id,
        user_email=user_email or "",
        logged_at=logged,
        detail=detail or "",
    ))
    log_audit(
        db,
        "date_change",
        entity_type,
        entity_type,
        entity_id,
        f"{field_name}: {old_str} → {parsed}",
        user_id,
        user_email,
        ip,
        old_value=old_str,
        new_value=str(parsed) if parsed else "",
    )
    db.commit()
    return {"ok": True, "entity_type": entity_type, "entity_id": entity_id, "field": field_name, "old": old_str, "new": str(parsed)}


def list_date_changes(db: Session, entity_type: str, entity_id: int) -> list[dict]:
    rows = (
        db.query(DateChangeLog)
        .filter(DateChangeLog.entity_type == entity_type, DateChangeLog.entity_id == entity_id)
        .order_by(DateChangeLog.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": r.id,
            "field": r.field_name,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "user_email": r.user_email,
            "logged_at": r.logged_at,
            "detail": r.detail,
        }
        for r in rows
    ]


def list_recent_date_changes(db: Session, limit: int = 200) -> list[dict]:
    rows = (
        db.query(DateChangeLog)
        .order_by(DateChangeLog.id.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "id": r.id,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "field": r.field_name,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "user_email": r.user_email,
            "logged_at": r.logged_at,
            "detail": r.detail,
        }
        for r in rows
    ]
