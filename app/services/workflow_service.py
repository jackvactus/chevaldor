"""Workflows d'approbation multi-niveaux."""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import User
from app.models_enterprise import ApprovalRequest, ApprovalStep
from app.services.notify import create_app_notification


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def create_approval(
    db: Session,
    user: User,
    module: str,
    title: str,
    amount: float = 0,
    entity_type: str = "",
    entity_id: int = None,
    max_levels: int = 2,
    notes: str = "",
    company_id: int = None,
) -> ApprovalRequest:
    req = ApprovalRequest(
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        amount=amount,
        status="pending",
        requested_by=user.id,
        current_level=1,
        max_levels=max_levels,
        company_id=company_id,
        created_at=_now(),
        notes=notes,
    )
    db.add(req)
    db.flush()
    roles = ["manager", "admin"]
    for lvl in range(1, max_levels + 1):
        role = roles[min(lvl - 1, len(roles) - 1)]
        db.add(ApprovalStep(
            request_id=req.id,
            level=lvl,
            approver_role=role,
            status="pending" if lvl == 1 else "waiting",
        ))
    admins = db.query(User).filter(User.role.in_(("admin", "manager")), User.is_active == True).all()
    for adm in admins[:3]:
        try:
            create_app_notification(
                db,
                user_id=adm.id,
                type_="info",
                title="Demande d'approbation",
                message=f"{title} — {amount:,.0f} FCFA",
                category="approval",
            )
        except Exception:
            pass
    db.commit()
    db.refresh(req)
    return req


def decide_step(
    db: Session,
    request_id: int,
    approver: User,
    approve: bool,
    comment: str = "",
) -> ApprovalRequest:
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req or req.status != "pending":
        raise ValueError("Demande introuvable ou déjà traitée")
    step = db.query(ApprovalStep).filter(
        ApprovalStep.request_id == request_id,
        ApprovalStep.level == req.current_level,
        ApprovalStep.status == "pending",
    ).first()
    if not step:
        raise ValueError("Étape invalide")
    if approver.role not in ("admin", "manager") and approver.id != step.approver_id:
        raise ValueError("Droits insuffisants pour approuver")
    step.status = "approved" if approve else "rejected"
    step.approver_id = approver.id
    step.decided_at = _now()
    step.comment = comment
    if not approve:
        req.status = "rejected"
    elif req.current_level >= req.max_levels:
        req.status = "approved"
    else:
        req.current_level += 1
        nxt = db.query(ApprovalStep).filter(
            ApprovalStep.request_id == request_id,
            ApprovalStep.level == req.current_level,
        ).first()
        if nxt:
            nxt.status = "pending"
    requester = db.query(User).filter(User.id == req.requested_by).first()
    if requester:
        create_app_notification(
            db,
            user_id=requester.id,
            type_="success" if approve and req.status == "approved" else "warn",
            title=f"Approbation : {req.status}",
            message=f"{req.title} — niveau {step.level}",
            category="approval",
        )
    db.commit()
    db.refresh(req)
    return req


def submit_approval(
    db: Session,
    user: User,
    module: str,
    title: str,
    amount: float = 0,
    entity_type: str = "",
    entity_id: int = None,
    notes: str = "",
    company_id: int = None,
    max_levels: int = 2,
):
    """Compat wrapper — ancien nom submit_approval -> create_approval"""
    return create_approval(
        db=db,
        user=user,
        module=module,
        title=title,
        amount=amount,
        entity_type=entity_type,
        entity_id=entity_id,
        max_levels=max_levels,
        notes=notes,
        company_id=company_id,
    )


def decide_approval(db: Session, request_id: int, approver: User, approve: bool, comment: str = ""):
    """Compat wrapper — ancien nom decide_approval -> decide_step"""
    return decide_step(db, request_id, approver, approve, comment)


def pending_for_entity(db: Session, entity_type: str, entity_id: int) -> bool:
    """Retourne True si une demande d'approbation pendante existe pour l'entité."""
    q = db.query(ApprovalRequest).filter(
        ApprovalRequest.entity_type == entity_type,
        ApprovalRequest.entity_id == entity_id,
        ApprovalRequest.status == "pending",
    ).first()
    return bool(q)
