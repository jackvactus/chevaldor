"""Aide à la connexion : tableau de bord par rôle, historique, session."""
from __future__ import annotations

from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models import User
from app.models_prefs import LoginLog, SystemSettings
from app.permissions import has_module_action
from app.rbac_matrix import ROLE_LANDING_TITLE, ROLE_LANDING_VIEW, normalize_role


def session_timeout_minutes(db: Session) -> int:
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if row and row.session_timeout_min and row.session_timeout_min > 0:
        return int(row.session_timeout_min)
    return 720


def resolve_dashboard(user: User, db: Session) -> dict:
    role = normalize_role(user.role or "auditeur")
    view = ROLE_LANDING_VIEW.get(role, "dashboard")
    title = ROLE_LANDING_TITLE.get(role, "Tableau de bord")

    if not has_module_action(user.role, view if view not in ("home", "bi") else "dashboard", "view", db):
        for fallback, mod in (
            ("home", "dashboard"),
            ("dashboard", "dashboard"),
            ("deals", "deals"),
            ("comptarep", "comptarep"),
            ("stock", "stock"),
            ("treasury", "treasury"),
            ("audit", "audit"),
            ("clients", "clients"),
        ):
            if has_module_action(user.role, mod, "view", db):
                view, title = fallback, ROLE_LANDING_TITLE.get(role, "Tableau de bord")
                break

    return {"view": view, "title": title}


def recent_login_history(db: Session, user_id: int, limit: int = 5) -> List[dict]:
    rows = (
        db.query(LoginLog)
        .filter(LoginLog.user_id == user_id, LoginLog.success == True)
        .order_by(LoginLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "logged_at": r.logged_at or "",
            "ip_address": r.ip_address or "",
            "user_agent": (r.user_agent or "")[:80],
        }
        for r in rows
    ]


def build_login_extras(user: User, db: Session) -> dict:
    dash = resolve_dashboard(user, db)
    return {
        "dashboard_view": dash["view"],
        "dashboard_title": dash["title"],
        "session_timeout_minutes": session_timeout_minutes(db),
        "welcome_message": f"Bienvenue, {user.full_name or user.first_name or user.email}",
        "recent_logins": recent_login_history(db, user.id),
    }
