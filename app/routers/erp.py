"""API ERP étendue — achats, trésorerie, compta, RH, budget, BI, Excel, audit."""
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user, require_permission
from app.api_guards import require_action
from app.models import User, Account, Transaction, Client
from app import schemas
from app import schemas_erp as se
from app.models_erp import (
    Supplier, SupplierInvoice, BankAccount, TreasuryMovement,
    JournalEntry, JournalLine, CostCenter, Budget, Employee, LeaveRequest,
    AuditLog, UserDashboard,
)
from app.models_accounting import SupplierInvoiceLine
from app.services.audit_log import log_audit
from app.tenant_service import get_company_id, filter_by_company, get_entity_or_404, stamp_company
from app.services.accounting_reports import (
    grand_livre, balance_generale, bilan_simplifie, validate_entry_balance,
    compte_de_resultat, financial_ratios, flux_tresorerie,
    balance_auxiliaire_clients, balance_auxiliaire_suppliers,
)
from app.purchase_guards import assert_supplier_invoice_mutable, assert_supplier_invoice_deletable
from app.fiscal_service import assert_fiscal_year_open, close_fiscal_year, reopen_fiscal_year, list_closed_fiscal_years
from app.services.account_guards import assert_account_deletable
from app.services.dashboard_service import full_dashboard
from app.services import excel_export
from app.services.purchase_workflow_service import evaluate_three_way_match

router = APIRouter(
    prefix="/api/erp",
    tags=["erp"],
    dependencies=[Depends(get_current_user)],
)


def _user_ctx(request: Request, user: User):
    return user.id, user.email, request.client.host if request.client else ""


# ——— Dashboard ———
@router.get("/dashboard/full")
def dashboard_full(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("dashboard", "view")),
):
    return full_dashboard(db)


@router.get("/dashboard/widgets")
def get_widgets(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    row = db.query(UserDashboard).filter(UserDashboard.user_id == user.id).first()
    import json
    if not row:
        return {"widgets": ["ca", "result", "creances", "dettes", "stock", "pipeline", "tresorerie"]}
    return {"widgets": json.loads(row.widgets_json or "[]")}


@router.put("/dashboard/widgets")
def save_widgets(
    body: se.DashboardWidgetsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import json
    row = db.query(UserDashboard).filter(UserDashboard.user_id == user.id).first()
    if not row:
        row = UserDashboard(user_id=user.id)
        db.add(row)
    row.widgets_json = json.dumps(body.widgets)
    db.commit()
    return {"ok": True, "widgets": body.widgets}


# ——— Fournisseurs ———
@router.get("/suppliers", response_model=List[se.SupplierOut])
def list_suppliers(
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("suppliers", "view")),
):
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(Supplier), Supplier, cid).order_by(Supplier.name)
    if hasattr(Supplier, "is_archived"):
        q = q.filter((Supplier.is_archived == False) | (Supplier.is_archived.is_(None)))  # noqa: E712
    return q.offset(offset).limit(limit).all()


@router.post("/suppliers", response_model=se.SupplierOut)
def create_supplier(
    data: se.SupplierIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("suppliers", "create")),
):
    cid = get_company_id(db, user)
    obj = Supplier(**data.model_dump())
    stamp_company(obj, cid)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    from app.services.auxiliary_account_service import ensure_supplier_auxiliary
    ensure_supplier_auxiliary(db, obj)
    db.commit()
    db.refresh(obj)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "create", "achats", "supplier", obj.id, obj.name, uid, email, ip)
    db.commit()
    return obj


@router.put("/suppliers/{sid}", response_model=se.SupplierOut)
def update_supplier(
    sid: int,
    data: se.SupplierIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("suppliers", "update")),
):
    cid = get_company_id(db, user)
    obj = get_entity_or_404(db, Supplier, sid, cid, "Fournisseur")
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "update", "achats", "supplier", obj.id, obj.name, uid, email, ip)
    db.commit()
    return obj


@router.delete("/suppliers/{sid}")
def delete_supplier(
    sid: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("suppliers", "delete")),
):
    obj = get_entity_or_404(db, Supplier, sid, get_company_id(db, user), "Fournisseur")
    n = db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == sid).count()
    uid, email, ip = _user_ctx(request, user)
    if n:
        if hasattr(obj, "is_archived"):
            obj.is_archived = True
            obj.status = "inactif"
            db.commit()
            log_audit(db, "archive", "achats", "supplier", sid, obj.name, uid, email, ip)
            return {"ok": True, "archived": True}
        raise HTTPException(400, f"Impossible : {n} facture(s) fournisseur liée(s)")
    log_audit(db, "delete", "achats", "supplier", sid, obj.name, uid, email, ip)
    db.delete(obj)
    db.commit()
    return {"ok": True}


