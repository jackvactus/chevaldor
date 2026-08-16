"""Suite métier — types clients, recouvrement, contrats, commerciaux."""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form, Path
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.database import get_db
from app.models import Client, Invoice, User
from app.models_business_ext import (
    ClientType,
    CollectionCase,
    CollectionPayment,
    InvoiceRecurring,
    SalesContract,
    SalesContractAmendment,
    SalesRep,
)
from app.schemas_business import (
    ClientTypeIn,
    CollectionCaseIn,
    CollectionPaymentIn,
    InvoiceRecurringIn,
    InvoiceRecurringOut,
    SalesContractAmendmentIn,
    SalesContractIn,
    SalesRepIn,
)
from app.services.audit_log import log_audit
from app.tenant_service import filter_by_company, get_company_id, stamp_company

router = APIRouter(prefix="/api/erp/business", tags=["business-suite"])

DEFAULT_CLIENT_TYPES = [
    ("PART", "Particulier", 0, 18, 0, 0),
    ("ENT", "Entreprise", 0, 18, 2, 0),
    ("REV", "Revendeur", 0, 18, 5, 0),
    ("DIST", "Distributeur", 0, 18, 7, 0),
    ("GROSS", "Grossiste", 0, 18, 8, 0),
    ("ADM", "Administration", 0, 0, 0, 5),
    ("ONG", "ONG", 0, 0, 0, 0),
    ("ASSO", "Association", 0, 0, 0, 0),
    ("VIP", "VIP", 0, 18, 3, 0),
]


def ensure_client_types_seeded(db: Session) -> None:
    if db.query(ClientType).count() > 0:
        return
    for code, name, disc, vat, comm, ret in DEFAULT_CLIENT_TYPES:
        db.add(ClientType(
            code=code, name=name,
            default_discount_pct=disc,
            default_vat_pct=vat,
            default_commission_pct=comm,
            default_withholding_pct=ret,
        ))
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _ctx(request: Request, user: User):
    return user.id, user.email, request.client.host if request.client else ""


# ——— Types clients ———
@router.get("/client-types")
def list_client_types(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clients", "view")),
):
    ensure_client_types_seeded(db)
    q = db.query(ClientType)
    if not include_archived:
        q = q.filter(ClientType.is_archived == 0)
    return q.order_by(ClientType.name).all()


@router.post("/client-types")
def create_client_type(
    data: ClientTypeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "create")),
):
    if db.query(ClientType).filter(ClientType.code == data.code).first():
        raise HTTPException(400, "Code déjà utilisé")
    obj = ClientType(**data.model_dump())
    obj.is_archived = 1 if data.is_archived else 0
    db.add(obj)
    db.commit()
    db.refresh(obj)
    uid, email, ip = _ctx(request, user)
    log_audit(db, "create", "clients", "client_type", obj.id, obj.name, uid, email, ip)
    db.commit()
    return obj


@router.put("/client-types/{tid}")
def update_client_type(
    tid: int,
    data: ClientTypeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "update")),
):
    obj = db.query(ClientType).filter(ClientType.id == tid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        if k == "is_archived":
            setattr(obj, k, 1 if v else 0)
        else:
            setattr(obj, k, v)
    db.commit()
    uid, email, ip = _ctx(request, user)
    log_audit(db, "update", "clients", "client_type", tid, obj.name, uid, email, ip)
    db.commit()
    return obj


@router.delete("/client-types/{tid}")
def archive_client_type(
    tid: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "delete")),
):
    obj = db.query(ClientType).filter(ClientType.id == tid).first()
    if not obj:
        raise HTTPException(404)
    obj.is_archived = 1
    db.commit()
    uid, email, ip = _ctx(request, user)
    log_audit(db, "archive", "clients", "client_type", tid, obj.name, uid, email, ip)
    db.commit()
    return {"ok": True}


# ——— Recouvrement ———
def _sync_case_amounts(db: Session, case: CollectionCase) -> None:
    paid = (
        db.query(func.coalesce(func.sum(CollectionPayment.amount), 0))
        .filter(CollectionPayment.case_id == case.id)
        .scalar()
    ) or 0
    case.amount_collected = float(paid)
    if case.due_date:
        case.delay_days = max(0, (date.today() - case.due_date).days)
    if case.amount_collected >= case.amount_due > 0:
        case.status = "clos"
    elif case.amount_collected > 0:
        case.status = "partiel"


