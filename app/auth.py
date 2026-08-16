"""Authentification JWT + mots de passe."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

_DEFAULT_JWT_SECRET = "peya-company-erp-secret-change-in-production-2026"
SECRET_KEY = os.environ.get("PEYA_JWT_SECRET", _DEFAULT_JWT_SECRET)


def validate_jwt_secret_for_env() -> None:
    """Refuse le démarrage en production sans secret JWT explicite."""
    from app.server_config import is_production

    if not is_production():
        return
    explicit = os.environ.get("PEYA_JWT_SECRET", "").strip()
    if not explicit or explicit == _DEFAULT_JWT_SECRET:
        raise RuntimeError(
            "PEYA_JWT_SECRET obligatoire en production — définissez une clé forte (min. 32 caractères)."
        )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def token_expire_hours(db: Session = None) -> int:
    if db is None:
        return ACCESS_TOKEN_EXPIRE_HOURS
    try:
        from app.models_prefs import SystemSettings
        row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
        if row and row.session_timeout_min and row.session_timeout_min > 0:
            return max(1, int(row.session_timeout_min / 60))
    except Exception:
        pass
    return ACCESS_TOKEN_EXPIRE_HOURS


def create_access_token(user_id: int, email: str, role: str, jti: str = None, db: Session = None) -> tuple:
    import uuid
    hours = token_expire_hours(db)
    expire = datetime.now(timezone.utc) + timedelta(hours=hours)
    token_jti = jti or str(uuid.uuid4())
    payload = {"sub": str(user_id), "email": email, "role": role, "exp": expire, "jti": token_jti}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM), token_jti


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def is_session_revoked(db, payload: dict) -> bool:
    """True si le jeton est explicitement révoqué en base."""
    jti = payload.get("jti")
    if not jti:
        return False
    try:
        from app.models_enterprise import UserSession

        row = db.query(UserSession).filter(UserSession.token_jti == jti).first()
        if row is None:
            return False
        return bool(row.revoked)
    except Exception:
        return False


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if not creds or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise")
    try:
        payload = decode_token(creds.credentials)
        user_id = int(payload.get("sub", 0))
    except (JWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide ou expirée")
    if is_session_revoked(db, payload):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session révoquée")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utilisateur introuvable")
    return user


def require_permission(permission: str):
    from app.permissions import has_permission

    def checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_permission(user.role, permission, db):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Droits insuffisants")
        return user

    return checker
