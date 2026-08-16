"""Gestion des dates ERP — UTC, échéances, horodatage audit."""
from __future__ import annotations

import datetime as dt
from datetime import date, timedelta
from typing import Optional


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_date(value: object) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    s = str(value).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def compute_due_date(invoice_date: Optional[date], payment_terms_days: int = 30) -> Optional[date]:
    if not invoice_date:
        return None
    days = max(0, int(payment_terms_days or 0))
    if days == 0:
        return invoice_date
    return invoice_date + timedelta(days=days)


def stamp_create(obj, user) -> None:
    now = utc_now_iso()
    if hasattr(obj, "created_at") and not getattr(obj, "created_at", None):
        setattr(obj, "created_at", now)
    if hasattr(obj, "updated_at"):
        setattr(obj, "updated_at", now)
    uid = getattr(user, "id", None)
    if uid and hasattr(obj, "created_by") and not getattr(obj, "created_by", None):
        setattr(obj, "created_by", uid)
    if uid and hasattr(obj, "updated_by"):
        setattr(obj, "updated_by", uid)


def stamp_update(obj, user) -> None:
    if hasattr(obj, "updated_at"):
        setattr(obj, "updated_at", utc_now_iso())
    uid = getattr(user, "id", None)
    if uid and hasattr(obj, "updated_by"):
        setattr(obj, "updated_by", uid)


def apply_invoice_dates(obj, data: dict, *, is_create: bool = False) -> None:
    """Calcule échéance et horodatages métier facture."""
    inv_date = parse_iso_date(data.get("date") or getattr(obj, "date", None))
    terms = int(data.get("payment_terms_days") or getattr(obj, "payment_terms_days", None) or 30)
    due = parse_iso_date(data.get("due_date"))
    if inv_date and not due:
        due = compute_due_date(inv_date, terms)
        if hasattr(obj, "due_date"):
            obj.due_date = due
    status = data.get("status") or getattr(obj, "status", "")
    if status in ("envoyée", "payée", "en retard") and hasattr(obj, "issued_at") and not getattr(obj, "issued_at", None):
        obj.issued_at = utc_now_iso()
    if status == "payée" and hasattr(obj, "payment_date"):
        paid_amt = float(data.get("paid") if "paid" in data else getattr(obj, "paid", 0) or 0)
        if paid_amt > 0 and not getattr(obj, "payment_date", None):
            obj.payment_date = inv_date or date.today()
    if status == "annulée" and hasattr(obj, "cancelled_at") and not getattr(obj, "cancelled_at", None):
        obj.cancelled_at = utc_now_iso()
    if status in ("envoyée", "payée", "en retard", "validée") and hasattr(obj, "validated_at") and not getattr(obj, "validated_at", None):
        obj.validated_at = utc_now_iso()
