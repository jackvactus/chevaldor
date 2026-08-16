"""Tickets support — SLA, messages, assignation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import User
from app.models_platform import SupportTicket, SupportTicketMessage
from app.services.notify import create_app_notification


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _hours_since(ts: str) -> float:
    if not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", ""))
        return (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).total_seconds() / 3600
    except ValueError:
        return 0


def sla_status(ticket: SupportTicket) -> dict:
    opened_h = _hours_since(ticket.opened_at)
    resp_limit = ticket.sla_response_hours or 24
    resolve_limit = ticket.sla_resolve_hours or 72
    response_ok = bool(ticket.first_response_at) or opened_h <= resp_limit
    resolve_ok = ticket.status in ("resolu", "ferme") or opened_h <= resolve_limit
    breach_response = not ticket.first_response_at and opened_h > resp_limit
    breach_resolve = ticket.status not in ("resolu", "ferme") and opened_h > resolve_limit
    return {
        "hours_open": round(opened_h, 1),
        "response_ok": response_ok,
        "resolve_ok": resolve_ok,
        "breach_response": breach_response,
        "breach_resolve": breach_resolve,
        "sla_response_hours": resp_limit,
        "sla_resolve_hours": resolve_limit,
    }


def ticket_analytics(db: Session, company_id: int | None = None) -> dict:
    q = db.query(SupportTicket)
    if company_id is not None:
        from app.tenant_service import filter_by_company

        q = filter_by_company(q, SupportTicket, company_id)
    tickets = q.all()
    open_cnt = sum(1 for t in tickets if t.status in ("ouvert", "en_cours"))
    breached = sum(1 for t in tickets if sla_status(t)["breach_response"] or sla_status(t)["breach_resolve"])
    resolved = sum(1 for t in tickets if t.status in ("resolu", "ferme"))
    return {
        "total": len(tickets),
        "open": open_cnt,
        "resolved": resolved,
        "sla_breached": breached,
        "by_status": {
            "ouvert": sum(1 for t in tickets if t.status == "ouvert"),
            "en_cours": sum(1 for t in tickets if t.status == "en_cours"),
            "resolu": sum(1 for t in tickets if t.status == "resolu"),
            "ferme": sum(1 for t in tickets if t.status == "ferme"),
        },
    }


def _scoped_ticket(db: Session, ticket_id: int, company_id: int | None):
    q = db.query(SupportTicket).filter(SupportTicket.id == ticket_id)
    if company_id is not None:
        from app.tenant_service import filter_by_company

        q = filter_by_company(q, SupportTicket, company_id)
    return q.first()


def add_ticket_message(
    db: Session,
    ticket_id: int,
    author_id: int | None,
    body: str,
    *,
    is_internal: bool = False,
    author_name: str = "",
    company_id: int | None = None,
) -> SupportTicketMessage:
    ticket = _scoped_ticket(db, ticket_id, company_id)
    if not ticket:
        raise ValueError("Ticket introuvable")
    if not body.strip():
        raise ValueError("Message vide")
    msg = SupportTicketMessage(
        ticket_id=ticket_id,
        author_id=author_id,
        author_name=author_name,
        body=body.strip(),
        is_internal=is_internal,
        created_at=_now(),
    )
    db.add(msg)
    if not ticket.first_response_at and author_id:
        ticket.first_response_at = _now()
    if ticket.status == "ouvert":
        ticket.status = "en_cours"
    db.commit()
    db.refresh(msg)
    return msg


def assign_ticket(db: Session, ticket_id: int, user_id: int, *, company_id: int | None = None) -> SupportTicket:
    ticket = _scoped_ticket(db, ticket_id, company_id)
    if not ticket:
        raise ValueError("Ticket introuvable")
    ticket.assigned_to = user_id
    if ticket.status == "ouvert":
        ticket.status = "en_cours"
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        create_app_notification(
            db,
            user_id=user.id,
            type_="info",
            title="Ticket assigné",
            message=ticket.subject or ticket.reference,
            category="ticket",
        )
    db.commit()
    db.refresh(ticket)
    return ticket


def list_ticket_messages(db: Session, ticket_id: int, *, company_id: int | None = None) -> list[dict]:
    if company_id is not None and not _scoped_ticket(db, ticket_id, company_id):
        raise ValueError("Ticket introuvable")
    rows = db.query(SupportTicketMessage).filter(
        SupportTicketMessage.ticket_id == ticket_id
    ).order_by(SupportTicketMessage.id).all()
    return [
        {
            "id": m.id,
            "author_name": m.author_name,
            "body": m.body,
            "is_internal": m.is_internal,
            "created_at": m.created_at,
        }
        for m in rows
    ]
