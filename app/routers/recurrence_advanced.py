"""
Routes API pour la gestion des paiements récurrents.
CRUD complet + génération + calendrier.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Path, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List, Optional
from datetime import date, datetime, timedelta

from app.database import get_db
from app.auth import require_permission, get_current_user
from app.models import User, Client
from app.models_enterprise import ApprovalRequest, ApprovalStep, DocumentSignature
from app.tenant_service import get_company_id, filter_by_company
from app.models_recurring_advanced import (
    PaymentRecurrence, RecurrenceGeneration, RecurrenceHistory,
    PaymentCollection, CollectionPaymentDetail
)
from app.schemas_recurring import (
    PaymentRecurrenceIn, PaymentRecurrenceUpdate, PaymentRecurrenceOut,
    CollectionPaymentDetailIn, CollectionPaymentDetailOut,
    PaymentCollectionIn, PaymentCollectionOut,
    PaymentCollectionHistoryIn, RecurrenceGenerationIn,
)
from app.services.recurrence_service import PaymentRecurrenceService, PaymentCollectionService
from app.services.audit_log import log_audit
from app.services.workflow_service import submit_approval, decide_approval, pending_for_entity

router = APIRouter(prefix="/api/recurrence", tags=["recurrence"])


# ============================================================================
# PAIEMENTS RÉCURRENTS - CRUD
# ============================================================================

@router.get("/recurring-payments", response_model=List[PaymentRecurrenceOut])
def list_recurrences(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Lister les paiements récurrents."""
    company_id = get_company_id(user, db)
    
    query = db.query(PaymentRecurrence).filter_by(company_id=company_id)
    
    if status:
        query = query.filter_by(status=status)
    if client_id:
        query = query.filter_by(client_id=client_id)
    
    recurrences = query.offset(skip).limit(limit).all()
    return recurrences


@router.post("/recurring-payments", response_model=PaymentRecurrenceOut)
def create_recurrence(
    data: PaymentRecurrenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.create")),
):
    """Créer une nouvelle récurrence."""
    company_id = get_company_id(user, db)
    
    # Vérifier le client appartient à la companie
    from app.models import Client
    client = db.query(Client).filter_by(id=data.client_id, company_id=company_id).first()
    if not client:
        raise HTTPException(400, "Client not found in your company")
    
    service = PaymentRecurrenceService(db)
    recurrence = service.create_recurrence(data.dict(), company_id, user.id)
    
    db.commit()
    
    log_audit(db, "create", "recurrence", f"{recurrence.id}", None, None, user.id, user.email or "", "")
    db.commit()
    
    return recurrence


