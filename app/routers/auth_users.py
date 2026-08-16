"""Routes authentification et gestion utilisateurs."""
import secrets
from datetime import date, datetime, timezone
from typing import List, Optional

from app.permissions import flatten_role_permissions

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_permission,
    verify_password,
)
from app.database import get_db
from app.models import User
from app.role_constants import ROLE_LABELS, ROLE_PERMISSIONS
from app.permissions import valid_role_codes
from app.services.password_service import (
    admin_reset_password,
    apply_user_password,
    assert_password_ok,
    find_user_by_login,
    generate_temp_password,
    generate_username,
    get_password_policy,
    send_password_reset_email,
    set_user_password,
    unlock_user_account,
    user_security_flags,
)
from app.services.audit_log import log_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str  # email ou nom d'utilisateur
    password: str


class TokenOut(BaseModel):
    access_token: str = ""
    token_type: str = "bearer"
    user: Optional["UserOut"] = None
    requires_2fa: bool = False
    challenge_token: str = ""
    must_change_password: bool = False
    password_expired: bool = False
    requires_password_change: bool = False
    dashboard_view: str = "dashboard"
    dashboard_title: str = ""
    session_timeout_minutes: int = 720
    welcome_message: str = ""
    recent_logins: List[dict] = []


class ForgotPasswordIn(BaseModel):
    email: str


class LoginHistoryOut(BaseModel):
    logged_at: str
    ip_address: str
    user_agent: str = ""


class Login2FAIn(BaseModel):
    challenge_token: str
    code: str


class RequiredPasswordChangeIn(BaseModel):
    current_password: str = ""
    new_password: str
    confirm_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str = ""
    email: str
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    department: str = ""
    role: str
    permissions: List[str] = []
    is_active: bool
    must_change_password: bool = False
    password_expired: bool = False
    requires_password_change: bool = False
    password_expires_at: str = ""
    last_password_change: str = ""
    locked_until: str = ""
    failed_login_attempts: int = 0


class CreateUserOut(UserOut):
    temp_password: str = ""


class UserIn(BaseModel):
    email: str
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    department: str = ""
    role: str = "viewer"
    password: str = ""
    is_active: bool = True


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


class RoleInfo(BaseModel):
    id: str
    label: str
    permissions: list[str]


def _user_out(user: User, db: Session) -> UserOut:
    from app.services.security_service import get_user_security, is_locked

    flags = user_security_flags(user, db)
    sec = get_user_security(db, user.id)
    locked = is_locked(sec)
    return UserOut(
        id=user.id,
        username=user.username or "",
        email=user.email,
        first_name=getattr(user, "first_name", "") or "",
        last_name=getattr(user, "last_name", "") or "",
        full_name=user.full_name or "",
        department=getattr(user, "department", "") or "",
        role=user.role,
        permissions=flatten_role_permissions(user.role, db),
        is_active=user.is_active,
        must_change_password=flags["must_change_password"],
        password_expired=flags["password_expired"],
        requires_password_change=flags["requires_password_change"],
        password_expires_at=flags["password_expires_at"],
        last_password_change=getattr(user, "last_password_change", "") or "",
        locked_until=sec.locked_until if locked else "",
        failed_login_attempts=sec.failed_login_attempts or 0,
    )


def _apply_names(data: UserIn | UserUpdate, user: User):
    fn = getattr(data, "first_name", None)
    ln = getattr(data, "last_name", None)
    if fn is not None:
        user.first_name = (fn or "").strip()
    if ln is not None:
        user.last_name = (ln or "").strip()
    if getattr(data, "full_name", None) is not None and data.full_name:
        user.full_name = data.full_name.strip()
    elif user.first_name or user.last_name:
        user.full_name = f"{user.first_name} {user.last_name}".strip()
    if getattr(data, "department", None) is not None:
        user.department = (data.department or "").strip()


def _finish_login(user: User, request: Request, db: Session) -> TokenOut:
    from app.models_prefs import LoginLog
    from app.services.auth_login_service import build_login_extras
    from app.services.security_service import clear_failed_login, register_session

    flags = user_security_flags(user, db)
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")[:200]
    db.add(LoginLog(
        user_id=user.id, user_email=user.email, success=True, ip_address=ip,
        logged_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), user_agent=ua,
    ))
    db.commit()
    clear_failed_login(db, user.id)
    token, jti = create_access_token(user.id, user.email, user.role, db=db)
    register_session(db, user.id, jti, ip, ua)
    try:
        log_audit(
            db,
            "login",
            "admin",
            "user",
            user.id,
            "login success",
            user.id,
            user.email,
            ip,
            user_agent=ua,
        )
        db.commit()
    except Exception:
        # Ne pas bloquer la connexion si le journal d'audit échoue.
        pass
    out = _user_out(user, db)
    extras = build_login_extras(user, db)
    return TokenOut(
        access_token=token,
        user=out,
        must_change_password=flags["must_change_password"],
        password_expired=flags["password_expired"],
        requires_password_change=flags["requires_password_change"],
        **extras,
    )


