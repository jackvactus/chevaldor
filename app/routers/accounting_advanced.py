"""Comptabilité avancée — brouillard, édition écritures, dates, suggestions."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.auth import get_current_user
from app.database import get_db
from app.fiscal_service import assert_fiscal_year_open
from app.models import User, Invoice
from app.models_erp import AuditLog, JournalEntry, JournalLine, SupplierInvoice
from app.models_business_ext import JournalEntryHistory
from app.models_accounting import AccountingTransaction
from app.services.accounting_engine import POSTING_STATUSES_INVOICE, POSTING_STATUSES_PURCHASE
from app.schemas_business import DateChangeIn, JournalEntryUpdateIn
from app.schemas_erp import JournalEntryIn
from app.services.audit_log import log_audit
from app.services.accounting_intelligence_service import (
    get_suggestions,
    record_context_use,
    validate_entry_anomalies,
)
from app.services.date_change_service import change_entity_date, list_date_changes, list_recent_date_changes
from app.services.smart_context_service import smart_lookup, touch_context
from app.services.accounting_reports import validate_entry_balance, normalize_journal_lines

router = APIRouter(prefix="/api/erp/accounting", tags=["accounting-advanced"])


def _user_ctx(request: Request, user: User):
    ip = request.client.host if request.client else ""
    return user.id, user.email, ip


def _entry_payload(e: JournalEntry, db: Session) -> dict:
    from app.models import Client

    lines = db.query(JournalLine).filter(JournalLine.entry_id == e.id).order_by(JournalLine.id).all()
    total_d = sum(l.debit or 0 for l in lines)
    total_c = sum(l.credit or 0 for l in lines)
    creator = ""
    if getattr(e, "created_by", None):
        u = db.query(User).filter(User.id == e.created_by).first()
        creator = (u.full_name or u.email or str(e.created_by)) if u else str(e.created_by)
    debit_accounts = [l.account_code for l in lines if (l.debit or 0) > 0]
    credit_accounts = [l.account_code for l in lines if (l.credit or 0) > 0]
    client_id = getattr(e, "client_id", None)
    client_name = ""
    client_code = ""
    client_account = ""
    if client_id:
        cl = db.query(Client).filter(Client.id == client_id).first()
        if cl:
            client_name = cl.name or ""
            client_code = str(cl.id)
            client_account = cl.account_code or ""
    line_client_ids = {getattr(l, "client_id", None) or client_id for l in lines}
    line_clients = {}
    ids = [i for i in line_client_ids if i]
    if ids:
        for cl in db.query(Client).filter(Client.id.in_(ids)).all():
            line_clients[cl.id] = cl.name
    return {
        "id": e.id,
        "date": str(e.date) if e.date else "",
        "value_date": str(getattr(e, "value_date", None) or e.date or ""),
        "journal": e.journal,
        "reference": e.reference,
        "label": e.label,
        "status": e.status,
        "fiscal_year": e.fiscal_year,
        "period": e.period,
        "client_id": client_id,
        "client_name": client_name,
        "client_code": client_code,
        "client_account": client_account,
        "observation": getattr(e, "observation", "") or "",
        "created_by": getattr(e, "created_by", None),
        "created_by_name": creator,
        "created_at": getattr(e, "created_at", ""),
        "total_debit": total_d,
        "total_credit": total_c,
        "debit_accounts": debit_accounts,
        "credit_accounts": credit_accounts,
        "lines": [
            {
                "id": l.id,
                "account_code": l.account_code,
                "label": l.label,
                "debit": l.debit,
                "credit": l.credit,
                "client_id": getattr(l, "client_id", None) or client_id,
                "client_name": line_clients.get(getattr(l, "client_id", None) or client_id, client_name),
            }
            for l in lines
        ],
    }


@router.get("/brouillard")
def list_brouillard(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    journal: Optional[str] = None,
    account_code: Optional[str] = None,
    reference: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    created_by: Optional[int] = None,
    display_scope: str = Query("commercial", pattern="^(commercial|all)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    from app.services.journal_query import apply_journal_display_scope

    query = apply_journal_display_scope(db.query(JournalEntry), display_scope)
    if status:
        query = query.filter(JournalEntry.status == status)
    else:
        query = query.filter(JournalEntry.status.in_(["brouillon", "validée"]))
    if journal:
        query = query.filter(JournalEntry.journal == journal)
    if reference:
        query = query.filter(JournalEntry.reference.ilike(f"%{reference}%"))
    if date_from:
        query = query.filter(JournalEntry.date >= date_from)
    if date_to:
        query = query.filter(JournalEntry.date <= date_to)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (JournalEntry.label.ilike(like)) | (JournalEntry.reference.ilike(like))
        )
    if created_by is not None:
        query = query.filter(JournalEntry.created_by == created_by)
    entries = query.order_by(JournalEntry.date.desc(), JournalEntry.id.desc()).offset(offset).limit(limit).all()
    result = []
    for e in entries:
        payload = _entry_payload(e, db)
        if account_code:
            if not any(l["account_code"].startswith(account_code) for l in payload["lines"]):
                continue
        result.append(payload)
    total = query.count()
    return {"items": result, "total": total, "offset": offset, "limit": limit}


@router.get("/journal-entries/{eid}")
def get_journal_entry(
    eid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    e = db.query(JournalEntry).filter(JournalEntry.id == eid).first()
    if not e:
        raise HTTPException(404)
    return _entry_payload(e, db)


@router.put("/journal-entries/{eid}")
def update_journal_entry(
    eid: int,
    data: JournalEntryUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("journal", "update")),
):
    entry = db.query(JournalEntry).filter(JournalEntry.id == eid).first()
    if not entry:
        raise HTTPException(404)
    snap = json.dumps(_entry_payload(entry, db), ensure_ascii=False)
    if data.date is not None:
        entry.date = data.date
    if data.value_date is not None and hasattr(entry, "value_date"):
        entry.value_date = data.value_date
    if data.journal is not None:
        entry.journal = data.journal
    if data.reference is not None:
        entry.reference = data.reference
    if data.label is not None:
        entry.label = data.label
    data_dump = data.model_dump(exclude_unset=True)
    if "client_id" in data_dump:
        entry.client_id = data_dump.get("client_id")
    if "observation" in data_dump:
        entry.observation = data_dump.get("observation") or ""
    if data.fiscal_year is not None:
        assert_fiscal_year_open(db, data.fiscal_year)
        entry.fiscal_year = data.fiscal_year
    elif data.lines is not None or data.date is not None:
        assert_fiscal_year_open(db, entry.fiscal_year)
    if data.period is not None:
        entry.period = data.period
    if data.lines is not None:
        lines_norm = normalize_journal_lines(data.lines)
        if not validate_entry_balance(lines_norm):
            raise HTTPException(400, "Écriture non équilibrée")
        db.query(JournalLine).filter(JournalLine.entry_id == eid).delete()
        for ln in lines_norm:
            db.add(JournalLine(
                entry_id=eid,
                account_code=ln["account_code"],
                label=ln["label"],
                debit=ln["debit"],
                credit=ln["credit"],
                client_id=ln.get("client_id") or entry.client_id,
            ))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    if hasattr(entry, "updated_at"):
        entry.updated_at = now
    if hasattr(entry, "updated_by"):
        entry.updated_by = user.id
    db.add(JournalEntryHistory(
        entry_id=eid,
        action="update",
        snapshot_json=snap[:8000],
        user_id=user.id,
        user_email=user.email,
        logged_at=now,
    ))
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "update", "compta", "journal_entry", eid, entry.label, uid, email, ip, old_value=snap[:500], new_value=data.model_dump_json()[:500])
    touch_context(db, user.id, {"journal": entry.journal or "OD"})
    db.commit()
    return {"ok": True, "entry": _entry_payload(entry, db)}


def _unlink_journal_entry_source(db: Session, entry: JournalEntry) -> None:
    """Quand une écriture générée automatiquement (facture, achat...) est supprimée,
    retire le pointeur journal_entry_id du document source pour qu'il ne se croie plus
    comptabilisé (sinon une re-comptabilisation ultérieure le considérerait à tort comme
    déjà posté, cf. dispatch_invoice_posting/dispatch_supplier_invoice_posting)."""
    if entry.source_type == "invoice" and entry.source_id:
        inv = db.query(Invoice).filter(Invoice.id == entry.source_id).first()
        if inv and inv.journal_entry_id == entry.id:
            inv.journal_entry_id = None
    elif entry.source_type == "supplier_invoice" and entry.source_id:
        sinv = db.query(SupplierInvoice).filter(SupplierInvoice.id == entry.source_id).first()
        if sinv and sinv.journal_entry_id == entry.id:
            sinv.journal_entry_id = None
    if entry.accounting_transaction_id:
        db.query(AccountingTransaction).filter(AccountingTransaction.id == entry.accounting_transaction_id).delete()
    elif entry.source_type:
        db.query(AccountingTransaction).filter(
            AccountingTransaction.source_type == entry.source_type,
            AccountingTransaction.source_id == entry.source_id,
        ).delete()


@router.delete("/journal-entries/{eid}")
def delete_journal_entry(
    eid: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("journal", "delete")),
):
    entry = db.query(JournalEntry).filter(JournalEntry.id == eid).first()
    if not entry:
        raise HTTPException(404)
    # Suppression autorisée quel que soit le statut (brouillon ou validée), à la demande
    # explicite de l'utilisateur — l'audit log ci-dessous conserve un instantané complet
    # de l'écriture avant suppression, donc la traçabilité n'est pas perdue.
    snap = json.dumps(_entry_payload(entry, db), ensure_ascii=False)
    _unlink_journal_entry_source(db, entry)
    db.query(JournalLine).filter(JournalLine.entry_id == eid).delete()
    # journal_entry_history.entry_id est une vraie contrainte FK (PRAGMA foreign_keys=ON) :
    # toute écriture déjà modifiée au moins une fois a une ligne d'historique, et la
    # suppression échouait silencieusement en IntegrityError sans ce nettoyage.
    db.query(JournalEntryHistory).filter(JournalEntryHistory.entry_id == eid).delete()
    db.delete(entry)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "delete", "compta", "journal_entry", eid, "", uid, email, ip, old_value=snap[:500])
    db.commit()
    return {"ok": True}


@router.get("/journal-entries/{eid}/history")
def journal_history(
    eid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    rows = (
        db.query(JournalEntryHistory)
        .filter(JournalEntryHistory.entry_id == eid)
        .order_by(JournalEntryHistory.id.desc())
        .limit(50)
        .all()
    )
    return [{"id": r.id, "action": r.action, "user_email": r.user_email, "logged_at": r.logged_at} for r in rows]


@router.post("/dates/change")
def api_change_date(
    body: DateChangeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("journal", "update")),
):
    uid, email, ip = _user_ctx(request, user)
    try:
        return change_entity_date(
            db,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            field_name=body.field_name,
            new_value=body.new_value,
            user_id=uid,
            user_email=email,
            ip=ip,
            detail=body.detail or "",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/dates/history/{entity_type}/{entity_id}")
def api_date_history(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return list_date_changes(db, entity_type, entity_id)


@router.get("/date-changes/recent")
def api_recent_date_changes(
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("audit", "view")),
):
    return list_recent_date_changes(db, limit=limit)


@router.get("/suggestions")
def api_suggestions(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("journal", "view")),
):
    return get_suggestions(db, user.id)


@router.post("/validate-lines")
def api_validate_lines(
    body: dict,
    _: User = Depends(require_action("journal", "view")),
):
    lines = normalize_journal_lines(body.get("lines"))
    entry_date = body.get("date")
    d = None
    if entry_date:
        from datetime import datetime as dt
        d = dt.strptime(str(entry_date)[:10], "%Y-%m-%d").date()
    return {"alerts": validate_entry_anomalies(lines, d)}


@router.get("/smart-context")
def api_smart_context(
    client_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    stock_item_id: Optional[int] = None,
    product_type: str = "SERVICE",
    doc_type: str = "invoice",
    db: Session = Depends(get_db),
    user: User = Depends(require_action("journal", "view")),
):
    return smart_lookup(
        db,
        user_id=user.id,
        client_id=client_id,
        supplier_id=supplier_id,
        stock_item_id=stock_item_id,
        product_type=product_type,
        doc_type=doc_type,
    )


@router.get("/entity-audit/{entity_type}/{entity_id}")
def entity_audit_timeline(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("audit", "view")),
):
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.id.desc())
        .limit(100)
        .all()
    )
    dates = list_date_changes(db, entity_type, entity_id)
    return {
        "audit": [
            {
                "action": l.action,
                "module": l.module,
                "detail": l.detail,
                "old_value": l.old_value,
                "new_value": l.new_value,
                "user_email": l.user_email,
                "logged_at": l.logged_at,
            }
            for l in logs
        ],
        "date_changes": dates,
    }


@router.get("/posting-status")
def accounting_posting_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    """Factures non comptabilisées, erreurs moteur, synthèse journal."""
    pending_inv = (
        db.query(Invoice)
        .filter(Invoice.status.in_(tuple(POSTING_STATUSES_INVOICE)))
        .filter((Invoice.journal_entry_id.is_(None)) | (Invoice.journal_entry_id == 0))
        .order_by(Invoice.date.desc())
        .limit(50)
        .all()
    )
    pending_sup = (
        db.query(SupplierInvoice)
        .filter(SupplierInvoice.status.in_(tuple(POSTING_STATUSES_PURCHASE)))
        .filter((SupplierInvoice.journal_entry_id.is_(None)) | (SupplierInvoice.journal_entry_id == 0))
        .order_by(SupplierInvoice.date.desc())
        .limit(50)
        .all()
    )
    errors = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.status == "error")
        .order_by(AccountingTransaction.id.desc())
        .limit(30)
        .all()
    )
    je_total = db.query(JournalEntry).count()
    je_valid = db.query(JournalEntry).filter(JournalEntry.status == "validée").count()
    je_draft = db.query(JournalEntry).filter(JournalEntry.status == "brouillon").count()
    return {
        "journal_entries": {"total": je_total, "validated": je_valid, "draft": je_draft},
        "pending_invoices": [
            {"id": i.id, "number": i.number, "status": i.status, "amount": i.amount, "date": str(i.date or "")}
            for i in pending_inv
        ],
        "pending_supplier_invoices": [
            {"id": i.id, "number": i.number, "status": i.status, "amount": i.amount, "date": str(i.date or "")}
            for i in pending_sup
        ],
        "errors": [
            {
                "source_type": t.source_type,
                "source_id": t.source_id,
                "label": t.label,
                "error_message": (t.error_message or "")[:500],
            }
            for t in errors
        ],
    }


@router.post("/posting/retry-all")
def accounting_retry_posting(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    """Relance la comptabilisation automatique sur les pièces en attente."""
    from app.services.accounting_hooks import dispatch_invoice_posting, dispatch_supplier_invoice_posting

    out = {"invoices": [], "supplier_invoices": []}
    for inv in (
        db.query(Invoice)
        .filter(Invoice.status.in_(tuple(POSTING_STATUSES_INVOICE)))
        .filter((Invoice.journal_entry_id.is_(None)) | (Invoice.journal_entry_id == 0))
        .all()
    ):
        r = dispatch_invoice_posting(db, inv, force=True)
        out["invoices"].append({"id": inv.id, "number": inv.number, **r})
    for sinv in (
        db.query(SupplierInvoice)
        .filter(SupplierInvoice.status.in_(tuple(POSTING_STATUSES_PURCHASE)))
        .filter((SupplierInvoice.journal_entry_id.is_(None)) | (SupplierInvoice.journal_entry_id == 0))
        .all()
    ):
        r = dispatch_supplier_invoice_posting(db, sinv, force=True)
        out["supplier_invoices"].append({"id": sinv.id, "number": sinv.number, **r})
    return out
