"""CRM 360° — fiche client unifiée avec timeline."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Activity, Client, Deal, Invoice, Project, Quote
from app.models_business_ext import CollectionPayment
from app.models_enterprise_ops import CrmActivity
from app.models_platform import SupportTicket


def _parse_ts(val: Any) -> str:
    if not val:
        return ""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()
    return str(val)[:19]


def _timeline_item(
    *,
    kind: str,
    date_val: Any,
    title: str,
    detail: str = "",
    amount: float = 0,
    status: str = "",
    entity_id: int | None = None,
    icon: str = "info",
) -> dict:
    return {
        "kind": kind,
        "date": _parse_ts(date_val),
        "title": title,
        "detail": detail,
        "amount": amount,
        "status": status,
        "entity_id": entity_id,
        "icon": icon,
    }


def build_client_360(db: Session, client_id: int) -> dict:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client introuvable")

    deals = db.query(Deal).filter(Deal.client_id == client_id).order_by(Deal.close_date.desc()).limit(30).all()
    quotes = db.query(Quote).filter(Quote.client_id == client_id).order_by(Quote.date.desc()).limit(30).all()
    invoices = db.query(Invoice).filter(Invoice.client_id == client_id).order_by(Invoice.date.desc()).limit(40).all()
    projects = db.query(Project).filter(Project.client_id == client_id).order_by(Project.start_date.desc()).limit(20).all()
    activities = db.query(Activity).filter(Activity.client_id == client_id).order_by(Activity.date.desc()).limit(50).all()
    crm_acts = db.query(CrmActivity).filter(CrmActivity.client_id == client_id).order_by(CrmActivity.id.desc()).limit(30).all()
    collections = db.query(CollectionPayment).filter(CollectionPayment.client_id == client_id).order_by(
        CollectionPayment.collection_date.desc()
    ).limit(30).all()
    tickets = db.query(SupportTicket).filter(SupportTicket.client_id == client_id).order_by(
        SupportTicket.id.desc()
    ).limit(20).all()

    timeline: List[dict] = []

    for d in deals:
        timeline.append(_timeline_item(
            kind="deal", date_val=d.close_date or d.id, title=d.title or "Opportunité",
            detail=f"Stage {d.stage} · {d.probability or 0}%", amount=float(d.amount or 0),
            status=d.stage, entity_id=d.id, icon="deal",
        ))
    for q in quotes:
        timeline.append(_timeline_item(
            kind="quote", date_val=q.date, title=f"Devis {q.number}",
            amount=float(q.amount or 0), status=q.status, entity_id=q.id, icon="quote",
        ))
    for inv in invoices:
        balance = max(0, float(inv.amount or 0) - float(inv.paid or 0))
        timeline.append(_timeline_item(
            kind="invoice", date_val=inv.date, title=f"Facture {inv.number}",
            detail=f"Payé {inv.paid or 0:,.0f} / {inv.amount or 0:,.0f}",
            amount=float(inv.amount or 0), status=inv.status, entity_id=inv.id, icon="invoice",
        ))
        if float(inv.paid or 0) > 0:
            timeline.append(_timeline_item(
                kind="payment", date_val=inv.date, title=f"Encaissement {inv.number}",
                amount=float(inv.paid or 0), status="payé", entity_id=inv.id, icon="payment",
            ))
    for cp in collections:
        timeline.append(_timeline_item(
            kind="collection", date_val=cp.collection_date, title="Collecte recouvrement",
            detail=cp.payment_method or "", amount=float(cp.amount or 0),
            status="collecté", entity_id=cp.id, icon="payment",
        ))
    for a in activities:
        timeline.append(_timeline_item(
            kind="activity", date_val=a.date, title=a.subject or a.type,
            detail=(a.body or "")[:200], status=a.type, entity_id=a.id, icon="activity",
        ))
    for ca in crm_acts:
        timeline.append(_timeline_item(
            kind="crm_activity", date_val=ca.due_date or ca.id, title=ca.subject or ca.activity_type,
            detail=ca.activity_type or "", status=ca.status, entity_id=ca.id, icon="call",
        ))
    for t in tickets:
        timeline.append(_timeline_item(
            kind="ticket", date_val=t.opened_at, title=t.subject or t.reference,
            detail=t.description[:120] if t.description else "", status=t.status,
            entity_id=t.id, icon="ticket",
        ))

    timeline.sort(key=lambda x: x.get("date") or "", reverse=True)

    pipeline = sum(d.amount or 0 for d in deals if d.stage not in ("won", "lost"))
    invoiced = sum(i.amount or 0 for i in invoices)
    paid = sum(i.paid or 0 for i in invoices)
    balance_due = sum(max(0, float(i.amount or 0) - float(i.paid or 0)) for i in invoices if i.status not in ("brouillon", "annulée"))

    return {
        "client": {
            "id": client.id,
            "name": client.name,
            "email": client.email,
            "phone": client.phone,
            "client_type_id": getattr(client, "client_type_id", None),
            "notes": client.notes or "",
        },
        "deals": [{"id": d.id, "title": d.title, "stage": d.stage, "amount": d.amount} for d in deals],
        "quotes": [{"id": q.id, "number": q.number, "amount": q.amount, "status": q.status, "date": _parse_ts(q.date)} for q in quotes],
        "invoices": [
            {
                "id": i.id, "number": i.number, "amount": i.amount, "paid": i.paid,
                "balance": max(0, float(i.amount or 0) - float(i.paid or 0)),
                "status": i.status, "date": _parse_ts(i.date), "due_date": _parse_ts(i.due_date),
                "doc_type": getattr(i, "doc_type", "invoice"),
            }
            for i in invoices
        ],
        "projects": [{"id": p.id, "name": p.name, "status": p.status} for p in projects],
        "activities": [
            {"id": a.id, "type": a.type, "subject": a.subject, "body": a.body, "date": _parse_ts(a.date), "user_name": a.user_name}
            for a in activities
        ],
        "tickets": [
            {"id": t.id, "reference": t.reference, "subject": t.subject, "status": t.status, "priority": t.priority}
            for t in tickets
        ],
        "timeline": timeline[:80],
        "totals": {
            "pipeline": pipeline,
            "invoiced": invoiced,
            "paid": paid,
            "balance_due": balance_due,
        },
    }