@router.get("/collections/cases")
def list_collection_cases(
    status: Optional[str] = None,
    client_id: Optional[int] = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "view")),
):
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(CollectionCase), CollectionCase, cid)
    if status:
        q = q.filter(CollectionCase.status == status)
    if client_id:
        q = q.filter(CollectionCase.client_id == client_id)
    total = q.count()
    rows = q.order_by(CollectionCase.id.desc()).offset(offset).limit(limit).all()
    return {"items": rows, "total": total}


@router.post("/collections/cases")
def create_collection_case(
    data: CollectionCaseIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    obj = CollectionCase(**data.model_dump())
    stamp_company(obj, get_company_id(db, user))
    obj.created_at = _now()
    obj.updated_at = obj.created_at
    if obj.invoice_id and not obj.amount_due:
        inv = db.query(Invoice).filter(Invoice.id == obj.invoice_id).first()
        if inv:
            obj.amount_due = float(inv.amount or 0) - float(inv.paid or 0)
            obj.due_date = obj.due_date or inv.due_date
    if obj.due_date:
        obj.delay_days = max(0, (date.today() - obj.due_date).days)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    uid, email, ip = _ctx(request, user)
    log_audit(db, "create", "recouvrement", "collection_case", obj.id, obj.reference, uid, email, ip)
    db.commit()
    return obj


@router.put("/collections/cases/{cid}")
def update_collection_case(
    cid: int,
    data: CollectionCaseIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "update")),
):
    obj = db.query(CollectionCase).filter(CollectionCase.id == cid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    _sync_case_amounts(db, obj)
    db.commit()
    return obj


@router.delete("/collections/cases/{cid}")
def delete_collection_case(
    cid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "delete")),
):
    db.query(CollectionPayment).filter(CollectionPayment.case_id == cid).delete()
    obj = db.query(CollectionCase).filter(CollectionCase.id == cid).first()
    if obj:
        db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/collections/payments")
def list_collection_payments(
    day: Optional[str] = None,
    month: Optional[str] = None,
    sales_rep_id: Optional[int] = None,
    client_id: Optional[int] = None,
    offset: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "view")),
):
    """Liste unifiée des encaissements réels (date de paiement, sans échéance)."""
    if day:
        start = end = date.fromisoformat(day[:10])
    elif month:
        parts = month.split("-")
        y, m = int(parts[0]), int(parts[1])
        start = date(y, m, 1)
        end = _month_end(y, m)
    else:
        end = date.today()
        start = end - timedelta(days=90)
    rows = _unified_collection_rows(db, start, end, client_id)
    if sales_rep_id:
        rows = [r for r in rows if r.get("sales_rep_id") == sales_rep_id]
    total = len(rows)
    page = rows[offset: offset + limit]
    return {"items": page, "total": total}