class BulkSuppliersIn(BaseModel):
    ids: List[int]
    action: str
    status: Optional[str] = None


@router.post("/suppliers/bulk")
def bulk_suppliers(
    body: BulkSuppliersIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("suppliers", "delete")),
):
    if not body.ids:
        raise HTTPException(400, "Aucun fournisseur sélectionné")
    action = (body.action or "").strip().lower()
    if action not in ("archive", "activate", "deactivate", "set_status", "delete"):
        raise HTTPException(400, "Action invalide")
    if action == "set_status" and body.status not in ("actif", "inactif"):
        raise HTTPException(400, "Statut invalide")
    company_id = get_company_id(db, user)
    uid, email, ip = _user_ctx(request, user)
    processed = 0
    for sid in body.ids:
        obj = filter_by_company(db.query(Supplier).filter(Supplier.id == sid), Supplier, company_id).first()
        if not obj:
            continue
        if action == "archive":
            if hasattr(obj, "is_archived"):
                obj.is_archived = True
            obj.status = "inactif"
            log_audit(db, "archive", "achats", "supplier", sid, obj.name, uid, email, ip)
            processed += 1
        elif action == "activate":
            if hasattr(obj, "is_archived"):
                obj.is_archived = False
            obj.status = "actif"
            processed += 1
        elif action == "deactivate":
            obj.status = "inactif"
            processed += 1
        elif action == "set_status":
            obj.status = body.status
            processed += 1
        elif action == "delete":
            n = db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == sid).count()
            if n and hasattr(obj, "is_archived"):
                obj.is_archived = True
                obj.status = "inactif"
                log_audit(db, "archive", "achats", "supplier", sid, obj.name, uid, email, ip)
            elif not n:
                log_audit(db, "delete", "achats", "supplier", sid, obj.name, uid, email, ip)
                db.delete(obj)
            processed += 1
    db.commit()
    return {"ok": True, "processed": processed, "message": f"{processed} fournisseur(s) traité(s)"}


# ——— Factures fournisseurs ———
@router.get("/supplier-invoices", response_model=List[se.SupplierInvoiceOut])
def list_supplier_invoices(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "view")),
):
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(SupplierInvoice), SupplierInvoice, cid)
    return q.order_by(SupplierInvoice.date.desc()).offset(offset).limit(limit).all()


@router.post("/supplier-invoices", response_model=se.SupplierInvoiceOut)
def create_supplier_invoice(
    data: se.SupplierInvoiceIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "create")),
):
    from app.date_service import apply_invoice_dates, compute_due_date, stamp_create

    cid = get_company_id(db, user)
    payload = data.model_dump()
    if payload.get("date") and not payload.get("due_date"):
        payload["due_date"] = compute_due_date(payload["date"], payload.get("payment_terms_days", 30))
    obj = SupplierInvoice(**payload)
    stamp_company(obj, cid)
    stamp_create(obj, user)
    apply_invoice_dates(obj, payload, is_create=True)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    if obj.purchase_order_id:
        evaluate_three_way_match(db, obj.id)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "create", "achats", "supplier_invoice", obj.id, obj.number or "", uid, email, ip)
    db.commit()
    if obj.status in ("validée", "payée", "en retard"):
        from app.services.accounting_hooks import dispatch_supplier_invoice_posting
        dispatch_supplier_invoice_posting(db, obj)
    return obj


@router.put("/supplier-invoices/{iid}", response_model=se.SupplierInvoiceOut)
def update_supplier_invoice(
    iid: int,
    data: se.SupplierInvoiceIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "update")),
):
    obj = get_entity_or_404(db, SupplierInvoice, iid, get_company_id(db, user), "Facture fournisseur")
    assert_supplier_invoice_mutable(obj, user, db)
    old_status = obj.status
    had_posting = bool(getattr(obj, "journal_entry_id", None))
    payload = data.model_dump()
    if payload.get("date") and not payload.get("due_date"):
        from app.date_service import compute_due_date
        payload["due_date"] = compute_due_date(payload["date"], payload.get("payment_terms_days", 30))
    for k, v in payload.items():
        setattr(obj, k, v)
    from app.date_service import apply_invoice_dates, stamp_update
    stamp_update(obj, user)
    apply_invoice_dates(obj, payload)
    db.commit()
    db.refresh(obj)
    if obj.status in ("validée", "payée", "en retard") and old_status == "brouillon":
        if obj.purchase_order_id:
            match = evaluate_three_way_match(db, obj.id)
            if match.get("status") != "matched":
                raise HTTPException(
                    400,
                    f"3-way matching requis avant validation facture fournisseur ({match.get('detail')})",
                )
    if obj.status in ("validée", "payée", "en retard"):
        from app.services.accounting_hooks import dispatch_supplier_invoice_posting
        force_repost = had_posting or old_status in ("validée", "payée", "en retard")
        dispatch_supplier_invoice_posting(db, obj, force=force_repost)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "update", "achats", "supplier_invoice", obj.id, obj.number or "", uid, email, ip)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/supplier-invoices/{iid}/lines", response_model=List[se.SupplierInvoiceLineOut])
