"""Rôles personnalisés et matrice de permissions (système + surcharges)."""
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.database import get_db
from app.models import User
from app.models_rbac import CustomRole
from app.rbac_matrix import SYSTEM_ROLES
from app.role_constants import ROLE_LABELS, ROLE_PERMISSIONS
from app.permissions import flatten_role_permissions, get_role_matrix, save_builtin_matrix
from app.permissions_catalog import ACTIONS, MODULE_ACTIONS
from app.services.audit_log import log_audit

router = APIRouter(prefix="/api/roles", tags=["roles-rbac"])


class CustomRoleIn(BaseModel):
    code: str = ""
    label: str
    description: str = ""
    matrix: Dict[str, Dict[str, bool]] = {}
    copy_from: Optional[str] = None


class BuiltinMatrixIn(BaseModel):
    matrix: Dict[str, Dict[str, bool]]


class CustomRoleOut(BaseModel):
    id: int
    code: str
    label: str
    description: str
    is_active: bool
    matrix: Dict[str, Dict[str, bool]]
    permissions: List[str]


def _matrix_to_permissions(matrix: Dict[str, Dict[str, bool]]) -> List[str]:
    perms = set()
    for mod, actions in (matrix or {}).items():
        if any(actions.get(a) for a in ACTIONS):
            perms.add(mod)
        for act in ACTIONS:
            if actions.get(act):
                perms.add(f"{mod}.{act}")
    return sorted(perms)


@router.get("/catalog")
def permission_catalog(_: User = Depends(require_permission("roles.view"))):
    return {
        "modules": [{"id": m, "label": l} for m, l in MODULE_ACTIONS],
        "actions": ACTIONS,
        "builtin": [
            {"id": rid, "label": ROLE_LABELS.get(rid, rid), "permissions": sorted(ROLE_PERMISSIONS.get(rid, set()))}
            for rid in SYSTEM_ROLES
        ],
    }


@router.get("/matrix")
def all_roles_matrix(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("roles.view")),
):
    builtin = []
    for rid in SYSTEM_ROLES:
        mx = get_role_matrix(rid, db)
        builtin.append({
            "id": rid,
            "label": ROLE_LABELS.get(rid, rid),
            "type": "builtin",
            "editable": True,
            "matrix": mx,
            "permissions": _matrix_to_permissions(mx),
        })
    custom = []
    for cr in db.query(CustomRole).filter(CustomRole.is_active == True).order_by(CustomRole.label).all():
        mx = get_role_matrix(cr.code, db)
        custom.append({
            "id": cr.code,
            "db_id": cr.id,
            "label": cr.label,
            "type": "custom",
            "editable": True,
            "matrix": mx,
            "permissions": _matrix_to_permissions(mx),
        })
    return {"builtin": builtin, "custom": custom}


@router.put("/builtin/{role_code}")
def update_builtin_role_matrix(
    role_code: str,
    data: BuiltinMatrixIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("roles.manage")),
):
    if role_code not in ROLE_PERMISSIONS:
        raise HTTPException(400, "Rôle système inconnu")
    if role_code == "admin" and user.role != "admin":
        raise HTTPException(403, "Seul un administrateur peut modifier le rôle admin")
    old = json.dumps(get_role_matrix(role_code, db))
    save_builtin_matrix(db, role_code, data.matrix or {})
    ip = request.client.host if request.client else ""
    log_audit(
        db, "update", "admin", "builtin_role", 0, role_code,
        user.id, user.email, ip, old_value=old[:500],
        new_value=json.dumps(data.matrix)[:500],
    )
    return {"ok": True, "matrix": get_role_matrix(role_code, db)}


@router.post("/custom", response_model=CustomRoleOut)
def create_custom_role(
    data: CustomRoleIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("roles.manage")),
):
    code = (data.code or data.label).strip().lower().replace(" ", "_")
    if not code.startswith("custom_"):
        code = "custom_" + code
    if code in ROLE_PERMISSIONS:
        raise HTTPException(400, "Ce code est réservé aux rôles système")
    if db.query(CustomRole).filter(CustomRole.code == code).first():
        raise HTTPException(400, "Rôle déjà existant")
    from app.permissions_catalog import default_matrix_for_role

    matrix = data.matrix
    if data.copy_from and not matrix:
        matrix = get_role_matrix(data.copy_from, db) if data.copy_from.startswith("custom_") else default_matrix_for_role(data.copy_from)
    if not matrix:
        matrix = default_matrix_for_role("viewer")
    cr = CustomRole(
        code=code,
        label=data.label,
        description=data.description,
        permissions_json=json.dumps(matrix),
    )
    db.add(cr)
    db.commit()
    db.refresh(cr)
    ip = request.client.host if request.client else ""
    log_audit(db, "create", "admin", "role", cr.id, cr.label, user.id, user.email, ip, new_value=code)
    mx = get_role_matrix(cr.code, db)
    return CustomRoleOut(
        id=cr.id, code=cr.code, label=cr.label, description=cr.description or "",
        is_active=cr.is_active, matrix=mx, permissions=_matrix_to_permissions(mx),
    )


@router.put("/custom/{role_id}")
def update_custom_role(
    role_id: int,
    data: CustomRoleIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("roles.manage")),
):
    cr = db.query(CustomRole).filter(CustomRole.id == role_id).first()
    if not cr:
        raise HTTPException(404, "Rôle introuvable")
    old = cr.permissions_json
    if data.label:
        cr.label = data.label
    if data.description is not None:
        cr.description = data.description
    if data.matrix:
        cr.permissions_json = json.dumps(data.matrix)
    db.commit()
    ip = request.client.host if request.client else ""
    log_audit(
        db, "update", "admin", "role", cr.id, cr.label, user.id, user.email, ip,
        old_value=(old or "")[:500], new_value=cr.permissions_json[:500],
    )
    return {"ok": True}


@router.delete("/custom/{role_id}")
def delete_custom_role(
    role_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("roles.manage")),
):
    cr = db.query(CustomRole).filter(CustomRole.id == role_id).first()
    if not cr:
        raise HTTPException(404)
    cr.is_active = False
    db.commit()
    log_audit(db, "delete", "admin", "role", cr.id, cr.label, user.id, user.email)
    return {"ok": True}
