"""API plateforme enterprise — workflow, notifications, recherche, portail, tickets, sync."""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.auth import get_current_user
from app.database import get_db
from app.models import Client, Deal, Invoice, Project, Quote, StockItem, Transaction, User
from app.models_enterprise import ApprovalRequest, ApprovalStep
from app.models_erp import Employee, JournalEntry, Supplier
from app.models_platform import (
    ApprovalRule,
    ClientPortalAccess,
    NotificationRule,
    OfflineSyncBatch,
    SupportTicket,
)
from app.schemas_platform import (
    ApprovalDecideIn,
    ApprovalRuleIn,
    ApprovalRuleOut,
    ApprovalSubmitIn,
    NotificationRuleIn,
    NotificationRuleOut,
    OfflineSyncBatchIn,
    PortalTokenIn,
    PortalTokenOut,
    SearchResultOut,
    SupportTicketIn,
    SupportTicketOut,
)
from app.services.approval_engine import (
    decide_approval,
    needs_approval,
    pending_for_entity,
    seed_default_rules,
    submit_approval,
)
from app.services.notification_engine import emit_event, notify_payment_received, run_scheduled_checks, seed_notification_rules
from app.tenant_service import filter_by_company, get_company_id

router = APIRouter(prefix="/api/platform", tags=["platform"])
portal_router = APIRouter(prefix="/api/portal", tags=["portal-client"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ——— Initialisation ———
@router.post("/seed")
def platform_seed(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403)
    cid = get_company_id(db, user)
    seed_default_rules(db, cid)
    seed_notification_rules(db)
    return {"ok": True}


@router.post("/checks/run")
def run_checks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in ("admin", "manager"):
        raise HTTPException(403)
    return run_scheduled_checks(db)


# ——— Règles d'approbation ———
@router.get("/approval-rules", response_model=List[ApprovalRuleOut])
def list_approval_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cid = get_company_id(db, user)
    q = db.query(ApprovalRule).filter(
        or_(ApprovalRule.company_id == cid, ApprovalRule.company_id.is_(None))
    ).order_by(ApprovalRule.module)
    return q.all()


@router.post("/approval-rules", response_model=ApprovalRuleOut)
def create_approval_rule(
    data: ApprovalRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403)
    obj = ApprovalRule(**data.model_dump(), company_id=get_company_id(db, user), created_at=_now())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/approval-rules/{rid}", response_model=ApprovalRuleOut)
def update_approval_rule(
    rid: int,
    data: ApprovalRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403)
    obj = db.query(ApprovalRule).filter(ApprovalRule.id == rid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


# ——— File d'approbation ———
@router.get("/approvals")
def list_platform_approvals(
    status: Optional[str] = None,
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ApprovalRequest).order_by(ApprovalRequest.id.desc())
    if status:
        q = q.filter(ApprovalRequest.status == status)
    if mine:
        q = q.filter(ApprovalRequest.requested_by == user.id)
    reqs = q.limit(150).all()
    users = {u.id: u.full_name or u.email for u in db.query(User).all()}
    out = []
    for r in reqs:
        steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == r.id).order_by(ApprovalStep.level).all()
        out.append({
            "id": r.id,
            "module": r.module,
            "title": r.title,
            "amount": r.amount,
            "status": r.status,
            "current_level": r.current_level,
            "max_levels": r.max_levels,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "requested_by_name": users.get(r.requested_by, ""),
            "created_at": r.created_at,
            "notes": r.notes,
            "steps": [
                {
                    "level": s.level,
                    "role": s.approver_role,
                    "status": s.status,
                    "comment": s.comment,
                    "decided_at": s.decided_at,
                }
                for s in steps
            ],
            "can_decide": user.role in ("admin", "manager", "dg", "director") and r.status in ("pending", "revision"),
        })
    return out


@router.post("/approvals/submit")
def submit_platform_approval(
    data: ApprovalSubmitIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = get_company_id(db, user)
    try:
        req = submit_approval(
            db, user, data.module, data.title, data.amount,
            data.entity_type, data.entity_id, data.notes, cid,
        )
        return {"ok": True, "id": req.id, "status": req.status}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/approvals/{rid}/decide")
def decide_platform_approval(
    rid: int,
    body: ApprovalDecideIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        req = decide_approval(db, rid, user, body.action, body.comment)
        emit_event(db, "approval_done", {"title": req.title, "status": req.status})
        return {"ok": True, "status": req.status}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/approvals/check")
def check_needs_approval(
    module: str,
    amount: float = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = get_company_id(db, user)
    return {"needs_approval": needs_approval(db, module, amount, cid)}


# ——— Règles notifications ———
@router.get("/notification-rules", response_model=List[NotificationRuleOut])
def list_notification_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403)
    return db.query(NotificationRule).order_by(NotificationRule.event_type).all()


@router.put("/notification-rules/{rid}", response_model=NotificationRuleOut)
def update_notification_rule(
    rid: int,
    data: NotificationRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403)
    obj = db.query(NotificationRule).filter(NotificationRule.id == rid).first()
    if not obj:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


# ——— Recherche globale enrichie ———
@router.get("/search", response_model=List[SearchResultOut])
def platform_global_search(
    q: str = Query(min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    term = f"%{q}%"
    cid = get_company_id(db, user)
    results: List[SearchResultOut] = []
    cq = filter_by_company(db.query(Client), Client, cid)
    for c in cq.filter(Client.name.ilike(term)).limit(8):
        results.append(SearchResultOut(type="client", id=c.id, label=c.name, view="clients", meta=c.email or ""))
    iq = filter_by_company(db.query(Invoice), Invoice, cid)
    for i in iq.filter(Invoice.number.ilike(term)).limit(6):
        results.append(SearchResultOut(type="invoice", id=i.id, label=i.number or f"#{i.id}", view="invoices", meta=i.status or ""))
    for qo in db.query(Quote).filter(Quote.number.ilike(term)).limit(5):
        results.append(SearchResultOut(type="quote", id=qo.id, label=qo.number, view="quotes"))
    dq = filter_by_company(db.query(Deal), Deal, cid)
    for d in dq.filter(Deal.title.ilike(term)).limit(5):
        results.append(SearchResultOut(type="deal", id=d.id, label=d.title, view="deals", meta=d.stage or ""))
    for s in db.query(Supplier).filter(Supplier.name.ilike(term)).limit(5):
        results.append(SearchResultOut(type="supplier", id=s.id, label=s.name, view="suppliers"))
    for st in db.query(StockItem).filter(or_(StockItem.name.ilike(term), StockItem.sku.ilike(term))).limit(5):
        results.append(SearchResultOut(type="product", id=st.id, label=st.name, view="stock", meta=st.sku or ""))
    for e in db.query(Employee).filter(
        or_(Employee.firstname.ilike(term), Employee.lastname.ilike(term), Employee.matricule.ilike(term))
    ).limit(5):
        name = f"{e.firstname or ''} {e.lastname or ''}".strip() or e.matricule
        results.append(SearchResultOut(type="employee", id=e.id, label=name, view="hr", meta=e.position or ""))
    for je in db.query(JournalEntry).filter(
        or_(JournalEntry.reference.ilike(term), JournalEntry.label.ilike(term))
    ).limit(4):
        results.append(SearchResultOut(
            type="journal", id=je.id,
            label=je.reference or je.label or f"#{je.id}",
            view="journal",
        ))
    return results


# ——— Portail client (admin) ———
@router.post("/portal/tokens", response_model=PortalTokenOut)
def create_portal_token(
    data: PortalTokenIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "update")),
):
    client = db.query(Client).filter(Client.id == data.client_id).first()
    if not client:
        raise HTTPException(404, "Client introuvable")
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=max(1, data.days_valid))).strftime("%Y-%m-%dT%H:%M:%S")
    row = ClientPortalAccess(
        company_id=get_company_id(db, user),
        client_id=data.client_id,
        token=token,
        expires_at=expires,
        is_active=True,
        created_at=_now(),
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    return PortalTokenOut(token=token, url=f"/portal-client.html?token={token}", expires_at=expires)


# ——— Tickets support ———
@router.get("/tickets")
def list_tickets(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.ticket_service import sla_status
    q = db.query(SupportTicket).order_by(SupportTicket.id.desc())
    if status:
        q = q.filter(SupportTicket.status == status)
    out = []
    for t in q.limit(100).all():
        sla = sla_status(t)
        out.append({
            "id": t.id,
            "reference": t.reference,
            "subject": t.subject,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "client_id": t.client_id,
            "assigned_to": t.assigned_to,
            "opened_at": t.opened_at,
            "sla": sla,
        })
    return out


@router.post("/tickets", response_model=SupportTicketOut)
def create_ticket(
    data: SupportTicketIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ref = f"TK-{datetime.now().strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"
    obj = SupportTicket(
        company_id=get_company_id(db, user),
        client_id=data.client_id,
        reference=ref,
        subject=data.subject,
        description=data.description,
        priority=data.priority,
        status="ouvert",
        opened_at=_now(),
        created_by=user.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    emit_event(db, "ticket_opened", {"reference": ref, "subject": data.subject})
    return obj


@router.patch("/tickets/{tid}/status")
def update_ticket_status(
    tid: int,
    status: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = db.query(SupportTicket).filter(SupportTicket.id == tid).first()
    if not obj:
        raise HTTPException(404)
    obj.status = status
    if status == "resolu":
        obj.resolved_at = _now()
    db.commit()
    return {"ok": True}


# ——— Sync offline ———
@router.post("/sync/batch")
def sync_offline_batch(
    body: OfflineSyncBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    processed = []
    errors = []
    from app.models_business_ext import CollectionPayment, CollectionCase
    from app.models import Invoice
    from sqlalchemy import func
    from datetime import date as date_type

    def _sync_case(db, case):
        paid = db.query(func.coalesce(func.sum(CollectionPayment.amount), 0)).filter(
            CollectionPayment.case_id == case.id
        ).scalar() or 0
        case.amount_collected = float(paid)
        if case.amount_collected >= float(case.amount_due or 0) > 0:
            case.status = "clos"
        elif case.amount_collected > 0:
            case.status = "partiel"

    for item in body.items:
        try:
            if item.entity == "collection_payment" and item.op in ("create", "collection_note"):
                p = item.payload or {}
                amount = float(p.get("amount") or 0)
                if amount <= 0:
                    raise ValueError("Montant invalide")
                obj = CollectionPayment(
                    case_id=p.get("case_id"),
                    client_id=p.get("client_id"),
                    invoice_id=p.get("invoice_id"),
                    amount=amount,
                    payment_method=p.get("payment_method") or "mobile_money",
                    reference=p.get("reference") or "",
                    notes=p.get("notes") or "Sync terrain",
                    collection_date=p.get("collection_date") or date_type.today(),
                    collected_by=user.full_name or user.email,
                    created_at=_now(),
                )
                db.add(obj)
                db.flush()
                if obj.case_id:
                    case = db.query(CollectionCase).filter(CollectionCase.id == obj.case_id).first()
                    if case:
                        _sync_case(db, case)
                if obj.invoice_id:
                    inv = db.query(Invoice).filter(Invoice.id == obj.invoice_id).first()
                    if inv:
                        inv.paid = float(inv.paid or 0) + amount
                        if inv.paid >= float(inv.amount or 0):
                            inv.status = "payée"
                from app.services.treasury_advanced_service import create_treasury_from_payment
                create_treasury_from_payment(
                    db,
                    amount=amount,
                    label=f"Recouvrement terrain — client {p.get('client_id')}",
                    reference=p.get("reference") or f"OFF-{obj.id}",
                    payment_method=p.get("payment_method") or "mobile_money",
                )
                processed.append({"op": item.op, "id": obj.id, "ok": True})
            elif item.op == "client_visit" and item.entity == "crm_activity":
                processed.append({"op": item.op, "ok": True, "stub": True})
            else:
                processed.append({"op": item.op, "entity": item.entity, "ok": True, "stub": True})
        except Exception as ex:
            errors.append({"op": item.op, "error": str(ex)})
    batch = OfflineSyncBatch(
        user_id=user.id,
        device_id=body.device_id,
        items_count=len(body.items),
        status="processed" if not errors else "partial",
        created_at=_now(),
        detail_json=str({"processed": len(processed), "errors": len(errors)}),
    )
    db.add(batch)
    db.commit()
    return {"ok": True, "processed": processed, "errors": errors}


# ——— Portail client public ———
def _portal_client(db: Session, token: str) -> ClientPortalAccess:
    row = db.query(ClientPortalAccess).filter(
        ClientPortalAccess.token == token,
        ClientPortalAccess.is_active == True,
    ).first()
    if not row:
        raise HTTPException(401, "Accès invalide")
    if row.expires_at and row.expires_at < _now():
        raise HTTPException(401, "Lien expiré")
    return row


@portal_router.get("/dashboard")
def portal_dashboard(token: str = Query(...), db: Session = Depends(get_db)):
    access = _portal_client(db, token)
    client = db.query(Client).filter(Client.id == access.client_id).first()
    if not client:
        raise HTTPException(404)
    invoices = db.query(Invoice).filter(Invoice.client_id == client.id).order_by(Invoice.id.desc()).limit(50).all()
    total_due = sum(max(0, float(i.amount or 0) - float(i.paid or 0)) for i in invoices if i.status not in ("payée", "brouillon", "annulée"))
    return {
        "client": {"id": client.id, "name": client.name, "email": client.email},
        "balance_due": total_due,
        "invoices": [
            {
                "id": i.id,
                "number": i.number,
                "date": str(i.date) if i.date else "",
                "due_date": str(i.due_date) if i.due_date else "",
                "amount": i.amount,
                "paid": i.paid,
                "balance": max(0, float(i.amount or 0) - float(i.paid or 0)),
                "status": i.status,
                "doc_type": getattr(i, "doc_type", "invoice"),
            }
            for i in invoices
        ],
    }


@portal_router.get("/invoices/{iid}/pdf")
def portal_invoice_pdf(iid: int, token: str = Query(...), db: Session = Depends(get_db)):
    access = _portal_client(db, token)
    inv = db.query(Invoice).filter(Invoice.id == iid, Invoice.client_id == access.client_id).first()
    if not inv:
        raise HTTPException(404)
    client = db.query(Client).filter(Client.id == access.client_id).first()
    from app.models import DocumentLine
    lines = db.query(DocumentLine).filter(DocumentLine.invoice_id == inv.id).all()
    from app.pdf_docs import render_invoice_pdf
    from fastapi.responses import Response
    data = render_invoice_pdf(inv, client, lines)
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{inv.number or "facture"}.pdf"',
    })


@portal_router.post("/tickets")
def portal_create_ticket(
    token: str = Query(...),
    subject: str = Query(...),
    description: str = Query(""),
    db: Session = Depends(get_db),
):
    access = _portal_client(db, token)
    ref = f"TKP-{uuid.uuid4().hex[:6].upper()}"
    obj = SupportTicket(
        company_id=access.company_id,
        client_id=access.client_id,
        reference=ref,
        subject=subject,
        description=description,
        status="ouvert",
        opened_at=_now(),
    )
    db.add(obj)
    db.commit()
    return {"ok": True, "reference": ref}


@portal_router.get("/payment-providers")
def portal_payment_providers():
    return {"providers": [
        {"id": "fedapay", "label": "FedaPay"},
        {"id": "mixx", "label": "Mixx by Yas"},
        {"id": "flooz", "label": "Flooz T-Money"},
        {"id": "cinetpay", "label": "CinetPay"},
    ]}


@portal_router.post("/payments/initiate")
def portal_initiate_payment(
    token: str = Query(...),
    invoice_id: int = Query(...),
    provider: str = Query("fedapay"),
    db: Session = Depends(get_db),
):
    access = _portal_client(db, token)
    inv = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.client_id == access.client_id,
    ).first()
    if not inv:
        raise HTTPException(404, "Facture introuvable")
    balance = max(0, float(inv.amount or 0) - float(inv.paid or 0))
    if balance <= 0:
        raise HTTPException(400, "Facture déjà soldée")
    from app.services.payment_gateway_service import initiate_payment
    try:
        intent = initiate_payment(db, provider=provider, invoice_id=invoice_id, amount=balance)
        return {
            "ok": True,
            "checkout_url": intent.checkout_url,
            "external_id": intent.external_id,
            "amount": balance,
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