def list_supplier_invoice_lines(
    iid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "view")),
):
    from app.models_accounting import SupplierInvoiceLine
    get_entity_or_404(db, SupplierInvoice, iid, get_company_id(db, user), "Facture fournisseur")
    return db.query(SupplierInvoiceLine).filter(
        SupplierInvoiceLine.supplier_invoice_id == iid
    ).order_by(SupplierInvoiceLine.position).all()


@router.put("/supplier-invoices/{iid}/lines")
def replace_supplier_invoice_lines(
    iid: int,
    body: List[se.SupplierInvoiceLineIn],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "update")),
):
    from app.models_accounting import SupplierInvoiceLine
    inv = get_entity_or_404(db, SupplierInvoice, iid, get_company_id(db, user), "Facture fournisseur")
    assert_supplier_invoice_mutable(inv, user, db)
    had_posting = bool(getattr(inv, "journal_entry_id", None))
    db.query(SupplierInvoiceLine).filter(SupplierInvoiceLine.supplier_invoice_id == iid).delete()
    total = 0.0
    for i, ln in enumerate(body):
        row = SupplierInvoiceLine(supplier_invoice_id=iid, position=i, **ln.model_dump())
        db.add(row)
        ht = (ln.quantity or 0) * (ln.unit_price or 0)
        tva = ht * float(ln.vat_rate or 0) / 100
        total += ht + tva
    inv.amount = round(total, 2)
    from app.date_service import stamp_update
    stamp_update(inv, user)
    db.commit()
    db.refresh(inv)
    if inv.status in ("validée", "payée", "en retard"):
        from app.services.accounting_hooks import dispatch_supplier_invoice_posting
        dispatch_supplier_invoice_posting(db, inv, force=had_posting)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "update", "achats", "supplier_invoice_lines", inv.id, inv.number or "", uid, email, ip)
    db.commit()
    return {"ok": True, "amount": inv.amount, "lines": len(body)}


@router.delete("/supplier-invoices/{iid}")
def delete_supplier_invoice(
    iid: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "delete")),
):
    obj = get_entity_or_404(db, SupplierInvoice, iid, get_company_id(db, user), "Facture fournisseur")
    assert_supplier_invoice_deletable(obj, user, db)
    from app.services.accounting_hooks import unpost_source
    unpost_source(db, "supplier_invoice", iid)
    uid, email, ip = _user_ctx(request, user)
    db.query(SupplierInvoiceLine).filter(SupplierInvoiceLine.supplier_invoice_id == iid).delete()
    log_audit(db, "delete", "achats", "supplier_invoice", iid, obj.number or "", uid, email, ip)
    db.delete(obj)
    db.commit()
    return {"ok": True}


class BulkSupplierInvoicesIn(BaseModel):
    ids: List[int]
    action: str


@router.post("/supplier-invoices/bulk")
def bulk_supplier_invoices(
    body: BulkSupplierInvoicesIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "delete")),
):
    if not body.ids:
        raise HTTPException(400, "Aucune facture sélectionnée")
    action = (body.action or "").strip().lower()
    if action != "delete":
        raise HTTPException(400, "Action invalide")
    company_id = get_company_id(db, user)
    uid, email, ip = _user_ctx(request, user)
    processed = 0
    errors: List[str] = []
    for iid in body.ids:
        obj = filter_by_company(db.query(SupplierInvoice).filter(SupplierInvoice.id == iid), SupplierInvoice, company_id).first()
        if not obj:
            errors.append(f"Facture #{iid} introuvable")
            continue
        try:
            assert_supplier_invoice_deletable(obj, user, db)
            from app.services.accounting_hooks import unpost_source
            unpost_source(db, "supplier_invoice", iid)
            db.query(SupplierInvoiceLine).filter(SupplierInvoiceLine.supplier_invoice_id == iid).delete()
            log_audit(db, "delete", "achats", "supplier_invoice", iid, obj.number or "", uid, email, ip)
            db.delete(obj)
            processed += 1
        except HTTPException as e:
            errors.append(f"{obj.number or iid}: {e.detail}")
    db.commit()
    msg = f"{processed} facture(s) fournisseur supprimée(s)"
    if errors:
        msg += f" — {len(errors)} ignorée(s)"
    return {"ok": True, "processed": processed, "errors": errors, "message": msg}


# ——— Trésorerie ———
@router.get("/bank-accounts", response_model=List[se.BankAccountOut])
def list_banks(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "view")),
):
    return db.query(BankAccount).all()


