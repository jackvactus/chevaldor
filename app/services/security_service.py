"""2FA TOTP, verrouillage compte, sessions."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
from sqlalchemy.orm import Session

from app.models import User
from app.models_enterprise import UserSecurity, UserSession, PendingLogin2FA

MAX_FAILED = 5
LOCK_MINUTES = 15


def _lock_limits(db: Session) -> tuple[int, int]:
    try:
        from app.services.password_service import get_lock_settings
        return get_lock_settings(db)
    except Exception:
        return MAX_FAILED, LOCK_MINUTES


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def get_user_security(db: Session, user_id: int) -> UserSecurity:
    sec = db.query(UserSecurity).filter(UserSecurity.user_id == user_id).first()
    if not sec:
        sec = UserSecurity(user_id=user_id)
        db.add(sec)
        db.flush()
    return sec


def is_locked(sec: UserSecurity) -> bool:
    if not sec.locked_until:
        return False
    try:
        until = datetime.fromisoformat(sec.locked_until.replace("Z", ""))
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except ValueError:
        return False


def record_failed_login(db: Session, user: User, ip: str = ""):
    max_failed, lock_minutes = _lock_limits(db)
    sec = get_user_security(db, user.id)
    sec.failed_login_attempts = (sec.failed_login_attempts or 0) + 1
    if sec.failed_login_attempts >= max_failed:
        until = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)
        sec.locked_until = until.strftime("%Y-%m-%dT%H:%M:%S")
    db.commit()


def clear_failed_login(db: Session, user_id: int):
    sec = get_user_security(db, user_id)
    sec.failed_login_attempts = 0
    sec.locked_until = ""
    db.commit()


def setup_totp(db: Session, user: User) -> dict:
    sec = get_user_security(db, user.id)
    if not sec.totp_secret:
        sec.totp_secret = pyotp.random_base32()
        db.commit()
    totp = pyotp.TOTP(sec.totp_secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="Peya Company ERP")
    return {"secret": sec.totp_secret, "provisioning_uri": uri, "enabled": sec.totp_enabled}


def enable_totp(db: Session, user: User, code: str) -> bool:
    sec = get_user_security(db, user.id)
    if not sec.totp_secret:
        return False
    totp = pyotp.TOTP(sec.totp_secret)
    if not totp.verify(code, valid_window=1):
        return False
    sec.totp_enabled = True
    db.commit()
    return True


def verify_totp(db: Session, user_id: int, code: str) -> bool:
    sec = db.query(UserSecurity).filter(UserSecurity.user_id == user_id).first()
    if not sec or not sec.totp_enabled or not sec.totp_secret:
        return True
    return pyotp.TOTP(sec.totp_secret).verify(code, valid_window=1)


def create_2fa_challenge(db: Session, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
    db.query(PendingLogin2FA).filter(PendingLogin2FA.user_id == user_id).delete()
    db.add(PendingLogin2FA(user_id=user_id, challenge_token=token, expires_at=expires))
    db.commit()
    return token


def consume_2fa_challenge(db: Session, token: str) -> User | None:
    row = db.query(PendingLogin2FA).filter(PendingLogin2FA.challenge_token == token).first()
    if not row:
        return None
    try:
        exp = datetime.fromisoformat(row.expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            db.delete(row)
            db.commit()
            return None
    except ValueError:
        pass
    user = db.query(User).filter(User.id == row.user_id).first()
    db.delete(row)
    db.commit()
    return user


def register_session(db: Session, user_id: int, jti: str, ip: str, user_agent: str):
    db.add(UserSession(
        user_id=user_id,
        token_jti=jti,
        ip_address=ip or "",
        user_agent=(user_agent or "")[:300],
        created_at=_now_iso(),
        last_seen_at=_now_iso(),
    ))
    db.commit()


def revoke_session(db: Session, session_id: int, user_id: int):
    s = db.query(UserSession).filter(UserSession.id == session_id, UserSession.user_id == user_id).first()
    if s:
        s.revoked = True
        db.commit()


def revoke_token_jti(db: Session, jti: str | None) -> bool:
    """Révoque la session liée au jti du jeton (logout)."""
    if not jti:
        return False
    row = db.query(UserSession).filter(UserSession.token_jti == jti).first()
    if not row:
        return False
    row.revoked = True
    db.commit()
    return True


def list_sessions(db: Session, user_id: int):
    return db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked == False,
    ).order_by(UserSession.id.desc()).limit(20).all()