@router.get("/password-policy")
def password_policy_public(db: Session = Depends(get_db)):
    return get_password_policy(db)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    from app.models_prefs import LoginLog
    from app.rate_limit import check_rate_limit, client_rate_key
    from app.services.security_service import (
        create_2fa_challenge,
        get_user_security,
        is_locked,
        record_failed_login,
    )

    try:
        check_rate_limit(client_rate_key(request, "login"))
    except ValueError as exc:
        raise HTTPException(429, str(exc))

    login_id = data.email.strip()
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")[:200]
    user = find_user_by_login(db, login_id)
    if not user or not user.is_active:
        if user:
            record_failed_login(db, user, ip)
            try:
                log_audit(
                    db,
                    "login",
                    "admin",
                    "user",
                    user.id,
                    "login failed (inactive or not found)",
                    user.id,
                    user.email,
                    ip,
                    user_agent=ua,
                )
                db.commit()
            except Exception:
                pass
        raise HTTPException(401, "Identifiant ou mot de passe incorrect")
    sec = get_user_security(db, user.id)
    if is_locked(sec):
        raise HTTPException(
            423,
            "Compte temporairement verrouillé — réessayez dans quelques minutes ou contactez un administrateur.",
        )
    if not verify_password(data.password, user.password_hash):
        record_failed_login(db, user, ip)
        db.add(LoginLog(
            user_email=user.email, success=False, ip_address=ip,
            logged_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            user_agent=request.headers.get("user-agent", "")[:200],
        ))
        db.commit()
        try:
            log_audit(
                db,
                "login",
                "admin",
                "user",
                user.id,
                "login failed (bad password)",
                user.id,
                user.email,
                ip,
                user_agent=ua,
            )
            db.commit()
        except Exception:
            pass
        raise HTTPException(401, "Identifiant ou mot de passe incorrect")
    if sec.totp_enabled:
        challenge = create_2fa_challenge(db, user.id)
        flags = user_security_flags(user, db)
        return TokenOut(
            requires_2fa=True,
            challenge_token=challenge,
            must_change_password=flags["must_change_password"],
            password_expired=flags["password_expired"],
            requires_password_change=flags["requires_password_change"],
        )
    return _finish_login(user, request, db)


@router.post("/login/2fa", response_model=TokenOut)
def login_2fa(data: Login2FAIn, request: Request, db: Session = Depends(get_db)):
    from app.rate_limit import check_rate_limit, client_rate_key
    from app.services.security_service import consume_2fa_challenge, verify_totp

    try:
        check_rate_limit(client_rate_key(request, "login-2fa"))
    except ValueError as exc:
        raise HTTPException(429, str(exc))

    user = consume_2fa_challenge(db, data.challenge_token)
    if not user:
        raise HTTPException(401, "Session 2FA expirée")
    if not verify_totp(db, user.id, data.code):
        ip = request.client.host if request.client else ""
        ua = request.headers.get("user-agent", "")[:200]
        try:
            log_audit(
                db,
                "login",
                "admin",
                "user",
                user.id,
                "login failed (2FA invalid)",
                user.id,
                user.email,
                ip,
                user_agent=ua,
            )
            db.commit()
        except Exception:
            pass
        raise HTTPException(401, "Code 2FA invalide")
    return _finish_login(user, request, db)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_out(user, db)


