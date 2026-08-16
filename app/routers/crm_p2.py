"""API CRM Phase P2 — 360°, tickets SLA."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.auth import get_current_user
from app.database import get_db
from app.models import Client, User
from app.models_platform import SupportTicket
from app.services.crm_360_service import build_client_360
from app.services.ticket_service import (
    add_ticket_message,
    assign_ticket,
    list_ticket_messages,
    sla_status,
    ticket_analytics,
)
from app.tenant_service import get_company_id, get_entity_or_404

router = APIRouter(prefix="/api/erp/crm-p2", tags=["crm-p2"])


class TicketMessageIn(BaseModel):
    body: str
    is_internal: bool = False


class TicketAssignIn(BaseModel):
    user_id: int


@router.get("/clients/{client_id}/360")
def get_crm_360(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "view")),
):
    get_entity_or_404(db, Client, client_id, get_company_id(db, user), "Client")
    try:
        return build_client_360(db, client_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/tickets/analytics")
def get_ticket_analytics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ticket_analytics(db, company_id=get_company_id(db, user))


@router.get("/tickets/{tid}/messages")
def get_ticket_messages(tid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return list_ticket_messages(db, tid, company_id=get_company_id(db, user))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/tickets/{tid}/messages")
def post_ticket_message(
    tid: int,
    body: TicketMessageIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        msg = add_ticket_message(
            db, tid, user.id, body.body,
            is_internal=body.is_internal,
            author_name=user.full_name or user.email,
            company_id=get_company_id(db, user),
        )
        return {"ok": True, "id": msg.id}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/tickets/{tid}/assign")
def post_ticket_assign(
    tid: int,
    body: TicketAssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        assign_ticket(db, tid, body.user_id, company_id=get_company_id(db, user))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/tickets/{tid}/sla")
def get_ticket_sla(tid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.tenant_service import filter_by_company

    t = filter_by_company(db.query(SupportTicket).filter(SupportTicket.id == tid), SupportTicket, get_company_id(db, user)).first()
    if not t:
        raise HTTPException(404)
    return sla_status(t)
