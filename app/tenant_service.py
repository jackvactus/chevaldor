"""Isolation multi-société — filtrage par company_id utilisateur."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models import User
from app.models_enterprise import Company
from app.services.security_service import get_user_security


def resolve_company_id(db: Session, user_id: int) -> int:
    sec = get_user_security(db, user_id)
    if sec.company_id:
        return int(sec.company_id)
    default = db.query(Company).filter(Company.is_default == True).first()  # noqa: E712
    if default:
        return int(default.id)
    any_c = db.query(Company).order_by(Company.id).first()
    return int(any_c.id) if any_c else 1


def get_company_id(db: Session, user: User) -> int:
    return resolve_company_id(db, user.id)


def filter_by_company(q: Query, model, company_id: int) -> Query:
    if not hasattr(model, "company_id"):
        return q
    return q.filter(or_(model.company_id == company_id, model.company_id.is_(None)))


def stamp_company(obj, company_id: int) -> None:
    if hasattr(obj, "company_id") and getattr(obj, "company_id", None) is None:
        obj.company_id = company_id


def get_entity_or_404(db: Session, model, entity_id: int, company_id: int, label: str = "Élément"):
    obj = db.query(model).filter(model.id == entity_id).first()
    if not obj:
        raise HTTPException(404, f"{label} introuvable")
    cid = getattr(obj, "company_id", None)
    if cid is not None and int(cid) != int(company_id):
        raise HTTPException(404, f"{label} introuvable")
    return obj


def ensure_user_company(db: Session, user_id: int) -> int:
    """Attribue la société par défaut si l'utilisateur n'en a pas."""
    sec = get_user_security(db, user_id)
    if sec.company_id:
        return int(sec.company_id)
    cid = resolve_company_id(db, user_id)
    sec.company_id = cid
    db.flush()
    return cid
