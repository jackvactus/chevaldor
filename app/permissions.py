"""Permissions par rôle (système, surcharges matrice, personnalisés)."""
import json
from typing import Optional, Set

from sqlalchemy.orm import Session

from app.permissions_catalog import ACTIONS, MODULE_ACTIONS
from app.rbac_matrix import normalize_role, default_matrix_for_role, matrix_to_flat_permissions, ROLE_LEGACY_PERMISSIONS
from app.role_constants import ROLE_LABELS, ROLE_PERMISSIONS


def _matrix_to_flat(matrix: dict) -> Set[str]:
    flat: Set[str] = set()
    for mod, acts in (matrix or {}).items():
        if not isinstance(acts, dict):
            continue
        if any(acts.get(a) for a in ACTIONS):
            flat.add(mod)
        for act in ACTIONS:
            if acts.get(act):
                flat.add(f"{mod}.{act}")
    return flat


def get_role_matrix(role: str, db: Session) -> dict:
    from app.models_rbac import CustomRole, RoleMatrixOverride

    role = normalize_role(role)

    if role.startswith("custom_"):
        cr = db.query(CustomRole).filter(CustomRole.code == role, CustomRole.is_active == True).first()
        if cr and cr.permissions_json:
            try:
                data = json.loads(cr.permissions_json)
                if isinstance(data, dict) and data:
                    return data
            except json.JSONDecodeError:
                pass
        return default_matrix_for_role("auditeur")

    ov = db.query(RoleMatrixOverride).filter(RoleMatrixOverride.role_code == role).first()
    if ov and ov.matrix_json:
        try:
            data = json.loads(ov.matrix_json)
            if isinstance(data, dict) and data:
                return data
        except json.JSONDecodeError:
            pass
    return default_matrix_for_role(role if role in ROLE_PERMISSIONS else "auditeur")


def save_builtin_matrix(db: Session, role_code: str, matrix: dict) -> None:
    from datetime import datetime, timezone
    from app.models_rbac import RoleMatrixOverride

    from app.rbac_matrix import SYSTEM_ROLES
    if role_code not in SYSTEM_ROLES and role_code not in ROLE_PERMISSIONS:
        raise ValueError("Rôle système inconnu")
    ov = db.query(RoleMatrixOverride).filter(RoleMatrixOverride.role_code == role_code).first()
    payload = json.dumps(matrix or {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    if ov:
        ov.matrix_json = payload
        ov.updated_at = now
    else:
        db.add(RoleMatrixOverride(role_code=role_code, matrix_json=payload, updated_at=now))
    db.commit()


def has_module_action(role: str, module: str, action: str, db: Session) -> bool:
    role = normalize_role(role)
    if role == "admin":
        return True
    matrix = get_role_matrix(role, db)
    row = matrix.get(module) or {}
    return bool(row.get(action))


def flatten_role_permissions(role: str, db: Session) -> list[str]:
    role = normalize_role(role)
    if role == "admin":
        return sorted(ROLE_PERMISSIONS["admin"] | {"admin"})
    flat = _matrix_to_flat(get_role_matrix(role, db))
    legacy = ROLE_LEGACY_PERMISSIONS.get(role, set()) | ROLE_PERMISSIONS.get(role, set())
    flat |= legacy
    return sorted(flat)


def _custom_role_permissions(role: str, db: Session) -> Set[str]:
    return _matrix_to_flat(get_role_matrix(role, db))


def get_permissions_for_role(role: str, db: Optional[Session] = None) -> Set[str]:
    if db:
        return set(flatten_role_permissions(role, db))
    if role in ROLE_PERMISSIONS:
        return set(ROLE_PERMISSIONS[role])
    return set()


def has_permission(role: str, permission: str, db: Optional[Session] = None) -> bool:
    role = normalize_role(role)
    if role == "admin":
        return True
    if permission == "users.manage" and db:
        return has_module_action(role, "users", "update", db) or has_module_action(role, "users", "create", db)
    if permission in ("settings.manage", "data.reset") and role == "admin":
        return True
    if permission == "settings.manage" and db:
        return has_module_action(role, "settings", "update", db)
    if permission == "audit.view" and db:
        return has_module_action(role, "audit", "view", db)
    if permission == "roles.view" and db:
        return has_module_action(role, "users", "view", db) or permission in ROLE_LEGACY_PERMISSIONS.get(role, set())
    if permission == "data.import" and db:
        return has_module_action(role, "imports", "create", db) or has_module_action(role, "imports", "view", db)
    if not db:
        perms = ROLE_PERMISSIONS.get(role, set())
        return permission in perms
    perms = get_permissions_for_role(role, db)
    if permission in perms:
        return True
    if "." in permission:
        mod, act = permission.split(".", 1)
        if f"{mod}.{act}" in perms:
            return True
        if act in ("view", "export") and mod in perms:
            return True
    if permission in ("comptarep", "journal", "treasury", "analytic") and "accounting" in perms:
        return True
    return False


def valid_role_codes(db: Session) -> set:
    from app.models_rbac import CustomRole
    from app.rbac_matrix import ROLE_ALIASES, SYSTEM_ROLES

    codes = set(SYSTEM_ROLES) | set(ROLE_ALIASES.keys())
    for cr in db.query(CustomRole).filter(CustomRole.is_active == True).all():
        codes.add(cr.code)
    return codes