@router.post("/bank-accounts", response_model=se.BankAccountOut)
def create_bank(
    data: se.BankAccountIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "create")),
):
    obj = BankAccount(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/bank-accounts/{bid}", response_model=se.BankAccountOut)
def update_bank(
    bid: int,
    data: se.BankAccountIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "update")),
):
    obj = db.query(BankAccount).filter(BankAccount.id == bid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/treasury-movements", response_model=List[se.TreasuryMovementOut])
def list_treasury(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "view")),
):
    return db.query(TreasuryMovement).order_by(TreasuryMovement.date.desc()).all()


@router.post("/treasury-movements", response_model=se.TreasuryMovementOut)
def create_treasury(
    data: se.TreasuryMovementIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "create")),
):
    obj = TreasuryMovement(**data.model_dump())
    db.add(obj)
    if obj.bank_account_id and obj.type in ("banque_entree", "banque_sortie"):
        bank = db.query(BankAccount).filter(BankAccount.id == obj.bank_account_id).first()
        if bank:
            if obj.type == "banque_entree":
                bank.balance = (bank.balance or 0) + (obj.amount or 0)
            else:
                bank.balance = (bank.balance or 0) - (obj.amount or 0)
    db.commit()
    db.refresh(obj)
    return obj


# ——— Comptabilité ———
@router.get("/accounts")
def list_accounts_full(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return db.query(Account).order_by(Account.code).all()


@router.put("/accounts/{aid}")
def update_account(
    aid: int,
    data: schemas.AccountIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "update")),
):
    obj = db.query(Account).filter(Account.id == aid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    return obj


@router.delete("/accounts/{aid}")
def delete_account(
    aid: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("journal", "delete")),
):
    obj = db.query(Account).filter(Account.id == aid).first()
    if not obj:
        raise HTTPException(404)
    assert_account_deletable(db, obj.code)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "delete", "compta", "account", aid, obj.code, uid, email, ip)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.post("/accounts/import-pcg")
