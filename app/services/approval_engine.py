"""Moteur d'approbation dynamique — règles configurables, 3 niveaux, révision."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import User
from app.models_enterprise import ApprovalRequest, ApprovalStep
from app.models_platform import ApprovalRule
from app.services.notify import create_app_notification

DEFAULT_LEVELS = [
    {"role": "manager", "label": "Responsable"},
    {"role": "admin", "label": "Directeur"},
    {"role": "admin", "label": "DG"},
]

MODULE_LABELS = {
    "invoice": "Facture",
    "purchase": "Achat",
    "payment": "Paiement",
    "leave": "Congé",
    "recruitment": "Recrutement",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def seed_default_rules(db: Session, company_id: int | None = None) -> None:
    defaults = [
        ("invoice", 500_000),
        ("purchase", 1_000_000),
        ("payment", 2_000_000),
        ("leave", 0),
        ("recruitment", 0),
    ]
    for module, min_amt in defaults:
        exists = db.query(ApprovalRule).filter(
            ApprovalRule.module == module,
            ApprovalRule.company_id == company_id,
        ).first()
        if exists:
            continue
        db.add(ApprovalRule(
            company_id=company_id,
            module=module,
            min_amount=min_amt,
            levels_json=json.dumps(DEFAULT_LEVELS, ensure_ascii=False),
            is_active=True,
            created_at=_now(),
        ))
    db.commit()


def get_rule(db: Session, module: str, amount: float, company_id: int | None) -> Optional[ApprovalRule]:
    q = db.query(ApprovalRule).filter(
        ApprovalRule.module == module,
        ApprovalRule.is_active == True,
        ApprovalRule.min_amount <= amount,
    )
    if company_id:
        q = q.filter((ApprovalRule.company_id == company_id) | (ApprovalRule.company_id.is_(None)))
    return q.order_by(ApprovalRule.min_amount.desc()).first()


def needs_approval(db: Session, module: str, amount: float, company_id: int | None) -> bool:
    return get_rule(db, module, amount, company_id) is not None


def pending_for_entity(db: Session, entity_type: str, entity_id: int) -> Optional[ApprovalRequest]:
    return (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.entity_type == entity_type,
            ApprovalRequest.entity_id == entity_id,
            ApprovalRequest.status.in_(("pending", "revision")),
        )
        .first()
    )


def is_entity_approved(db: Session, entity_type: str, entity_id: int) -> bool:
    pending = pending_for_entity(db, entity_type, entity_id)
    if pending:
        return False
    approved = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.entity_type == entity_type,
            ApprovalRequest.entity_id == entity_id,
            ApprovalRequest.status == "approved",
        )
        .order_by(ApprovalRequest.id.desc())
        .first()
    )
    return approved is not None


def _parse_levels(rule: ApprovalRule | None) -> List[dict]:
    if not rule:
        return DEFAULT_LEVELS
    try:
        data = json.loads(rule.levels_json or "[]")
        return data if data else DEFAULT_LEVELS
    except json.JSONDecodeError:
        return DEFAULT_LEVELS


def _notify_approvers(db: Session, roles: List[str], title: str, amount: float) -> None:
    users = db.query(User).filter(User.is_active == True, User.role.in_(tuple(set(roles)))).all()
    for u in users[:5]:
        try:
            create_app_notification(
                db,
                user_id=u.id,
                type_="info",
                title="Validation requise",
                message=f"{title} — {amount:,.0f} FCFA",
                category="approval",
            )
        except Exception:
            pass


def submit_approval(
    db: Session,
    user: User,
    module: str,
    title: str,
    amount: float = 0,
    entity_type: str = "",
    entity_id: int | None = None,
    notes: str = "",
    company_id: int | None = None,
) -> ApprovalRequest:
    if entity_type and entity_id:
        existing = pending_for_entity(db, entity_type, entity_id)
        if existing:
            raise ValueError("Une demande d'approbation est déjà en cours")
    rule = get_rule(db, module, amount, company_id)
    levels = _parse_levels(rule)
    max_levels = len(levels)
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
    for idx, lvl in enumerate(levels, start=1):
        role = lvl.get("role", "manager")
        db.add(ApprovalStep(
            request_id=req.id,
            level=idx,
            approver_role=role,
            status="pending" if idx == 1 else "waiting",
        ))
    _notify_approvers(db, [levels[0].get("role", "manager")], title, amount)
    db.commit()
    db.refresh(req)
    return req


def decide_approval(
    db: Session,
    request_id: int,
    approver: User,
    action: str,
    comment: str = "",
) -> ApprovalRequest:
    action = (action or "approve").lower()
    if action not in ("approve", "reject", "revision"):
        raise ValueError("Action invalide (approve, reject, revision)")
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req or req.status not in ("pending", "revision"):
        raise ValueError("Demande introuvable ou déjà traitée")
    step = db.query(ApprovalStep).filter(
        ApprovalStep.request_id == request_id,
        ApprovalStep.level == req.current_level,
        ApprovalStep.status == "pending",
    ).first()
    if not step:
        raise ValueError("Étape invalide")
    allowed_roles = ("admin", "manager", "dg", "director")
    if approver.role not in allowed_roles and approver.id != step.approver_id:
        raise ValueError("Droits insuffisants pour valider")
    if action == "revision":
        step.status = "revision"
        step.approver_id = approver.id
        step.decided_at = _now()
        step.comment = comment or "Modification demandée"
        req.status = "revision"
    elif action == "reject":
        step.status = "rejected"
        step.approver_id = approver.id
        step.decided_at = _now()
        step.comment = comment
        req.status = "rejected"
    else:
        step.status = "approved"
        step.approver_id = approver.id
        step.decided_at = _now()
        step.comment = comment
        if req.current_level >= req.max_levels:
            req.status = "approved"
        else:
            req.current_level += 1
            nxt = db.query(ApprovalStep).filter(
                ApprovalStep.request_id == request_id,
                ApprovalStep.level == req.current_level,
            ).first()
            if nxt:
                nxt.status = "pending"
                _notify_approvers(db, [nxt.approver_role], req.title, req.amount or 0)
    requester = db.query(User).filter(User.id == req.requested_by).first()
    if requester:
        msg_map = {
            "approved": ("success", "Approuvé"),
            "rejected": ("warn", "Rejeté"),
            "revision": ("info", "Modification demandée"),
            "pending": ("info", "Niveau suivant"),
        }
        typ, lbl = msg_map.get(req.status, ("info", req.status))
        create_app_notification(
            db,
            user_id=requester.id,
            type_=typ,
            title=f"Approbation : {lbl}",
            message=f"{req.title} — {comment or 'sans commentaire'}",
            category="approval",
        )
    db.commit()
    db.refresh(req)
    return req
