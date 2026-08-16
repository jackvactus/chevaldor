"""Politique de mot de passe, temporaires, historique et expiration."""
from __future__ import annotations

import json
import re
import secrets
import string
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.models import User
from app.models_prefs import PasswordHistory, SystemSettings

DEFAULT_POLICY = {
    "min_length": 8,
    "uppercase": True,
    "lowercase": True,
    "digits": True,
    "special": True,
    "history_count": 5,
    "expiry_days": 90,
    "max_failed_attempts": 5,
    "lock_minutes": 15,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def get_password_policy(db: Session) -> dict:
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    raw = {}
    if row and row.password_policy_json:
        try:
            raw = json.loads(row.password_policy_json)
        except json.JSONDecodeError:
            raw = {}
    return {**DEFAULT_POLICY, **raw}


def get_lock_settings(db: Session) -> tuple[int, int]:
    p = get_password_policy(db)
    return int(p.get("max_failed_attempts", 5)), int(p.get("lock_minutes", 15))


def validate_password_strength(password: str, policy: Optional[dict] = None) -> list[str]:
    """Retourne la liste des erreurs (vide = OK)."""
    policy = policy or DEFAULT_POLICY
    errors: list[str] = []
    min_len = int(policy.get("min_length", 8))
    if len(password) < min_len:
        errors.append(f"Au moins {min_len} caractères")
    if policy.get("uppercase") and not re.search(r"[A-Z]", password):
        errors.append("Une majuscule")
    if policy.get("lowercase") and not re.search(r"[a-z]", password):
        errors.append("Une minuscule")
    if policy.get("digits") and not re.search(r"\d", password):
        errors.append("Un chiffre")
    if policy.get("special") and not re.search(r"[^A-Za-z0-9]", password):
        errors.append("Un caractère spécial")
    return errors


def assert_password_ok(password: str, db: Session):
    errs = validate_password_strength(password, get_password_policy(db))
    if errs:
        raise HTTPException(400, "Mot de passe non conforme : " + ", ".join(errs))


def _slug_ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]", "", s).lower()
    return s


def generate_username(first_name: str, last_name: str, db: Session) -> str:
    first = _slug_ascii((first_name or "").strip())[:1]
    last = _slug_ascii((last_name or "").strip())
    base = (first + last) or "user"
    if len(base) < 3:
        base = (base + "usr")[:8]
    candidate = base[:20]
    n = 0
    while db.query(User).filter(User.username == candidate).first():
        n += 1
        candidate = f"{base[:16]}{n}"
    return candidate


def generate_temp_password() -> str:
    """Mot de passe temporaire lisible, conforme à la politique par défaut."""
    year = date.today().year
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(2))
    return f"Temp#{year}{suffix}"


def password_is_expired(user: User, policy: dict) -> bool:
    if bool(getattr(user, "must_change_password", False)):
        return False
    days = int(policy.get("expiry_days") or 0)
    if days <= 0 or not user.last_password_change:
        return False
    try:
        changed = datetime.fromisoformat(user.last_password_change.replace("Z", ""))
        if changed.tzinfo is None:
            changed = changed.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) > changed + timedelta(days=days)