def import_pcg(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    """Import plan comptable SYSCOHADA révisé (remplace l'ancien PCG simplifié)."""
    from app.syscohada.service import import_syscohada_chart
    return import_syscohada_chart(db)


@router.post("/accounts/import-syscohada")
def import_syscohada(
    force: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    from app.syscohada.service import import_syscohada_chart
    return import_syscohada_chart(db, force=force)


@router.get("/journal-entries")
def list_journal_entries(
    display_scope: str = Query("commercial", pattern="^(commercial|all)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    from app.services.journal_query import apply_journal_display_scope

    q = apply_journal_display_scope(db.query(JournalEntry), display_scope)
    entries = q.order_by(JournalEntry.date.desc()).all()
    entry_ids = [e.id for e in entries]
    lines_by_entry: dict[int, list[JournalLine]] = {eid: [] for eid in entry_ids}
    if entry_ids:
        for ln in db.query(JournalLine).filter(JournalLine.entry_id.in_(entry_ids)).all():
            lines_by_entry.setdefault(ln.entry_id, []).append(ln)

    client_ids = {getattr(e, "client_id", None) for e in entries}
    for lns in lines_by_entry.values():
        client_ids.update(getattr(l, "client_id", None) for l in lns)
    client_ids.discard(None)
    client_names = {}
    if client_ids:
        client_names = {c.id: c.name for c in db.query(Client).filter(Client.id.in_(client_ids)).all()}

    result = []
    for e in entries:
        lines = lines_by_entry.get(e.id, [])
        entry_client_id = getattr(e, "client_id", None)
        # Sans client_id propre à l'écriture, on retombe sur celui de la 1re ligne qui en a un
        # (cas des écritures saisies ligne par ligne où seule la ligne porte le client).
        if not entry_client_id:
            entry_client_id = next((getattr(l, "client_id", None) for l in lines if getattr(l, "client_id", None)), None)
        result.append({
            "id": e.id, "date": str(e.date) if e.date else "", "journal": e.journal,
            "reference": e.reference, "label": e.label, "status": e.status,
            "client_id": entry_client_id,
            "client_name": client_names.get(entry_client_id, ""),
            "lines": [{
                "account_code": l.account_code, "debit": l.debit, "credit": l.credit, "label": l.label,
                "client_id": getattr(l, "client_id", None),
                "client_name": client_names.get(getattr(l, "client_id", None), ""),
            } for l in lines],
        })
    return result


@router.post("/journal-entries")
def create_journal_entry(
    data: se.JournalEntryIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("journal", "create")),
):
    if not validate_entry_balance([l.model_dump() for l in data.lines]):
        raise HTTPException(400, "Écriture non équilibrée (débit ≠ crédit)")
    assert_fiscal_year_open(db, data.fiscal_year)
    entry = JournalEntry(
        date=data.date or date.today(),
        value_date=data.value_date or data.date or date.today(),
        journal=data.journal,
        reference=data.reference,
        label=data.label,
        status=data.status,
        fiscal_year=data.fiscal_year,
        period=data.period,
        client_id=getattr(data, "client_id", None),
        observation=getattr(data, "observation", "") or "",
        created_by=user.id,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    db.add(entry)
    db.flush()
    for ln in data.lines:
        payload = ln.model_dump()
        if not payload.get("client_id"):
            payload["client_id"] = entry.client_id
        db.add(JournalLine(entry_id=entry.id, **payload))
    db.commit()
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "create", "compta", "journal_entry", entry.id, entry.label, uid, email, ip)
    return {"ok": True, "id": entry.id}


@router.post("/journal-entries/{eid}/validate")
def validate_journal(
    eid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "validate")),
):
    entry = db.query(JournalEntry).filter(JournalEntry.id == eid).first()
    if not entry:
        raise HTTPException(404)
    lines = db.query(JournalLine).filter(JournalLine.entry_id == eid).all()
    if not validate_entry_balance([{"debit": l.debit, "credit": l.credit} for l in lines]):
        raise HTTPException(400, "Écriture non équilibrée")
    entry.status = "validée"
    db.commit()
    return {"ok": True}


@router.post("/journal-entries/{eid}/reverse")
def reverse_journal(
    eid: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "approve")),
):
    from app.services.journal_reversal_service import reverse_journal_entry
    try:
        return reverse_journal_entry(db, eid, label=body.get("label") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/reports/grand-livre")
def report_grand_livre(
    account_code: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return grand_livre(db, account_code)


@router.get("/reports/balance")
def report_balance(
    fiscal_year: Optional[int] = None,
    period: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return balance_generale(db, fiscal_year=fiscal_year, period=period)


@router.get("/reports/bilan")
def report_bilan(
    fiscal_year: Optional[int] = None,
    period: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return bilan_simplifie(db, fiscal_year=fiscal_year, period=period)


@router.get("/reports/compte-resultat")
def report_compte_resultat(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return compte_de_resultat(db, fiscal_year=fiscal_year)


@router.get("/reports/ratios")
def report_ratios(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return financial_ratios(db)


@router.get("/finance-summary")
def finance_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("accounting", "view")),
):
    """Synthèse financière temps réel — KPI alimentés par la base."""
    from app.services.dashboard_service import full_dashboard

    ratios = financial_ratios(db)
    bilan = bilan_simplifie(db)
    cr = compte_de_resultat(db)
    flux = flux_tresorerie(db)
    dash = full_dashboard(db)
    banks = db.query(BankAccount).order_by(BankAccount.name).all()
    return {
        "ratios": ratios,
        "bilan": bilan,
        "compte_resultat": cr,
        "flux": flux,
        "treasury_total": ratios.get("tresorerie", 0),
        "bank_accounts": [
            {"id": b.id, "name": b.name, "bank_name": b.bank_name, "balance": b.balance or 0, "currency": b.currency or "XOF"}
            for b in banks
        ],
        "ca_total": dash.get("ca_total", 0),
        "creances_clients": dash.get("creances", ratios.get("creances", 0)),
        "dettes_fournisseurs": dash.get("dettes", ratios.get("dettes", 0)),
        "resultat_net": cr.get("net_result", 0),
        "updated_at": __import__("datetime").datetime.now().isoformat(),
    }


@router.get("/reports/flux-tresorerie")
def report_flux(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return flux_tresorerie(db)


@router.post("/journal-entries/from-transaction/{tid}")
def journal_from_transaction(
    tid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    """Génère une écriture OD depuis une transaction existante."""
    t = db.query(Transaction).filter(Transaction.id == tid).first()
    if not t:
        raise HTTPException(404)
    from app.syscohada.constants import DEFAULT_ACCOUNTS
    acc = dict(DEFAULT_ACCOUNTS)
    amount = t.amount or 0
    if t.type == "produit":
        lines = [
            {"account_code": acc["bank"], "debit": amount, "credit": 0, "label": t.label},
            {"account_code": t.account_code or acc["sales_services"], "debit": 0, "credit": amount, "label": t.label},
        ]
        journal = "VE"
    else:
        lines = [
            {"account_code": t.account_code or acc["purchases_goods"], "debit": amount, "credit": 0, "label": t.label},
            {"account_code": acc["bank"], "debit": 0, "credit": amount, "label": t.label},
        ]
        journal = "AC"
    entry = JournalEntry(date=t.date or date.today(), journal=journal, reference=t.reference or f"T{tid}", label=t.label, status="validée")
    db.add(entry)
    db.flush()
    for ln in lines:
        db.add(JournalLine(entry_id=entry.id, account_code=ln["account_code"], debit=ln["debit"], credit=ln["credit"], label=ln["label"]))
    db.commit()
    return {"ok": True, "entry_id": entry.id}


# ——— Analytique & budget ———
@router.get("/cost-centers", response_model=List[se.CostCenterOut])
def list_cost_centers(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "view")),
):
    q = db.query(CostCenter)
    if hasattr(CostCenter, "is_active"):
        q = q.filter((CostCenter.is_active == True) | (CostCenter.is_active.is_(None)))  # noqa: E712
    return q.order_by(CostCenter.code).all()


@router.post("/cost-centers", response_model=se.CostCenterOut)
def create_cost_center(
    data: se.CostCenterIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "create")),
):
    obj = CostCenter(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


class BulkCostCentersIn(BaseModel):
    ids: List[int]
    action: str = "archive"


@router.post("/cost-centers/bulk")
def bulk_cost_centers(
    body: BulkCostCentersIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "delete")),
):
    if not body.ids:
        raise HTTPException(400, "Aucun centre sélectionné")
    action = (body.action or "archive").strip().lower()
    if action not in ("archive", "activate", "delete"):
        raise HTTPException(400, "Action invalide")
    count = 0
    for cid in body.ids:
        obj = db.query(CostCenter).filter(CostCenter.id == cid).first()
        if not obj:
            continue
        if action == "archive":
            obj.is_active = False
        elif action == "activate":
            obj.is_active = True
        elif action == "delete":
            db.delete(obj)
        count += 1
    db.commit()
    return {"ok": True, "processed": count, "message": f"{count} centre(s) traité(s)"}


@router.put("/cost-centers/{cid}", response_model=se.CostCenterOut)
def update_cost_center(
    cid: int,
    data: se.CostCenterIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "update")),
):
    obj = db.query(CostCenter).filter(CostCenter.id == cid).first()
    if not obj:
        raise HTTPException(404, "Centre introuvable")
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/cost-centers/{cid}")
def delete_cost_center(
    cid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "delete")),
):
    obj = db.query(CostCenter).filter(CostCenter.id == cid).first()
    if not obj:
        raise HTTPException(404, "Centre introuvable")
    obj.is_active = False
    db.commit()
    return {"ok": True, "message": f"Centre « {obj.name} » archivé"}