@router.post("/collections/payments")
def create_collection_payment(
    data: CollectionPaymentIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    obj = CollectionPayment(**data.model_dump())
    if not obj.collection_date:
        obj.collection_date = date.today()
    obj.created_at = _now()
    if not obj.collected_by:
        obj.collected_by = user.full_name or user.email
    db.add(obj)
    db.flush()
    if obj.case_id:
        case = db.query(CollectionCase).filter(CollectionCase.id == obj.case_id).first()
        if case:
            _sync_case_amounts(db, case)
    if obj.invoice_id:
        inv = db.query(Invoice).filter(Invoice.id == obj.invoice_id).first()
        if inv:
            inv.paid = float(inv.paid or 0) + float(obj.amount or 0)
            if inv.paid >= float(inv.amount or 0):
                inv.status = "payée"
    db.commit()
    db.refresh(obj)
    uid, email, ip = _ctx(request, user)
    log_audit(db, "create", "recouvrement", "collection_payment", obj.id, str(obj.amount), uid, email, ip)
    db.commit()
    return obj


@router.post("/collections/sync-overdue")
def sync_overdue_invoices(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    """Crée des dossiers recouvrement pour factures en retard sans dossier ouvert."""
    cid = get_company_id(db, user)
    today = date.today()
    q = filter_by_company(db.query(Invoice), Invoice, cid)
    overdue = q.filter(
        Invoice.status.in_(["envoyée", "en retard"]),
        Invoice.due_date < today,
    ).all()
    created = 0
    for inv in overdue:
        balance = float(inv.amount or 0) - float(inv.paid or 0)
        if balance <= 0:
            continue
        exists = (
            db.query(CollectionCase)
            .filter(
                CollectionCase.invoice_id == inv.id,
                CollectionCase.status.in_(["ouvert", "partiel"]),
            )
            .first()
        )
        if exists:
            continue
        delay = max(0, (today - inv.due_date).days) if inv.due_date else 0
        obj = CollectionCase(
            company_id=cid,
            client_id=inv.client_id,
            invoice_id=inv.id,
            reference=inv.number or f"INV-{inv.id}",
            amount_due=balance,
            due_date=inv.due_date,
            delay_days=delay,
            status="ouvert",
            priority="haute" if delay > 30 else "normale",
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(obj)
        created += 1
    db.commit()
    return {"ok": True, "created": created, "scanned": len(overdue)}


@router.get("/collections/analytics")
def collections_analytics(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "view")),
):
    today = date.today()
    month_start = today.replace(day=1)
    cid = get_company_id(db, user)
    cases = filter_by_company(db.query(CollectionCase), CollectionCase, cid).all()
    payments = db.query(CollectionPayment).filter(CollectionPayment.collection_date >= month_start).all()
    today_payments = [p for p in payments if p.collection_date == today]
    total_due = sum(float(c.amount_due or 0) - float(c.amount_collected or 0) for c in cases if c.status != "clos")
    collected_month = sum(float(p.amount or 0) for p in payments)
    collected_today = sum(float(p.amount or 0) for p in today_payments)
    open_cases = len([c for c in cases if c.status in ("ouvert", "partiel")])
    overdue = len([c for c in cases if (c.delay_days or 0) > 0 and c.status != "clos"])
    rate = 0.0
    total_cases_due = sum(float(c.amount_due or 0) for c in cases)
    total_collected = sum(float(c.amount_collected or 0) for c in cases)
    if total_cases_due > 0:
        rate = round(100 * total_collected / total_cases_due, 1)
    by_rep: dict[str, float] = {}
    by_client: dict[int, float] = {}
    for p in payments:
        key = str(p.sales_rep_id or p.collected_by or "—")
        by_rep[key] = by_rep.get(key, 0) + float(p.amount or 0)
        if p.client_id:
            by_client[p.client_id] = by_client.get(p.client_id, 0) + float(p.amount or 0)
    return {
        "impayes": total_due,
        "collecte_mois": collected_month,
        "collecte_jour": collected_today,
        "dossiers_ouverts": open_cases,
        "retards": overdue,
        "taux_recouvrement": rate,
        "par_commercial": [{"key": k, "amount": v} for k, v in sorted(by_rep.items(), key=lambda x: -x[1])],
        "par_client": [{"client_id": k, "amount": v} for k, v in sorted(by_client.items(), key=lambda x: -x[1])],
    }


# ——— Commerciaux ———
@router.get("/sales-reps")
def list_sales_reps(db: Session = Depends(get_db), _: User = Depends(require_action("deals", "view"))):
    return db.query(SalesRep).order_by(SalesRep.name).all()


@router.post("/sales-reps")
def create_sales_rep(data: SalesRepIn, db: Session = Depends(get_db), _: User = Depends(require_action("deals", "create"))):
    obj = SalesRep(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/sales-reps/{rid}")
def update_sales_rep(rid: int, data: SalesRepIn, db: Session = Depends(get_db), _: User = Depends(require_action("deals", "update"))):
    obj = db.query(SalesRep).filter(SalesRep.id == rid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    return obj


@router.delete("/sales-reps/{rid}")
def delete_sales_rep(rid: int, db: Session = Depends(get_db), _: User = Depends(require_action("deals", "delete"))):
    obj = db.query(SalesRep).filter(SalesRep.id == rid).first()
    if obj:
        db.delete(obj)
    db.commit()
    return {"ok": True}


# ——— Contrats commerciaux ———
@router.get("/contracts")
def list_contracts(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("deals", "view")),
):
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(SalesContract), SalesContract, cid)
    if client_id:
        q = q.filter(SalesContract.client_id == client_id)
    if status:
        q = q.filter(SalesContract.status == status)
    return q.order_by(SalesContract.id.desc()).all()


@router.post("/contracts")
def create_contract(data: SalesContractIn, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "create"))):
    if db.query(SalesContract).filter(SalesContract.reference == data.reference).first():
        raise HTTPException(400, "Référence contrat déjà utilisée")
    obj = SalesContract(**data.model_dump())
    stamp_company(obj, get_company_id(db, user))
    obj.created_at = _now()
    obj.updated_at = obj.created_at
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/contracts/{cid}")
def update_contract(cid: int, data: SalesContractIn, db: Session = Depends(get_db), _: User = Depends(require_action("deals", "update"))):
    obj = db.query(SalesContract).filter(SalesContract.id == cid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    db.commit()
    return obj


@router.post("/contracts/{cid}/renew")
def renew_contract(cid: int, db: Session = Depends(get_db), _: User = Depends(require_action("deals", "create"))):
    src = db.query(SalesContract).filter(SalesContract.id == cid).first()
    if not src:
        raise HTTPException(404)
    ref = f"{src.reference}-R{date.today().strftime('%Y%m')}"
    obj = SalesContract(
        client_id=src.client_id,
        reference=ref,
        title=f"Renouvellement — {src.title}",
        start_date=date.today(),
        end_date=src.end_date,
        amount=src.amount,
        discount_pct=src.discount_pct,
        vat_pct=src.vat_pct,
        commission_pct=src.commission_pct,
        status="brouillon",
        sales_rep_id=src.sales_rep_id,
        renewal_of_id=src.id,
        company_id=src.company_id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/contracts/{cid}/amendments")
def list_amendments(cid: int, db: Session = Depends(get_db), _: User = Depends(require_action("deals", "view"))):
    return db.query(SalesContractAmendment).filter(SalesContractAmendment.contract_id == cid).order_by(SalesContractAmendment.id.desc()).all()


@router.post("/contracts/{cid}/amendments")
def add_amendment(cid: int, data: SalesContractAmendmentIn, db: Session = Depends(get_db), _: User = Depends(require_action("deals", "create"))):
    obj = SalesContractAmendment(contract_id=cid, **data.model_dump())
    db.add(obj)
    contract = db.query(SalesContract).filter(SalesContract.id == cid).first()
    if contract and data.amount_delta:
        contract.amount = float(contract.amount or 0) + float(data.amount_delta)
        contract.updated_at = _now()
    db.commit()
    db.refresh(obj)
    return obj


# ——— Factures récurrentes ———
def _recurring_out(obj: InvoiceRecurring) -> InvoiceRecurringOut:
    return InvoiceRecurringOut(
        id=obj.id,
        client_id=obj.client_id,
        template_invoice_id=obj.template_invoice_id,
        label=obj.label or "",
        frequency=obj.frequency or "monthly",
        next_date=obj.next_date,
        end_date=obj.end_date,
        amount=float(obj.amount or 0),
        active=bool(obj.active),
        notes=obj.notes or "",
        last_generated_at=obj.last_generated_at or "",
    )


@router.get("/recurring-invoices", response_model=List[InvoiceRecurringOut])
def list_recurring(db: Session = Depends(get_db), _: User = Depends(require_action("invoices", "view"))):
    rows = db.query(InvoiceRecurring).order_by(InvoiceRecurring.id.desc()).all()
    return [_recurring_out(r) for r in rows]


@router.post("/recurring-invoices", response_model=InvoiceRecurringOut)
def create_recurring(
    data: InvoiceRecurringIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    payload = data.model_dump()
    payload["active"] = 1 if data.active else 0
    obj = InvoiceRecurring(**payload)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    ip = request.client.host if request.client else ""
    log_audit(db, "create", "invoices", "invoice_recurring", obj.id, obj.label or "", user.id, user.email, ip)
    db.commit()
    return _recurring_out(obj)


@router.put("/recurring-invoices/{rid}", response_model=InvoiceRecurringOut)
def update_recurring(
    rid: int,
    data: InvoiceRecurringIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "update")),
):
    obj = db.query(InvoiceRecurring).filter(InvoiceRecurring.id == rid).first()
    if not obj:
        raise HTTPException(404, "Plan récurrent introuvable")
    for k, v in data.model_dump().items():
        if k == "active":
            setattr(obj, k, 1 if v else 0)
        else:
            setattr(obj, k, v)
    ip = request.client.host if request.client else ""
    log_audit(db, "update", "invoices", "invoice_recurring", obj.id, obj.label or "", user.id, user.email, ip)
    db.commit()
    db.refresh(obj)
    return _recurring_out(obj)


@router.delete("/recurring-invoices/{rid}")
def delete_recurring(
    rid: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "delete")),
):
    obj = db.query(InvoiceRecurring).filter(InvoiceRecurring.id == rid).first()
    if obj:
        ip = request.client.host if request.client else ""
        log_audit(db, "delete", "invoices", "invoice_recurring", obj.id, obj.label or "", user.id, user.email, ip)
        db.delete(obj)
    db.commit()
    return {"ok": True}