def compute_password_expires_at(user: User, policy: dict) -> str:
    days = int(policy.get("expiry_days") or 0)
    if days <= 0:
        return ""
    base = user.last_password_change or _now_iso()
    try:
        dt = datetime.fromisoformat(base.replace("Z", ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc)
    exp = dt + timedelta(days=days)
    return exp.strftime("%Y-%m-%dT%H:%M:%S")


def password_in_history(db: Session, user_id: int, plain: str, policy: dict) -> bool:
    count = int(policy.get("history_count", 5))
    if count <= 0:
        return False
    rows = (
        db.query(PasswordHistory)
        .filter(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.id.desc())
        .limit(count)
        .all()
    )
    return any(verify_password(plain, row.password_hash) for row in rows)


def is_password_reused(db: Session, user: User, plain: str, policy: dict) -> bool:
    if user.password_hash and verify_password(plain, user.password_hash):
        return True
    return password_in_history(db, user.id, plain, policy)


def record_password_history(db: Session, user_id: int, password_hash: str, policy: dict):
    if not password_hash:
        return
    db.add(PasswordHistory(user_id=user_id, password_hash=password_hash, created_at=_now_iso()))
    db.flush()
    count = int(policy.get("history_count", 5))
    if count > 0:
        excess = (
            db.query(PasswordHistory)
            .filter(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.id.desc())
            .offset(count)
            .all()
        )
        for row in excess:
            db.delete(row)


def apply_user_password(
    db: Session,
    user: User,
    new_password: str,
    *,
    must_change: bool = False,
    check_history: bool = True,
    check_strength: bool = True,
):
    """Met à jour le mot de passe sans commit."""
    policy = get_password_policy(db)
    if check_strength:
        assert_password_ok(new_password, db)
    if check_history and is_password_reused(db, user, new_password, policy):
        raise HTTPException(
            400,
            "Le nouveau mot de passe doit être différent des "
            f"{policy.get('history_count', 5)} derniers mots de passe.",
        )
    old_hash = user.password_hash
    user.password_hash = hash_password(new_password)
    user.must_change_password = must_change
    if not must_change:
        user.last_password_change = _now_iso()
        user.password_expires_at = compute_password_expires_at(user, policy)
    else:
        user.password_expires_at = ""
    user.updated_at = _now_iso()
    record_password_history(db, user.id, old_hash, policy)


def set_user_password(
    db: Session,
    user: User,
    new_password: str,
    *,
    must_change: bool = False,
    check_history: bool = True,
    check_strength: bool = True,
):
    apply_user_password(
        db,
        user,
        new_password,
        must_change=must_change,
        check_history=check_history,
        check_strength=check_strength,
    )
    db.commit()
    db.refresh(user)


def find_user_by_login(db: Session, login: str) -> User | None:
    s = login.strip()
    if not s:
        return None
    if "@" in s:
        return db.query(User).filter(User.email == s.lower()).first()
    return db.query(User).filter(User.username == s.lower()).first()


def user_security_flags(user: User, db: Session) -> dict:
    policy = get_password_policy(db)
    must_flag = bool(getattr(user, "must_change_password", False))
    expired = password_is_expired(user, policy)
    requires = must_flag or expired
    expires_at = getattr(user, "password_expires_at", "") or ""
    if not expires_at and user.last_password_change and int(policy.get("expiry_days") or 0) > 0:
        expires_at = compute_password_expires_at(user, policy)
    return {
        "must_change_password": must_flag,
        "password_expired": expired,
        "requires_password_change": requires,
        "password_expires_at": expires_at,
    }


def admin_reset_password(db: Session, user: User) -> str:
    temp = generate_temp_password()
    set_user_password(
        db,
        user,
        temp,
        must_change=True,
        check_history=False,
        check_strength=False,
    )
    return temp


def unlock_user_account(db: Session, user_id: int):
    from app.services.security_service import get_user_security

    sec = get_user_security(db, user_id)
    sec.failed_login_attempts = 0
    sec.locked_until = ""
    db.commit()


def send_password_reset_email(db: Session, user: User, username: str, temp_password: str) -> bool:
    """Envoie l'e-mail si SMTP est activé ; retourne True si envoyé."""
    from app.services.smtp_service import send_email_via_smtp

    name = user.full_name or user.first_name or "Utilisateur"
    body = (
        f"Bonjour {name},\n\n"
        "Un administrateur a réinitialisé votre accès à Peya Company ERP.\n\n"
        f"Nom d'utilisateur : {username}\n"
        f"Mot de passe temporaire : {temp_password}\n\n"
        "À la première connexion, vous devrez définir un mot de passe personnel.\n\n"
        "— Peya Company"
    )
    html_body = "<p>" + body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    result = send_email_via_smtp(
        db,
        to_email=user.email,
        subject="Peya ERP — Réinitialisation de votre mot de passe",
        body=html_body,
    )
    return bool(result.get("ok"))