@router.get("/budgets", response_model=List[se.BudgetOut])
def list_budgets(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "view")),
):
    return db.query(Budget).filter(Budget.status != "archivé").order_by(Budget.year.desc(), Budget.name).all()


@router.post("/budgets", response_model=se.BudgetOut)
def create_budget(
    data: se.BudgetIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "create")),
):
    obj = Budget(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


class BulkBudgetsIn(BaseModel):
    ids: List[int]
    action: str = "archive"
    status: Optional[str] = None


@router.post("/budgets/bulk")
def bulk_budgets(
    body: BulkBudgetsIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "delete")),
):
    if not body.ids:
        raise HTTPException(400, "Aucun budget sélectionné")
    action = (body.action or "archive").strip().lower()
    if action not in ("archive", "activate", "delete", "set_status"):
        raise HTTPException(400, "Action invalide")
    count = 0
    for bid in body.ids:
        obj = db.query(Budget).filter(Budget.id == bid).first()
        if not obj:
            continue
        if action == "archive":
            obj.status = "archivé"
        elif action == "activate":
            obj.status = "actif"
        elif action == "set_status" and body.status:
            obj.status = body.status
        elif action == "delete":
            db.delete(obj)
        count += 1
    db.commit()
    return {"ok": True, "processed": count, "message": f"{count} budget(s) traité(s)"}


@router.put("/budgets/{bid}", response_model=se.BudgetOut)
def update_budget(
    bid: int,
    data: se.BudgetIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "update")),
):
    obj = db.query(Budget).filter(Budget.id == bid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    obj.amount_actual = obj.amount_actual or 0
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/budgets/{bid}")
def delete_budget(
    bid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("analytic", "delete")),
):
    obj = db.query(Budget).filter(Budget.id == bid).first()
    if not obj:
        raise HTTPException(404, "Budget introuvable")
    obj.status = "archivé"
    db.commit()
    return {"ok": True, "message": f"Budget « {obj.name} » archivé"}