@router.post("/recurring-invoices/{rid}/generate")
def generate_recurring_invoice(rid: int, db: Session = Depends(get_db), user: User = Depends(require_action("invoices", "create"))):
    plan = db.query(InvoiceRecurring).filter(InvoiceRecurring.id == rid).first()
    if not plan or not plan.active:
        raise HTTPException(400, "Plan récurrent inactif")
    from app.commercial_service import _next_invoice_number
    prefix = "F"
    num = _next_invoice_number(db, prefix)
    inv = Invoice(
        number=num,
        client_id=plan.client_id,
        date=plan.next_date or date.today(),
        due_date=plan.next_date or date.today(),
        amount=plan.amount,
        status="brouillon",
        doc_type="invoice",
        notes=f"Récurrent — {plan.label}",
        created_by=user.id,
    )
    db.add(inv)
    freq = plan.frequency or "monthly"
    nd = plan.next_date or date.today()
    if freq == "daily":
        plan.next_date = nd + timedelta(days=1)
    elif freq == "weekly":
        plan.next_date = nd + timedelta(days=7)
    elif freq == "quarterly":
        plan.next_date = nd + timedelta(days=92)
    elif freq == "yearly":
        plan.next_date = nd.replace(year=nd.year + 1)
    else:
        m = nd.month + 1
        y = nd.year
        if m > 12:
            m, y = 1, y + 1
        plan.next_date = nd.replace(year=y, month=m)
    plan.last_generated_at = _now()
    db.commit()
    db.refresh(inv)
    return {"ok": True, "invoice_id": inv.id, "number": inv.number}