@router.get("/recurring-payments/{recurrence_id}", response_model=PaymentRecurrenceOut)
def get_recurrence(
    recurrence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Consulter une récurrence."""
    company_id = get_company_id(user, db)
    
    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")
    
    return recurrence


@router.put("/recurring-payments/{recurrence_id}", response_model=PaymentRecurrenceOut)
def update_recurrence(
    recurrence_id: int,
    data: PaymentRecurrenceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.modify")),
):
    """Mettre à jour une récurrence."""
    company_id = get_company_id(user, db)
    
    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")
    
    service = PaymentRecurrenceService(db)
    recurrence = service.update_recurrence(recurrence_id, data.dict(exclude_none=True), user.id)
    
    db.commit()
    
    log_audit(db, "update", "recurrence", f"{recurrence_id}", None, None, user.id, user.email or "", "")
    db.commit()
    
    return recurrence


@router.delete("/recurring-payments/{recurrence_id}")
def delete_recurrence(
    recurrence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.delete")),
):
    """Supprimer une récurrence (soft delete)."""
    company_id = get_company_id(user, db)
    
    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")
    
    recurrence.status = 'cancelled'
    recurrence.is_active = False
    db.commit()
    
    log_audit(db, "delete", "recurrence", f"{recurrence_id}", None, None, user.id, user.email or "", "")
    db.commit()
    
    return {"ok": True}


# ============================================================================
# GESTION D'ÉTAT
# ============================================================================

@router.post("/recurring-payments/{recurrence_id}/suspend")
def suspend_recurrence(
    recurrence_id: int,
    reason: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.modify")),
):
    """Suspendre une récurrence."""
    company_id = get_company_id(user, db)
    
    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")
    
    service = PaymentRecurrenceService(db)
    service.suspend_recurrence(recurrence_id, reason, user.id)
    db.commit()
    
    return {"ok": True, "status": "suspended"}


@router.post("/recurring-payments/{recurrence_id}/resume")
def resume_recurrence(
    recurrence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.modify")),
):
    """Reprendre une récurrence suspendue."""
    company_id = get_company_id(user, db)
    
    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")
    
    service = PaymentRecurrenceService(db)
    service.resume_recurrence(recurrence_id, user.id)
    db.commit()
    
    return {"ok": True, "status": "active"}


@router.post("/recurring-payments/{recurrence_id}/terminate")
def terminate_recurrence(
    recurrence_id: int,
    reason: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.modify")),
):
    """Terminer une récurrence."""
    company_id = get_company_id(user, db)
    
    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")
    
    service = PaymentRecurrenceService(db)
    service.terminate_recurrence(recurrence_id, reason, user.id)
    db.commit()
    
    return {"ok": True, "status": "terminated"}


# ============================================================================
# GÉNÉRATION DE FACTURES
# ============================================================================

@router.post("/recurring-payments/{recurrence_id}/generate")
def generate_invoice_for_recurrence(
    recurrence_id: int,
    data: Optional[RecurrenceGenerationIn] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.generate")),
):
    """Générer manuellement une facture pour une récurrence."""
    company_id = get_company_id(user, db)
    
    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")
    
    service = PaymentRecurrenceService(db)
    try:
        invoice = service._create_draft_invoice(recurrence, date.today())
        
        # Enregistrer la génération
        generation = RecurrenceGeneration(
            recurrence_id=recurrence_id,
            generated_invoice_id=invoice.id,
            scheduled_date=recurrence.next_due_date,
            actual_date=datetime.utcnow(),
            amount=recurrence.amount,
            status='success',
        )
        db.add(generation)
        db.commit()
        
        return {"ok": True, "invoice_id": invoice.id}
    except Exception as e:
        raise HTTPException(500, f"Generation failed: {str(e)}")


@router.get("/recurring-payments/generations")
def list_generations(
    recurrence_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Lister les générations effectuées."""
    company_id = get_company_id(user, db)
    
    query = db.query(RecurrenceGeneration).join(PaymentRecurrence).filter(
        PaymentRecurrence.company_id == company_id
    )
    
    if recurrence_id:
        query = query.filter_by(recurrence_id=recurrence_id)
    
    generations = query.order_by(RecurrenceGeneration.created_at.desc()).offset(skip).limit(limit).all()
    return generations


class RecurrenceApprovalIn(BaseModel):
    notes: Optional[str] = ""
    max_levels: int = 2
    amount: Optional[float] = None


class RecurrenceSignIn(BaseModel):
    signer_name: Optional[str] = None
    signature_png: str


@router.post("/recurring-payments/{recurrence_id}/approval")
def request_recurrence_approval(
    recurrence_id: int,
    data: RecurrenceApprovalIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.modify")),
):
    """Demande d'approbation pour une récurrence."""
    company_id = get_company_id(user, db)

    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")

    if pending_for_entity(db, "recurrence", recurrence_id):
        raise HTTPException(400, "Une demande d'approbation est déjà en cours pour cette récurrence")

    amount = data.amount if data.amount is not None else float(recurrence.amount or 0)
    req = submit_approval(
        db,
        user,
        module="payment",
        title=f"Validation récurrence {recurrence.name}",
        amount=amount,
        entity_type="recurrence",
        entity_id=recurrence_id,
        notes=data.notes or "",
        company_id=company_id,
    )
    return {"ok": True, "request_id": req.id, "status": req.status}


@router.get("/recurring-payments/{recurrence_id}/approval")
def get_recurrence_approval_status(
    recurrence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    company_id = get_company_id(user, db)

    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")

    req = db.query(ApprovalRequest).filter(
        ApprovalRequest.entity_type == "recurrence",
        ApprovalRequest.entity_id == recurrence_id,
    ).order_by(ApprovalRequest.id.desc()).first()

    if not req:
        return {"ok": True, "status": "none", "current_level": 0, "max_levels": 0, "steps": []}

    step_rows = db.query(ApprovalStep).filter(ApprovalStep.request_id == req.id).order_by(ApprovalStep.level).all()
    # Determine if current user can decide on this request
    can_decide = getattr(user, 'role', '') in ("admin", "manager", "dg", "director") and req.status in ("pending", "revision")

    return {
        "ok": True,
        "status": req.status,
        "request_id": req.id,
        "current_level": req.current_level,
        "max_levels": req.max_levels,
        "can_decide": can_decide,
        "steps": [
            {
                "level": step.level,
                "approver_role": step.approver_role,
                "status": step.status,
                "approver_id": step.approver_id,
                "comment": step.comment,
                "decided_at": step.decided_at,
            }
            for step in step_rows
        ],
    }


@router.post("/recurring-payments/{recurrence_id}/sign")
def sign_recurrence(
    recurrence_id: int,
    data: RecurrenceSignIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.modify")),
):
    company_id = get_company_id(user, db)

    recurrence = db.query(PaymentRecurrence).filter(
        PaymentRecurrence.id == recurrence_id,
        PaymentRecurrence.company_id == company_id,
    ).first()
    if not recurrence:
        raise HTTPException(404, "Recurrence not found")

    signature = DocumentSignature(
        document_type="recurrence",
        document_id=recurrence_id,
        signed_by=user.id,
        signer_name=data.signer_name or user.full_name or user.email or "",
        signature_png=data.signature_png[:500000],
        signed_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        ip_address="",
    )
    db.add(signature)
    db.commit()
    return {"ok": True, "signature_id": signature.id}


# ============================================================================
# CALENDRIER
# ============================================================================

@router.get("/calendar/{year}/{month}")
def get_payment_calendar(
    year: int,
    month: int = Path(..., ge=1, le=12),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Retourner le calendrier des paiements pour un mois."""
    company_id = get_company_id(user, db)
    
    service = PaymentRecurrenceService(db)
    
    # Limiter aux récurrences de la companie
    recurrences = service.db.query(PaymentRecurrence).filter(
        PaymentRecurrence.company_id == company_id,
        PaymentRecurrence.is_active == True,
    ).all()
    
    calendar = service.get_recurrence_calendar(company_id, year, month)
    return {"year": year, "month": month, "payments": calendar}


# ============================================================================
# FICHES DE COLLECTE
# ============================================================================

@router.post("/collections", response_model=PaymentCollectionOut)
def create_collection(
    data: PaymentCollectionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("collection.create")),
):
    """Créer une nouvelle fiche de collecte."""
    company_id = get_company_id(user, db)
    
    service = PaymentCollectionService(db)
    collection = service.create_collection(data.collection_date, data.agent_id, company_id)
    
    # Ajouter les paiements
    for payment_data in data.payments:
        service.add_payment_to_collection(collection.id, payment_data.dict(), user.id)
    
    db.commit()
    
    return collection


@router.get("/collections/{collection_id}", response_model=PaymentCollectionOut)
def get_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("collection.view")),
):
    """Consulter une fiche de collecte."""
    company_id = get_company_id(user, db)
    
    collection = db.query(PaymentCollection).filter(
        PaymentCollection.id == collection_id,
        PaymentCollection.company_id == company_id,
    ).first()
    
    if not collection:
        raise HTTPException(404, "Collection not found")
    
    # Ajouter les paiements
    payments = db.query(CollectionPaymentDetail).filter_by(collection_id=collection_id).all()
    return PaymentCollectionOut(
        id=collection.id,
        collection_date=collection.collection_date,
        agent_id=collection.agent_id,
        total_amount=collection.total_amount,
        expected_amount=collection.expected_amount,
        balance_amount=collection.balance_amount,
        status=collection.status,
        created_at=collection.created_at,
        payments=[CollectionPaymentDetailOut.from_orm(p) for p in payments],
    )


@router.put("/collections/{collection_id}/payments/{payment_id}")
def update_collection_payment(
    collection_id: int,
    payment_id: int,
    data: PaymentCollectionHistoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("collection.modify")),
):
    """Mettre à jour un paiement dans une collecte."""
    company_id = get_company_id(user, db)
    
    collection = db.query(PaymentCollection).filter(
        PaymentCollection.id == collection_id,
        PaymentCollection.company_id == company_id,
    ).first()
    
    if not collection:
        raise HTTPException(404, "Collection not found")
    
    payment = db.query(CollectionPaymentDetail).filter(
        CollectionPaymentDetail.id == payment_id,
        CollectionPaymentDetail.collection_id == collection_id,
    ).first()
    
    if not payment:
        raise HTTPException(404, "Payment not found")
    
    service = PaymentCollectionService(db)
    service.update_payment(
        payment_id,
        data.new_amount,
        data.new_status,
        data.modification_reason,
        user.id,
    )
    db.commit()
    
    return {"ok": True}


# ============================================================================
# KPIs - Indicateurs clés de performance
# ============================================================================

@router.get("/kpis")
def get_recurrence_kpis(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Obtenir les KPIs globaux des récurrences."""
    from app.services.recurrence_kpi_service import RecurrenceKPIService
    
    company_id = get_company_id(user, db)
    service = RecurrenceKPIService(db, company_id)
    return service.get_recurrence_kpis()


@router.get("/collections/kpis")
def get_collection_kpis(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Obtenir les KPIs des collections."""
    from app.services.recurrence_kpi_service import RecurrenceKPIService
    from datetime import datetime as dt
    
    company_id = get_company_id(user, db)
    service = RecurrenceKPIService(db, company_id)
    
    # Parser les dates
    date_from_obj = dt.fromisoformat(date_from).date() if date_from else None
    date_to_obj = dt.fromisoformat(date_to).date() if date_to else None
    
    return service.get_collection_kpis(date_from_obj, date_to_obj)


@router.get("/calendar/advanced/{year}/{month}")
def get_advanced_calendar(
    year: int,
    month: int,
    status_filter: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """
    Obtenir le calendrier avancé avec tous les paiements du mois.
    Format: { date: { payments: [...], summary: {...} } }
    """
    company_id = get_company_id(user, db)

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    def _ensure_day(d_str: str) -> dict:
        if d_str not in calendar_data:
            calendar_data[d_str] = {
                "date": d_str,
                "payments": [],
                "summary": {"expected": 0, "collected": 0, "pending": 0, "scheduled": 0},
            }
        return calendar_data[d_str]

    calendar_data: dict = {}

    # Uniquement les collectes / paiements réellement enregistrés (plus d'échéances planifiées).

    # Collections enregistrées
    collections = db.query(PaymentCollection).filter(
        PaymentCollection.company_id == company_id,
        PaymentCollection.collection_date >= start,
        PaymentCollection.collection_date <= end,
    ).all()
    
    # Organiser par date
    calendar_data = {}
    
    for collection in collections:
        collection_date = str(collection.collection_date)
        
        if collection_date not in calendar_data:
            calendar_data[collection_date] = {
                "date": collection_date,
                "payments": [],
                "summary": {
                    "expected": 0,
                    "collected": 0,
                    "pending": 0,
                    "scheduled": 0,
                }
            }
        
        # Ajouter les paiements
        payments = db.query(CollectionPaymentDetail).filter(
            CollectionPaymentDetail.collection_id == collection.id
        ).all()
        
        for p in payments:
            if status_filter and p.status != status_filter:
                continue
            if client_id and p.client_id != client_id:
                continue
            
            client = db.query(Client).filter(Client.id == p.client_id).first()
            
            calendar_data[collection_date]["payments"].append({
                "id": p.id,
                "recurrence_id": p.recurrence_id,
                "client_id": p.client_id,
                "client_name": client.name if client else "Unknown",
                "amount": float(p.payment_amount or 0),
                "expected_amount": float(p.expected_amount or 0),
                "status": p.status,
                "method": p.payment_method,
                "color": "green" if p.status == "completed" else ("orange" if p.status == "pending" else "red"),
            })
            
            # Mettre à jour le summary
            calendar_data[collection_date]["summary"]["expected"] += float(p.expected_amount or 0)
            calendar_data[collection_date]["summary"]["collected"] += float(p.payment_amount or 0) if p.status == "completed" else 0
            calendar_data[collection_date]["summary"]["pending"] += float(p.payment_amount or 0) if p.status == "pending" else 0

    month_summary = {
        "expected": round(sum(d["summary"]["expected"] for d in calendar_data.values()), 2),
        "collected": round(sum(d["summary"]["collected"] for d in calendar_data.values()), 2),
        "pending": round(sum(d["summary"]["pending"] for d in calendar_data.values()), 2),
        "scheduled": round(sum(d["summary"].get("scheduled", 0) for d in calendar_data.values()), 2),
        "days_with_events": len(calendar_data),
    }

    return {
        "year": year,
        "month": month,
        "start_date": str(start),
        "end_date": str(end),
        "data": calendar_data,
        "summary": month_summary,
    }


@router.get("/clients/summaries")
def get_client_summaries(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Retourne le total dû, payé et restant par client."""
    from app.models import Client

    company_id = get_company_id(user, db)

    client_query = db.query(Client.id, Client.name).filter(Client.company_id == company_id)
    client_rows = client_query.all()

    recurrences = db.query(
        PaymentRecurrence.client_id,
        func.sum(PaymentRecurrence.amount).label('total_due'),
        func.count(PaymentRecurrence.id).label('active_recurrences'),
    ).filter(
        PaymentRecurrence.company_id == company_id,
        PaymentRecurrence.is_active == True,
    ).group_by(PaymentRecurrence.client_id).all()

    payments = db.query(
        CollectionPaymentDetail.client_id,
        func.sum(CollectionPaymentDetail.payment_amount).label('total_paid'),
        func.count(CollectionPaymentDetail.id).label('paid_count'),
        func.sum(func.case([(CollectionPaymentDetail.status == 'late', 1)], else_=0)).label('overdue_count'),
        func.max(CollectionPaymentDetail.payment_date).label('last_payment_date'),
    ).join(PaymentCollection, CollectionPaymentDetail.collection_id == PaymentCollection.id).filter(
        PaymentCollection.company_id == company_id,
        CollectionPaymentDetail.status == 'completed',
    ).group_by(CollectionPaymentDetail.client_id).all()

    paid_map = {p.client_id: p for p in payments}
    recurrence_map = {r.client_id: r for r in recurrences}

    results = []
    for client_id, client_name in client_rows:
        total_due = float(getattr(recurrence_map.get(client_id), 'total_due', 0) or 0)
        total_paid = float(getattr(paid_map.get(client_id), 'total_paid', 0) or 0)
        remaining = max(total_due - total_paid, 0)
        progress_rate = round((total_paid / total_due) * 100, 2) if total_due > 0 else 0.0
        overdue_count = int(getattr(paid_map.get(client_id), 'overdue_count', 0) or 0)
        results.append({
            'client_id': client_id,
            'client_name': client_name,
            'total_due': total_due,
            'total_paid': total_paid,
            'remaining': remaining,
            'progress_rate': progress_rate,
            'overdue_count': overdue_count,
            'active_recurrences': int(getattr(recurrence_map.get(client_id), 'active_recurrences', 0) or 0),
            'last_payment_date': getattr(paid_map.get(client_id), 'last_payment_date', None),
        })

    return results


@router.get("/clients/{client_id}/financials")
def get_client_financials(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Retourne le suivi financier d'un client."""
    from app.models import Client

    company_id = get_company_id(user, db)
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == company_id,
    ).first()
    if not client:
        raise HTTPException(404, "Client not found")

    total_due = float(db.query(func.coalesce(func.sum(PaymentRecurrence.amount), 0)).filter(
        PaymentRecurrence.company_id == company_id,
        PaymentRecurrence.client_id == client_id,
        PaymentRecurrence.is_active == True,
    ).scalar() or 0)

    total_paid = float(db.query(func.coalesce(func.sum(CollectionPaymentDetail.payment_amount), 0)).join(
        PaymentCollection,
        CollectionPaymentDetail.collection_id == PaymentCollection.id,
    ).filter(
        PaymentCollection.company_id == company_id,
        CollectionPaymentDetail.client_id == client_id,
        CollectionPaymentDetail.status == 'completed',
    ).scalar() or 0)

    remaining = max(total_due - total_paid, 0)
    overdue_count = int(db.query(func.count(CollectionPaymentDetail.id)).join(
        PaymentCollection,
        CollectionPaymentDetail.collection_id == PaymentCollection.id,
    ).filter(
        PaymentCollection.company_id == company_id,
        CollectionPaymentDetail.client_id == client_id,
        CollectionPaymentDetail.status == 'late',
    ).scalar() or 0)

    payments = db.query(CollectionPaymentDetail).join(
        PaymentCollection,
        CollectionPaymentDetail.collection_id == PaymentCollection.id,
    ).filter(
        PaymentCollection.company_id == company_id,
        CollectionPaymentDetail.client_id == client_id,
    ).order_by(CollectionPaymentDetail.payment_date.desc()).limit(20).all()

    return {
        'client_id': client.id,
        'client_name': client.name,
        'total_due': total_due,
        'total_paid': total_paid,
        'remaining': remaining,
        'progress_rate': round((total_paid / total_due) * 100, 2) if total_due > 0 else 0.0,
        'overdue_count': overdue_count,
        'payments': [
            {
                'id': payment.id,
                'amount': float(payment.payment_amount or 0),
                'expected_amount': float(payment.expected_amount or 0),
                'payment_date': str(payment.payment_date),
                'status': payment.status,
                'method': payment.payment_method,
            }
            for payment in payments
        ],
    }


@router.get("/calendar/day/{payment_date}")
def get_daily_calendar(
    payment_date: date,
    status_filter: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.view")),
):
    """Calendrier des paiements pour une date donnée."""
    company_id = get_company_id(user, db)
    collections = db.query(PaymentCollection).filter(
        PaymentCollection.company_id == company_id,
        PaymentCollection.collection_date == payment_date,
    ).all()

    payments = []
    for collection in collections:
        details = db.query(CollectionPaymentDetail).filter(
            CollectionPaymentDetail.collection_id == collection.id,
        ).all()
        for payment in details:
            if status_filter and payment.status != status_filter:
                continue
            if client_id and payment.client_id != client_id:
                continue
            client = db.query(Client).filter(Client.id == payment.client_id).first()
            payments.append({
                'id': payment.id,
                'client_id': payment.client_id,
                'client_name': client.name if client else 'Unknown',
                'amount': float(payment.payment_amount or 0),
                'expected_amount': float(payment.expected_amount or 0),
                'status': payment.status,
                'method': payment.payment_method,
                'payment_date': str(payment.payment_date),
                'collection_id': collection.id,
            })

    return {
        'date': str(payment_date),
        'payments': payments,
        'summary': {
            'count': len(payments),
            'collected': sum(p['amount'] for p in payments if p['status'] == 'completed'),
            'expected': sum(p['expected_amount'] for p in payments),
        }
    }


@router.post("/import/collecte/preview")
async def preview_collecte_import(
    file: UploadFile = File(...),
    _: User = Depends(require_permission("recurrence.view")),
):
    from app.services.collecte_import_service import parse_collecte_workbook
    from app.upload_limits import read_bounded, assert_extension, SPREADSHEET_EXT

    assert_extension(file.filename, SPREADSHEET_EXT)
    content = await read_bounded(file)
    try:
        return parse_collecte_workbook(content, file.filename or "upload.xlsx")
    except Exception as e:
        raise HTTPException(400, f"Lecture impossible : {e}") from e


@router.post("/import/collecte")
async def import_collecte_recurrence(
    file: UploadFile = File(...),
    create_clients: bool = Form(True),
    mode: str = Form("merge"),
    frequency: str = Form("daily"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recurrence.create")),
):
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
        company_id = get_company_id(user, db)
        result = import_collecte_to_recurring(
            db,
            content,
            filename=file.filename or "upload.xlsx",
            create_clients=create_clients,
            frequency=freq,
            mode=mode,
            company_id=company_id,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(400, f"Import impossible : {e}") from e

    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "Import impossible"))

    return result