# ——— RH ———
@router.get("/hr/overview")
def hr_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "view")),
):
    from collections import Counter
    from app.models_accounting import PayrollRun

    employees = db.query(Employee).all()
    leaves = db.query(LeaveRequest).all()
    runs = db.query(PayrollRun).order_by(
        PayrollRun.period_year.desc(), PayrollRun.period_month.desc()
    ).limit(6).all()
    active = [e for e in employees if (e.status or "") == "actif"]
    depts = Counter((e.department or "—").strip() or "—" for e in active)
    pending_leaves = [l for l in leaves if (l.status or "") == "en attente"]
    masse = sum(float(e.salary_base or 0) for e in active)
    last_run = runs[0] if runs else None
    return {
        "headcount": len(employees),
        "active_count": len(active),
        "masse_salariale": round(masse, 2),
        "pending_leaves": len(pending_leaves),
        "departments": [{"name": k, "count": v} for k, v in depts.most_common(12)],
        "last_payroll": {
            "id": last_run.id,
            "period": f"{last_run.period_month:02d}/{last_run.period_year}",
            "status": last_run.status,
            "total_net": last_run.total_net,
        } if last_run else None,
        "payroll_runs": [
            {
                "id": r.id,
                "period_year": r.period_year,
                "period_month": r.period_month,
                "status": r.status,
                "total_gross": r.total_gross,
                "total_net": r.total_net,
                "total_charges": r.total_charges,
            }
            for r in runs
        ],
    }


@router.get("/employees", response_model=List[se.EmployeeOut])
def list_employees(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "view")),
):
    return db.query(Employee).order_by(Employee.lastname).all()


@router.post("/employees", response_model=se.EmployeeOut)
def create_employee(
    data: se.EmployeeIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "create")),
):
    obj = Employee(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/employees/{eid}", response_model=se.EmployeeOut)
def update_employee(
    eid: int,
    data: se.EmployeeIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "update")),
):
    obj = db.query(Employee).filter(Employee.id == eid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/employees/{eid}", response_model=se.EmployeeOut)
def get_employee(
    eid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "view")),
):
    obj = db.query(Employee).filter(Employee.id == eid).first()
    if not obj:
        raise HTTPException(404)
    return obj


@router.delete("/employees/{eid}")
def delete_employee(
    eid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "delete")),
):
    obj = db.query(Employee).filter(Employee.id == eid).first()
    if not obj:
        raise HTTPException(404)
    db.query(LeaveRequest).filter(LeaveRequest.employee_id == eid).delete()
    db.delete(obj)
    db.commit()
    return {"ok": True, "message": "Employé supprimé"}


@router.get("/leave-requests", response_model=List[se.LeaveRequestOut])
def list_leaves(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "view")),
):
    return db.query(LeaveRequest).all()


@router.post("/leave-requests", response_model=se.LeaveRequestOut)
def create_leave(
    data: se.LeaveRequestIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "create")),
):
    obj = LeaveRequest(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/leave-requests/{lid}/status")
def update_leave_status(
    lid: int,
    status: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "update")),
):
    obj = db.query(LeaveRequest).filter(LeaveRequest.id == lid).first()
    if not obj:
        raise HTTPException(404)
    obj.status = status
    db.commit()
    return {"ok": True}


@router.put("/leave-requests/{lid}", response_model=se.LeaveRequestOut)
def update_leave(
    lid: int,
    data: se.LeaveRequestIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "update")),
):
    obj = db.query(LeaveRequest).filter(LeaveRequest.id == lid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/leave-requests/{lid}")
def delete_leave(
    lid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "delete")),
):
    obj = db.query(LeaveRequest).filter(LeaveRequest.id == lid).first()
    if not obj:
        raise HTTPException(404)
    db.delete(obj)
    db.commit()
    return {"ok": True, "message": "Demande de congé supprimée"}


# ——— Audit ———
@router.get("/audit-logs", response_model=List[se.AuditLogOut])
def list_audit(
    limit: int = 200,
    module: Optional[str] = None,
    action: Optional[str] = None,
    user_email: Optional[str] = None,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit.view")),
):
    query = db.query(AuditLog)
    if module:
        query = query.filter(AuditLog.module == module)
    if action:
        query = query.filter(AuditLog.action == action)
    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f"%{user_email}%"))
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if ip_address:
        query = query.filter(AuditLog.ip_address.ilike(f"%{ip_address}%"))
    if created_from:
        try:
            from datetime import date as date_cls
            d = date_cls.fromisoformat(created_from[:10])
            query = query.filter(AuditLog.created_at >= d)
        except Exception:
            raise HTTPException(400, "created_from invalide (format YYYY-MM-DD)")
    if created_to:
        try:
            from datetime import date as date_cls
            d = date_cls.fromisoformat(created_to[:10])
            query = query.filter(AuditLog.created_at <= d)
        except Exception:
            raise HTTPException(400, "created_to invalide (format YYYY-MM-DD)")
    if q:
        query = query.filter(
            (AuditLog.detail.ilike(f"%{q}%"))
            | (AuditLog.old_value.ilike(f"%{q}%"))
            | (AuditLog.new_value.ilike(f"%{q}%"))
            | (AuditLog.user_email.ilike(f"%{q}%"))
            | (AuditLog.entity_type.ilike(f"%{q}%"))
        )
    return query.order_by(AuditLog.id.desc()).limit(min(limit, 1000)).all()