def _month_end(year: int, month: int) -> date:
    import calendar as cal_mod
    return date(year, month, cal_mod.monthrange(year, month)[1])


def _advance_plan_date(d: date, frequency: str) -> date:
    freq = (frequency or "monthly").lower()
    if freq == "daily":
        return d + timedelta(days=1)
    if freq == "weekly":
        return d + timedelta(days=7)
    if freq == "quarterly":
        return d + timedelta(days=92)
    if freq == "yearly":
        try:
            return d.replace(year=d.year + 1)
        except ValueError:
            return d.replace(year=d.year + 1, day=28)
    m = d.month + 1
    y = d.year
    if m > 12:
        m, y = 1, y + 1
    import calendar as cal_mod
    last = cal_mod.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def _make_client_resolver(db: Session):
    cache: dict[int, str] = {}

    def resolve(cid: Optional[int]) -> str:
        if not cid:
            return "—"
        if cid not in cache:
            row = db.query(Client).filter(Client.id == cid).first()
            cache[cid] = row.name if row else f"Client #{cid}"
        return cache[cid]

    return resolve


def _unified_collection_rows(
    db: Session,
    start: date,
    end: date,
    client_id: Optional[int] = None,
) -> list[dict]:
    """
    Encaissements réels unifiés — date de paiement / collecte uniquement (jamais échéance facture).
    Sources : collection_payments (recouvrement) + collection_payment_details (fiches collecte validées).

    Garde-fou : une collecte « réelle » ne peut jamais être datée dans le futur — si une donnée
    malformée (saisie anticipée, import, fiche pré-remplie) porte une date future, elle est exclue
    ici plutôt que de fuiter des montants « prévus » dans un calendrier censé n'afficher que du réel.
    """
    end = min(end, date.today())
    if end < start:
        return []
    resolve = _make_client_resolver(db)
    rows: list[dict] = []

    q = db.query(CollectionPayment).filter(
        CollectionPayment.collection_date.isnot(None),
        CollectionPayment.collection_date >= start,
        CollectionPayment.collection_date <= end,
    )
    if client_id:
        q = q.filter(CollectionPayment.client_id == client_id)
    for p in q.order_by(CollectionPayment.collection_date.desc(), CollectionPayment.id.desc()).all():
        d_str = str(p.collection_date)
        rows.append({
            "id": p.id,
            "source": "recouvrement",
            "payment_date": d_str,
            "collection_date": d_str,
            "client_id": p.client_id,
            "client_name": resolve(p.client_id),
            "amount": float(p.amount or 0),
            "status": "completed",
            "payment_method": p.payment_method or "—",
            "method": p.payment_method or "—",
            "reference": p.reference or "",
            "collected_by": p.collected_by or "",
            "sales_rep_id": p.sales_rep_id,
            "case_id": p.case_id,
            "invoice_id": p.invoice_id,
            "label": "Collecte recouvrement",
        })

    try:
        from app.models_recurring_advanced import CollectionPaymentDetail

        dq = db.query(CollectionPaymentDetail).filter(
            CollectionPaymentDetail.status == "completed",
            CollectionPaymentDetail.payment_date.isnot(None),
            CollectionPaymentDetail.payment_date >= start,
            CollectionPaymentDetail.payment_date <= end,
        )
        if client_id:
            dq = dq.filter(CollectionPaymentDetail.client_id == client_id)
        for p in dq.order_by(CollectionPaymentDetail.payment_date.desc(), CollectionPaymentDetail.id.desc()).all():
            d_str = str(p.payment_date)
            rows.append({
                "id": p.id,
                "source": "fiche_collecte",
                "payment_date": d_str,
                "collection_date": d_str,
                "client_id": p.client_id,
                "client_name": resolve(p.client_id),
                "amount": float(p.payment_amount or 0),
                "status": "completed",
                "payment_method": p.payment_method or "cash",
                "method": p.payment_method or "cash",
                "reference": p.payment_reference or "",
                "collected_by": "",
                "collection_id": p.collection_id,
                "label": "Fiche collecte",
            })
    except Exception:
        pass

    try:
        from app.models_accounting import PaymentRecord

        rq = (
            db.query(PaymentRecord, Invoice)
            .join(Invoice, Invoice.id == PaymentRecord.invoice_id)
            .filter(
                PaymentRecord.direction == "in",
                Invoice.recurring_plan_id.isnot(None),
                PaymentRecord.date.isnot(None),
                PaymentRecord.date >= start,
                PaymentRecord.date <= end,
            )
        )
        if client_id:
            rq = rq.filter(Invoice.client_id == client_id)
        for pr, inv in rq.order_by(PaymentRecord.date.desc(), PaymentRecord.id.desc()).all():
            d_str = str(pr.date)
            rows.append({
                "id": pr.id,
                "source": "facture_recurrente",
                "payment_date": d_str,
                "collection_date": d_str,
                "client_id": inv.client_id,
                "client_name": resolve(inv.client_id),
                "amount": float(pr.amount or 0),
                "status": "completed",
                "payment_method": pr.method or "banque",
                "method": pr.method or "banque",
                "reference": pr.reference or inv.number or "",
                "collected_by": "",
                "invoice_id": inv.id,
                "recurring_plan_id": inv.recurring_plan_id,
                "label": f"Facture récurrente {inv.number}",
            })
    except Exception:
        pass

    rows.sort(key=lambda r: (r.get("payment_date") or "", r.get("source") or ""), reverse=True)
    return rows


