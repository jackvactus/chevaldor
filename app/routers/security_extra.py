"""Sécurité — journal de connexion (admin)."""
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_permission
from app.database import get_db
from app.models import User
from app.models_prefs import LoginLog
from app.services.security_service import get_user_security

router = APIRouter(prefix="/api/security", tags=["security"])


class LoginLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_email: str
    success: bool
    ip_address: str
    logged_at: str
    user_agent: str = ""


@router.get("/login-logs", response_model=List[LoginLogOut])
def list_login_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    return db.query(LoginLog).order_by(LoginLog.id.desc()).limit(min(limit, 500)).all()


@router.get("/settings")
def security_settings_global(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    return {
        "session_timeout_minutes": 720,
        "max_failed_attempts": 5,
        "auto_logout": True,
        "two_factor_available": True,
    }