@router.get("/audit-logs/user-activity")
def user_activity(
    days: int = 30,
    user_id: Optional[int] = None,
    user_email: Optional[str] = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit.view")),
):
    from app.services.user_activity_service import user_activity_report
    return user_activity_report(
        db,
        days=days,
        user_id=user_id,
        user_email=user_email,
        limit=limit,
    )


@router.post("/activity-log")
def log_ui_activity(
    data: se.UiActivityIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ip = request.client.host if request.client else ""
    ua = (request.headers.get("user-agent", "") or "")[:200]
    log_audit(
        db,
        data.action or "navigate",
        data.module or "ui",
        entity_type="page",
        detail=(data.detail or "")[:500],
        user_id=user.id,
        user_email=user.email or "",
        ip=ip,
        user_agent=ua,
    )
    db.commit()
    return {"ok": True}


@router.get("/audit-logs/export")
def export_audit_csv(
    limit: int = 2000,
    module: Optional[str] = None,
    action: Optional[str] = None,
    user_email: Optional[str] = None,
    user_id: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit.view")),
):
    import csv
    import io
    query = db.query(AuditLog)
    if module:
        query = query.filter(AuditLog.module == module)
    if action:
        query = query.filter(AuditLog.action == action)
    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f"%{user_email}%"))
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if created_from:
        try:
            from datetime import date as date_cls
            d = date_cls.fromisoformat(created_from[:10])
            query = query.filter(AuditLog.created_at >= d)
        except Exception:
            pass
    if created_to:
        try:
            from datetime import date as date_cls
            d = date_cls.fromisoformat(created_to[:10])
            query = query.filter(AuditLog.created_at <= d)
        except Exception:
            pass
    rows = query.order_by(AuditLog.id.desc()).limit(min(limit, 5000)).all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Date/heure", "Utilisateur", "Module", "Action", "Entité", "Entité ID", "Ancienne valeur", "Nouvelle valeur", "IP", "Détail"])
    for r in rows:
        ts = r.logged_at or (str(r.created_at) if r.created_at else "")
        w.writerow([
            ts, r.user_email, r.module, r.action, r.entity_type,
            r.entity_id or "", r.old_value or "", r.new_value or "", r.ip_address or "", (r.detail or "")[:500],
        ])
    return Response(
        buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_peya.csv"'},
    )


# ——— Export Excel ———
EXPORTERS = {
    "clients": excel_export.export_clients,
    "invoices": excel_export.export_invoices,
    "quotes": excel_export.export_quotes,
    "devis": excel_export.export_quotes,
    "transactions": excel_export.export_transactions,
    "journal_entries": excel_export.export_journal_entries,
    "journal-entries": excel_export.export_journal_entries,
    "balance": excel_export.export_balance,
    "grand-livre": excel_export.export_grand_livre,
    "stock": excel_export.export_stock,
    "suppliers": excel_export.export_suppliers,
    "employees": excel_export.export_employees,
    "recurring": excel_export.export_recurring,
}


@router.get("/export/{kind}")
def export_excel(
    kind: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("exports", "export")),
):
    fn = EXPORTERS.get(kind)
    if not fn:
        raise HTTPException(404, "Export inconnu")
    data = fn(db)
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="peya_{kind}.xlsx"'},
    )


# ——— Balance auxiliaire ———
@router.get("/reports/balance-auxiliaire/clients")
def report_aux_clients(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return balance_auxiliaire_clients(db)


@router.get("/reports/balance-auxiliaire/suppliers")
def report_aux_suppliers(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return balance_auxiliaire_suppliers(db)


# ——— Exercices fiscaux ———
@router.get("/fiscal/closed-years")
def fiscal_closed(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("settings", "view")),
):
    return {"closed_years": list_closed_fiscal_years(db)}


@router.post("/fiscal/close/{year}")
def fiscal_close_year(
    year: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("settings", "update")),
):
    closed = close_fiscal_year(db, year)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "validate", "compta", "fiscal_year", year, f"Clôture {year}", uid, email, ip)
    db.commit()
    return {"ok": True, "closed_years": closed}


@router.post("/fiscal/reopen/{year}")
def fiscal_reopen_year(
    year: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("settings", "update")),
):
    closed = reopen_fiscal_year(db, year)
    uid, email, ip = _user_ctx(request, user)
    log_audit(db, "update", "compta", "fiscal_year", year, f"Réouverture {year}", uid, email, ip)
    db.commit()
    return {"ok": True, "closed_years": closed}