def _build_collected_calendar(db: Session, year: int, month: int, client_id: Optional[int] = None) -> dict:
    """Calendrier des encaissements réels (date de paiement), sans échéances prévues."""
    start = date(year, month, 1)
    end = _month_end(year, month)
    calendar_data: dict = {}

    def _ensure_day(d_str: str) -> dict:
        if d_str not in calendar_data:
            calendar_data[d_str] = {
                "date": d_str,
                "payments": [],
                "summary": {"collected": 0, "count": 0, "clients": 0},
            }
        return calendar_data[d_str]

    def _append_payment(d_str: str, payload: dict) -> None:
        bucket = _ensure_day(d_str)
        bucket["payments"].append(payload)
        amt = float(payload.get("amount") or 0)
        bucket["summary"]["collected"] = round(bucket["summary"]["collected"] + amt, 2)
        bucket["summary"]["count"] += 1

    for row in _unified_collection_rows(db, start, end, client_id):
        d_str = row.get("payment_date") or row.get("collection_date")
        if not d_str:
            continue
        _append_payment(d_str, row)

    for bucket in calendar_data.values():
        cids = {p.get("client_id") for p in bucket["payments"] if p.get("client_id")}
        bucket["summary"]["clients"] = len(cids)

    all_client_ids = {
        p.get("client_id")
        for bucket in calendar_data.values()
        for p in bucket["payments"]
        if p.get("client_id")
    }
    month_summary = {
        "collected": round(sum(d["summary"]["collected"] for d in calendar_data.values()), 2),
        "count": sum(d["summary"]["count"] for d in calendar_data.values()),
        "clients": len(all_client_ids),
        "days_with_events": len(calendar_data),
    }

    flat_items = _unified_collection_rows(db, start, end, client_id)

    return {
        "year": year,
        "month": month,
        "start_date": str(start),
        "end_date": str(end),
        "data": calendar_data,
        "summary": month_summary,
        "items": flat_items,
    }


