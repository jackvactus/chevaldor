"""Intelligence comptable — suggestions, alertes, comptes fréquents."""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models_erp import JournalEntry, JournalLine
from app.models_business_ext import SmartContextCache
from app.services.accounting_reports import normalize_journal_lines


def record_context_use(db: Session, user_id: int | None, key: str, value: str) -> None:
    if not user_id or not key or value is None:
        return
    val = str(value)[:500]
    row = (
        db.query(SmartContextCache)
        .filter(SmartContextCache.user_id == user_id, SmartContextCache.context_key == key)
        .first()
    )
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    if row:
        if row.context_value == val:
            row.use_count = (row.use_count or 0) + 1
        else:
            row.context_value = val
            row.use_count = 1
        row.last_used_at = now
    else:
        db.add(SmartContextCache(user_id=user_id, context_key=key, context_value=val, use_count=1, last_used_at=now))
    db.flush()


def get_suggestions(db: Session, user_id: int | None = None) -> dict[str, Any]:
    journals = Counter()
    accounts = Counter()
    recent_refs: list[str] = []

    entries = (
        db.query(JournalEntry)
        .order_by(JournalEntry.id.desc())
        .limit(200)
        .all()
    )
    for e in entries:
        if e.journal:
            journals[e.journal] += 1
        if e.reference:
            recent_refs.append(e.reference)
        lines = db.query(JournalLine).filter(JournalLine.entry_id == e.id).all()
        for ln in lines:
            if ln.account_code:
                accounts[ln.account_code] += 1

    last_ctx: dict[str, str] = {}
    if user_id:
        for row in db.query(SmartContextCache).filter(SmartContextCache.user_id == user_id).all():
            last_ctx[row.context_key] = row.context_value

    return {
        "journals": [{"code": k, "count": v} for k, v in journals.most_common(8)],
        "accounts": [{"code": k, "count": v} for k, v in accounts.most_common(12)],
        "recent_references": list(dict.fromkeys(recent_refs))[:10],
        "last_used": last_ctx,
    }


def validate_entry_anomalies(lines: list[dict], entry_date: date | None = None) -> list[dict]:
    alerts: list[dict] = []
    norm = normalize_journal_lines(lines)
    total_d = sum(l["debit"] for l in norm)
    total_c = sum(l["credit"] for l in norm)
    if abs(total_d - total_c) > 0.01:
        alerts.append({"level": "error", "code": "unbalanced", "message": f"Débit ({total_d:.2f}) ≠ Crédit ({total_c:.2f})"})
    if total_d == 0 and total_c == 0:
        alerts.append({"level": "warning", "code": "empty", "message": "Écriture sans montant"})
    for i, ln in enumerate(norm):
        if not (ln.get("account_code") or "").strip():
            alerts.append({"level": "error", "code": "missing_account", "message": f"Ligne {i + 1} : compte manquant"})
        vat_accounts = ("445", "443", "444")
        code = (ln.get("account_code") or "")[:3]
        if code in vat_accounts:
            amt = ln.get("debit", 0) + ln.get("credit", 0)
            if amt <= 0:
                alerts.append({"level": "warning", "code": "vat_zero", "message": f"Compte TVA {ln.get('account_code')} sans montant"})
    if entry_date and entry_date.year < 2000:
        alerts.append({"level": "warning", "code": "bad_date", "message": "Date incohérente"})
    return alerts
