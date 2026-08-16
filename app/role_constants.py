"""Constantes rôles système — délégation vers rbac_matrix."""
from app.rbac_matrix import (
    ROLE_LABELS,
    ROLE_LEGACY_PERMISSIONS,
    ROLE_LANDING_TITLE,
    ROLE_LANDING_VIEW,
    ROLE_ALIASES,
    SYSTEM_ROLES,
    matrix_to_flat_permissions,
    default_matrix_for_role,
    normalize_role,
)

# Compatibilité imports existants
ROLE_PERMISSIONS = {
    role: matrix_to_flat_permissions(default_matrix_for_role(role)) | ROLE_LEGACY_PERMISSIONS.get(role, set())
    for role in SYSTEM_ROLES
}
ROLE_PERMISSIONS["manager"] = ROLE_PERMISSIONS["dg"]
ROLE_PERMISSIONS["viewer"] = ROLE_PERMISSIONS["auditeur"]