def _plan_occurrences_in_month(plan: InvoiceRecurring, year: int, month: int) -> list[date]:
    if not plan.active or not plan.next_date:
        return []
    start = date(year, month, 1)
    end = _month_end(year, month)
    cur = plan.next_date
    out: list[date] = []
    for _ in range(400):
        if cur > end:
            break
        if plan.end_date and cur > plan.end_date:
            break
        if cur >= start:
            out.append(cur)
        cur = _advance_plan_date(cur, plan.frequency or "monthly")
    return out


def _build_recurring_calendar(db: Session, year: int, month: int, client_id: Optional[int] = None) -> dict:
    """Ne renvoie que les montants réels déjà insérés dans l'application — jamais d'échéances
    prévisionnelles ni de paiements projetés (demande explicite de l'utilisateur, 2026-07-28 :
    un aller-retour a été fait sur ce point le même jour — voir CLAUDE.md — la version « combinée »
    avec projections de plans reste disponible dans l'historique git si jamais redemandée)."""
    return _build_collected_calendar(db, year, month, client_id)


@router.get("/recurring-invoices/calendar/{year}/{month}")
def recurring_invoices_calendar(
    year: int,
    month: int = Path(..., ge=1, le=12),
    client_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "view")),
):
    """Calendrier réel uniquement (alias collectes) — aucune projection de plan."""
    return _build_collected_calendar(db, year, month, client_id)


@router.get("/recurring-invoices/calendar/day/{payment_date}")
def recurring_invoices_calendar_day(
    payment_date: date,
    client_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "view")),
):
    cal = _build_recurring_calendar(db, payment_date.year, payment_date.month, client_id)
    bucket = cal["data"].get(payment_date.isoformat(), {"payments": [], "summary": {"expected": 0, "collected": 0}})
    payments = bucket.get("payments") or []
    return {
        "date": payment_date.isoformat(),
        "payments": payments,
        "summary": {
            "count": len(payments),
            "expected": bucket.get("summary", {}).get("expected", 0),
            "collected": bucket.get("summary", {}).get("collected", 0),
        },
    }


@router.get("/collections/calendar/{year}/{month}")
def collections_calendar(
    year: int,
    month: int = Path(..., ge=1, le=12),
    client_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "view")),
):
    """Calendrier des collectes réellement enregistrées (sans plans / échéances prévues)."""
    return _build_collected_calendar(db, year, month, client_id)


@router.get("/collections/calendar/day/{payment_date}")
def collections_calendar_day(
    payment_date: date,
    client_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "view")),
):
    cal = _build_collected_calendar(db, payment_date.year, payment_date.month, client_id)
    bucket = cal["data"].get(payment_date.isoformat(), {
        "payments": [],
        "summary": {"collected": 0, "count": 0, "clients": 0},
    })
    return {
        "date": payment_date.isoformat(),
        "payments": bucket.get("payments") or [],
        "summary": bucket.get("summary") or {"collected": 0, "count": 0, "clients": 0},
    }