@router.post("/change-password-required")
def change_password_required(
    body: RequiredPasswordChangeIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.auth_login_service import build_login_extras

    if body.new_password != body.confirm_password:
        raise HTTPException(400, "Les mots de passe ne correspondent pas")
    flags = user_security_flags(user, db)
    first_login = flags["must_change_password"] and not flags["password_expired"]
    if not first_login:
        if not body.current_password:
            raise HTTPException(400, "Mot de passe actuel requis")
        if not verify_password(body.current_password, user.password_hash):
            label = "actuel" if flags["password_expired"] else "temporaire"
            raise HTTPException(400, f"Mot de passe {label} incorrect")
    set_user_password(db, user, body.new_password, must_change=False)
    extras = build_login_extras(user, db)
    return {
        "ok": True,
        "user": _user_out(user, db),
        "requires_password_change": False,
        **extras,
    }


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    """Demande de réinitialisation — notification aux administrateurs (sans révéler si le compte existe)."""
    from app.rate_limit import check_rate_limit, client_rate_key
    from app.services.notify import create_app_notification

    try:
        check_rate_limit(client_rate_key(request, "forgot-password"), max_calls=8, window_sec=3600)
    except ValueError as exc:
        raise HTTPException(429, str(exc))

    login_id = body.email.strip()
    user = find_user_by_login(db, login_id) if login_id else None
    if user and user.is_active:
        admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
        for admin in admins:
            create_app_notification(
                db,
                user_id=admin.id,
                type_="warn",
                title="Demande de réinitialisation mot de passe",
                message=f"L'utilisateur {user.full_name or user.email} a demandé une réinitialisation de mot de passe.",
                category="security",
            )
        db.commit()
    return {
        "ok": True,
        "message": "Si un compte correspond à cet identifiant, un administrateur a été notifié.",
    }


@router.get("/login-history", response_model=List[LoginHistoryOut])
def my_login_history(
    limit: int = 8,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.auth_login_service import recent_login_history

    return recent_login_history(db, user.id, limit=min(limit, 20))


@router.post("/logout")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.auth import decode_token
    from app.services.security_service import revoke_token_jti

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = decode_token(auth[7:])
            revoke_token_jti(db, payload.get("jti"))
        except Exception:
            pass
    try:
        ip = request.client.host if request.client else ""
        ua = request.headers.get("user-agent", "")[:200]
        log_audit(
            db,
            "logout",
            "admin",
            "user",
            user.id,
            "logout",
            user.id,
            user.email,
            ip,
            user_agent=ua,
        )
        db.commit()
    except Exception:
        pass
    return {"ok": True, "message": "Déconnecté"}


users_router = APIRouter(prefix="/api/users", tags=["users"])


@users_router.get("", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    users = db.query(User).order_by(User.email).all()
    return [_user_out(u, db) for u in users]


@users_router.post("", response_model=CreateUserOut)
def create_user(
    data: UserIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    if data.role not in valid_role_codes(db):
        raise HTTPException(400, f"Rôle invalide. Choix : {', '.join(sorted(valid_role_codes(db)))}")
    email = data.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Cet email est déjà utilisé")
    first = (data.first_name or "").strip()
    last = (data.last_name or "").strip()
    if not first and not last and data.full_name:
        parts = data.full_name.strip().split(None, 1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""
    if not first or not last:
        raise HTTPException(400, "Le prénom et le nom sont obligatoires")
    username = generate_username(first, last, db)
    auto_temp = not (data.password or "").strip()
    temp_password = generate_temp_password() if auto_temp else ""
    plain = (data.password or "").strip() or temp_password
    if not auto_temp:
        assert_password_ok(plain, db)
    # Tout nouveau compte doit changer son mot de passe à la première connexion
    force_change_on_first_login = True
    user = User(
        email=email,
        username=username,
        first_name=first,
        last_name=last,
        department=(data.department or "").strip(),
        full_name=(data.full_name or f"{first} {last}".strip()),
        role=data.role,
        password_hash=hash_password(secrets.token_urlsafe(16)),
        must_change_password=force_change_on_first_login,
        is_active=data.is_active,
        created_at=date.today(),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    db.add(user)
    db.flush()
    apply_user_password(
        db,
        user,
        plain,
        must_change=force_change_on_first_login,
        check_history=not auto_temp,
        check_strength=not auto_temp,
    )
    db.commit()
    db.refresh(user)
    db.refresh(user)
    out = _user_out(user, db)
    return CreateUserOut(**out.model_dump(), temp_password=temp_password)


@users_router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("users.manage")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    if data.role is not None:
        if data.role not in valid_role_codes(db):
            raise HTTPException(400, "Rôle invalide")
        user.role = data.role
    _apply_names(data, user)
    if data.is_active is not None:
        if user.id == current.id and not data.is_active:
            raise HTTPException(400, "Vous ne pouvez pas désactiver votre propre compte")
        user.is_active = data.is_active
    if data.password:
        apply_user_password(db, user, data.password, must_change=True)
    user.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.commit()
    db.refresh(user)
    return _user_out(user, db)


@users_router.post("/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    temp = admin_reset_password(db, user)
    from app.services.notify import create_app_notification

    create_app_notification(
        db,
        user_id=user.id,
        type_="security",
        title="Mot de passe réinitialisé",
        message="Un administrateur a réinitialisé votre mot de passe. Connectez-vous avec le mot de passe temporaire fourni et changez-le immédiatement.",
        category="security",
    )
    email_sent = send_password_reset_email(db, user, user.username or "", temp)
    db.commit()
    return {
        "ok": True,
        "username": user.username,
        "temp_password": temp,
        "email_sent": email_sent,
    }


@users_router.post("/{user_id}/unlock")
def unlock_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    unlock_user_account(db, user_id)
    return {"ok": True}


def _user_dependency_summary(db: Session, user_id: int, *, skip_tables: set[str]) -> list[tuple[str, str, int]]:
    """Parcourt tout le schéma (toutes les colonnes FK vers users.id) et compte les
    lignes liées à cet utilisateur — plutôt qu'une liste figée de tables, ce qui
    laisserait échapper toute nouvelle table ajoutée au fil du temps."""
    from sqlalchemy import text as sa_text
    from app.database import Base

    found = []
    for table in Base.metadata.sorted_tables:
        if table.name in skip_tables:
            continue
        for col in table.columns:
            for fk in col.foreign_keys:
                if fk.column.table.name == "users" and fk.column.name == "id":
                    try:
                        n = db.execute(
                            sa_text(f'SELECT COUNT(*) FROM "{table.name}" WHERE "{col.name}" = :uid'),
                            {"uid": user_id},
                        ).scalar()
                    except Exception:
                        n = 0
                    if n:
                        found.append((table.name, col.name, int(n)))
    return found


def _hard_delete_user(db: Session, user_id: int, current_id: int) -> None:
    if user_id == current_id:
        raise HTTPException(400, "Impossible de supprimer votre propre compte")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    from app.models_enterprise import UserSecurity, UserSession
    from app.models_prefs import AppNotification, PasswordHistory, UserPreferences

    # Ces tables ne sont que de la plomberie de compte (session, préférences d'affichage,
    # notifications reçues) — nettoyées automatiquement. Tout le reste (audit, documents
    # créés/validés par l'utilisateur...) représente un historique métier réel : on bloque
    # plutôt que de le faire disparaître silencieusement.
    cleaned = {"password_history", "user_sessions", "user_security", "user_preferences", "app_notifications"}
    blocking = _user_dependency_summary(db, user_id, skip_tables=cleaned)
    if blocking:
        parts = [f"{n} dans « {t.replace('_', ' ')} »" for t, _col, n in blocking[:6]]
        more = f" (+{len(blocking) - 6} autre(s) tables)" if len(blocking) > 6 else ""
        raise HTTPException(
            400,
            "Suppression impossible : cet utilisateur a un historique réel dans l'ERP "
            f"({', '.join(parts)}{more}). Désactivez son compte au lieu de le supprimer "
            "— cela bloque sa connexion tout en conservant l'historique et les documents qu'il a créés.",
        )

    db.query(PasswordHistory).filter(PasswordHistory.user_id == user_id).delete()
    db.query(UserSession).filter(UserSession.user_id == user_id).delete()
    db.query(UserSecurity).filter(UserSecurity.user_id == user_id).delete()
    db.query(UserPreferences).filter(UserPreferences.user_id == user_id).delete()
    db.query(AppNotification).filter(AppNotification.user_id == user_id).delete()
    db.delete(user)


@users_router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("users.manage")),
):
    _hard_delete_user(db, user_id, current.id)
    db.commit()
    return {"ok": True, "message": "Utilisateur supprimé définitivement"}


class BulkUsersIn(BaseModel):
    ids: List[int]
    action: str  # activate, deactivate, delete, reset_password
    role: Optional[str] = None


@users_router.post("/bulk")
def bulk_users(
    body: BulkUsersIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("users.manage")),
):
    """Actions groupées sur les utilisateurs."""
    if not body.ids:
        raise HTTPException(400, "Aucun utilisateur sélectionné")
    action = (body.action or "").strip().lower()
    if action not in ("activate", "deactivate", "delete", "reset_password", "set_role"):
        raise HTTPException(400, "Action invalide")
    results = {"ok": 0, "skipped": 0, "errors": []}
    for uid in body.ids:
        if uid == current.id and action in ("deactivate", "delete"):
            results["skipped"] += 1
            results["errors"].append(f"Compte courant ignoré (id {uid})")
            continue
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            results["skipped"] += 1
            continue
        try:
            if action == "activate":
                user.is_active = True
            elif action == "deactivate":
                user.is_active = False
            elif action == "delete":
                _hard_delete_user(db, uid, current.id)
            elif action == "reset_password":
                admin_reset_password(db, user)
            elif action == "set_role":
                if not body.role or body.role not in valid_role_codes(db):
                    raise HTTPException(400, "Rôle invalide")
                user.role = body.role
            results["ok"] += 1
        except HTTPException:
            raise
        except Exception as exc:
            results["skipped"] += 1
            results["errors"].append(str(exc))
    db.commit()
    return {
        "ok": True,
        "processed": results["ok"],
        "skipped": results["skipped"],
        "errors": results["errors"],
        "message": f"{results['ok']} utilisateur(s) traité(s)",
    }


roles_router = APIRouter(prefix="/api/roles", tags=["roles"])


@roles_router.get("", response_model=List[RoleInfo])
def list_roles(_: User = Depends(require_permission("roles.view"))):
    return [
        RoleInfo(id=rid, label=ROLE_LABELS.get(rid, rid), permissions=sorted(perms))
        for rid, perms in ROLE_PERMISSIONS.items()
    ]