@router.post("/recurring-invoices/import-collecte/preview")
async def preview_collecte_import(
    file: UploadFile = File(...),
    _: User = Depends(require_action("invoices", "view")),
):
    """Aperçu import FICHE DE COLLECTE.xlsx avant insertion."""
    from app.services.collecte_import_service import parse_collecte_workbook
    from app.upload_limits import read_bounded, assert_extension, SPREADSHEET_EXT

    assert_extension(file.filename, SPREADSHEET_EXT)
    content = await read_bounded(file)
    try:
        return parse_collecte_workbook(content, file.filename or "upload.xlsx")
    except Exception as e:
        raise HTTPException(400, f"Lecture impossible : {e}") from e


@router.post("/recurring-invoices/import-collecte")
async def import_collecte_recurring(
    file: UploadFile = File(...),
    create_clients: bool = Form(True),
    mode: str = Form("merge"),
    frequency: str = Form("daily"),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    """Importe FICHE DE COLLECTE.xlsx en plans factures récurrentes."""
    from app.services.collecte_import_service import import_collecte_to_recurring
    from app.upload_limits import read_bounded, assert_extension, SPREADSHEET_EXT

    assert_extension(file.filename, SPREADSHEET_EXT)
    content = await read_bounded(file)
    mode = (mode or "merge").strip().lower()
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "Mode invalide (merge ou replace)")
    freq = (frequency or "daily").strip().lower()
    if freq not in ("daily", "weekly", "monthly"):
        freq = "daily"
    try:
        cid = get_company_id(db, user)
        result = import_collecte_to_recurring(
            db,
            content,
            filename=file.filename or "upload.xlsx",
            create_clients=bool(create_clients),
            frequency=freq,
            mode=mode,
            company_id=cid,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(400, f"Import impossible : {e}") from e
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "Import impossible"))
    ip = ""
    log_audit(
        db, "import", "ventes", "recurring_collecte", None,
        file.filename or "collecte.xlsx", user.id, user.email or "", ip,
        new_value=result.get("message", "")[:500],
    )
    db.commit()
    return result


@router.get("/commercial/pipeline-analytics")
def pipeline_analytics(db: Session = Depends(get_db), user: User = Depends(require_action("deals", "view"))):
    from app.models import Deal
    from app.models_enterprise_ops import CrmLead
    cid = get_company_id(db, user)
    stage_map = {
        "lead": "nouveau",
        "qualified": "qualification",
        "proposal": "proposition",
        "negotiation": "négociation",
        "won": "gagné",
        "lost": "perdu",
        "nouveau": "nouveau",
        "qualification": "qualification",
        "proposition": "proposition",
        "négociation": "négociation",
        "gagné": "gagné",
        "perdu": "perdu",
    }
    deals = filter_by_company(db.query(Deal), Deal, cid).all()
    leads = db.query(CrmLead).all()
    stages = ["nouveau", "qualification", "proposition", "négociation", "gagné", "perdu"]
    counts = {s: 0 for s in stages}
    amounts = {s: 0.0 for s in stages}
    for d in deals:
        s = stage_map.get(d.stage, d.stage)
        if s not in counts:
            s = "nouveau"
        counts[s] += 1
        amounts[s] += float(d.amount or 0)
    for l in leads:
        s = stage_map.get(l.stage, l.stage)
        if s not in counts:
            s = "nouveau"
        counts[s] += 1
        amounts[s] += float(l.amount or 0)
    won = counts.get("gagné", 0)
    total = sum(counts.values()) or 1
    reps = db.query(SalesRep).filter(SalesRep.status == "actif").all()
    return {
        "stages": [{"stage": s, "count": counts[s], "amount": amounts[s]} for s in stages],
        "conversion_rate": round(100 * won / total, 1),
        "forecast": sum(amounts[s] for s in stages if s not in ("perdu", "gagné")),
        "sales_reps": [{"id": r.id, "name": r.name, "target": r.target_amount, "zone": r.zone} for r in reps],
    }
