"""
Matrice RBAC métier Peya Company — source unique des droits par rôle système.
Chaque module expose : view, create, update, delete, export, approve, validate, cancel, print, archive.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Tuple

# Actions fines (niveau ERP professionnel)
RBAC_ACTIONS: List[str] = [
    "view",
    "create",
    "update",
    "delete",
    "export",
    "approve",
    "validate",
    "cancel",
    "print",
    "archive",
]

# (id technique, libellé menu)
RBAC_MODULES: List[Tuple[str, str]] = [
    ("dashboard", "Tableau de bord / Pilotage"),
    ("clients", "Clients CRM"),
    ("deals", "Pipeline commercial"),
    ("quotes", "Devis"),
    ("invoices", "Factures"),
    ("projects", "Projets"),
    ("trainings", "Formations"),
    ("stock", "Stock & inventaires"),
    ("purchases", "Achats"),
    ("suppliers", "Fournisseurs"),
    ("accounting", "Comptabilité"),
    ("journal", "Journaux & écritures"),
    ("treasury", "Trésorerie & caisse"),
    ("comptarep", "États & rapports financiers"),
    ("analytic", "Budgets & analytique"),
    ("clientele", "Clientèle PC"),
    ("hr", "Ressources humaines"),
    ("users", "Utilisateurs"),
    ("settings", "Paramètres système"),
    ("audit", "Audit & traçabilité"),
    ("imports", "Import de données"),
    ("exports", "Exports & rapports"),
    ("cms", "Contenu site vitrine"),
]

ROLE_ALIASES = {
    "manager": "dg",
    "viewer": "auditeur",
}

SYSTEM_ROLES = (
    "admin",
    "dg",
    "daf",
    "compta",
    "stock",
    "commercial",
    "caissier",
    "auditeur",
)

ROLE_LABELS = {
    "admin": "Super Administrateur",
    "dg": "Directeur Général",
    "daf": "Directeur Financier",
    "compta": "Comptable",
    "stock": "Responsable Stock",
    "commercial": "Commercial",
    "caissier": "Caissier",
    "auditeur": "Auditeur",
    "manager": "Directeur Général",
    "viewer": "Auditeur",
}

# Vue ERP par défaut après connexion
ROLE_LANDING_VIEW = {
    "admin": "home",
    "dg": "home",
    "daf": "treasury",
    "compta": "comptarep",
    "stock": "stock",
    "commercial": "deals",
    "caissier": "treasury",
    "auditeur": "audit",
    "manager": "home",
    "viewer": "audit",
}

ROLE_LANDING_TITLE = {
    "admin": "Tableau de bord — Administration",
    "dg": "Tableau de bord — Direction générale",
    "daf": "Tableau de bord — Direction financière",
    "compta": "Tableau de bord — Comptabilité",
    "stock": "Tableau de bord — Stock",
    "commercial": "Tableau de bord — Commercial",
    "caissier": "Tableau de bord — Caisse",
    "auditeur": "Tableau de bord — Audit",
}


def _empty_row() -> Dict[str, bool]:
    return {a: False for a in RBAC_ACTIONS}


def _full_row() -> Dict[str, bool]:
    return {a: True for a in RBAC_ACTIONS}


def _view_export_row() -> Dict[str, bool]:
    r = _empty_row()
    r["view"] = True
    r["export"] = True
    r["print"] = True
    return r


def _consult_row() -> Dict[str, bool]:
    """Consultation + export (DG, auditeur)."""
    return _view_export_row()


def _crud_row(*, can_delete: bool = False, can_approve: bool = False) -> Dict[str, bool]:
    r = _empty_row()
    for k in ("view", "create", "update", "export", "print"):
        r[k] = True
    if can_delete:
        r["delete"] = True
    if can_approve:
        r["approve"] = True
        r["validate"] = True
    return r


def _matrix_template(rows: Dict[str, Dict[str, bool]]) -> Dict[str, Dict[str, bool]]:
    base = {mod: _empty_row() for mod, _ in RBAC_MODULES}
    for mod, row in rows.items():
        if mod in base:
            base[mod] = {**_empty_row(), **row}
    return base


def _admin_matrix() -> Dict[str, Dict[str, bool]]:
    return {mod: _full_row() for mod, _ in RBAC_MODULES}


def _dg_matrix() -> Dict[str, Dict[str, bool]]:
    v = _consult_row()
    appr = {**v, "approve": True, "validate": True}
    return _matrix_template({
        "dashboard": v,
        "clients": v,
        "deals": v,
        "quotes": v,
        "invoices": appr,
        "projects": v,
        "trainings": v,
        "stock": v,
        "purchases": v,
        "suppliers": v,
        "accounting": v,
        "journal": v,
        "treasury": appr,
        "comptarep": v,
        "analytic": appr,
        "clientele": v,
        "hr": v,
        "audit": v,
        "exports": v,
        "imports": {**_empty_row(), "view": True},
    })


def _daf_matrix() -> Dict[str, Dict[str, bool]]:
    v = _consult_row()
    op = _crud_row(can_approve=True)
    return _matrix_template({
        "dashboard": v,
        "accounting": op,
        "journal": op,
        "treasury": op,
        "comptarep": op,
        "analytic": op,
        "suppliers": v,
        "purchases": v,
        "invoices": v,
        "clients": v,
        "exports": v,
        "audit": v,
    })


def _compta_matrix() -> Dict[str, Dict[str, bool]]:
    op = _crud_row(can_approve=True)
    v = _consult_row()
    ex = _view_export_row()
    return _matrix_template({
        "dashboard": v,
        "invoices": {**v, "update": True, "export": True},
        "accounting": op,
        "journal": op,
        "treasury": {**v, "update": True},
        "comptarep": op,
        "analytic": v,
        "suppliers": {**v, "create": True, "update": True},
        "purchases": v,
        "deals": v,
        "clientele": v,
        "exports": ex,
    })


def _stock_matrix() -> Dict[str, Dict[str, bool]]:
    op = _crud_row(can_delete=True)
    v = _consult_row()
    return _matrix_template({
        "dashboard": v,
        "stock": op,
        "purchases": {**v, "create": True, "update": True},
        "suppliers": v,
        "projects": v,
        "exports": v,
    })


def _commercial_matrix() -> Dict[str, Dict[str, bool]]:
    op = _crud_row()
    v = _consult_row()
    ex = _view_export_row()
    return _matrix_template({
        "dashboard": v,
        "clients": op,
        "deals": op,
        "quotes": op,
        "invoices": op,
        "projects": v,
        "clientele": v,
        "exports": ex,
        "imports": {**_empty_row(), "view": True, "create": True},
    })


def _caissier_matrix() -> Dict[str, Dict[str, bool]]:
    cash = _crud_row(can_approve=True)
    v = _consult_row()
    return _matrix_template({
        "dashboard": v,
        "treasury": cash,
        "journal": {**v, "create": True, "update": True},
        "invoices": {**v, "update": True},
        "clientele": v,
        "exports": v,
    })


def _auditeur_matrix() -> Dict[str, Dict[str, bool]]:
    v = _view_export_row()
    return _matrix_template({mod: v for mod, _ in RBAC_MODULES if mod not in ("users", "settings")} | {
        "users": _empty_row(),
        "settings": _empty_row(),
        "audit": v,
    })


ROLE_MATRIX_BUILDERS = {
    "admin": _admin_matrix,
    "dg": _dg_matrix,
    "daf": _daf_matrix,
    "compta": _compta_matrix,
    "stock": _stock_matrix,
    "commercial": _commercial_matrix,
    "caissier": _caissier_matrix,
    "auditeur": _auditeur_matrix,
}


def normalize_role(role: str) -> str:
    return ROLE_ALIASES.get(role or "", role or "auditeur")


def default_matrix_for_role(role_id: str) -> dict:
    role_id = normalize_role(role_id)
    builder = ROLE_MATRIX_BUILDERS.get(role_id)
    if builder:
        return deepcopy(builder())
    return deepcopy(_auditeur_matrix())


def matrix_to_flat_permissions(matrix: dict) -> set:
    flat = set()
    for mod, acts in (matrix or {}).items():
        if not isinstance(acts, dict):
            continue
        if any(acts.get(a) for a in RBAC_ACTIONS):
            flat.add(mod)
        for act in RBAC_ACTIONS:
            if acts.get(act):
                flat.add(f"{mod}.{act}")
    return flat


# Permissions legacy (compatibilité routes / has_permission string)
ROLE_LEGACY_PERMISSIONS = {
    "admin": {
        "admin", "users.manage", "roles.manage", "roles.view", "audit.view",
        "settings.manage", "data.reset", "data.import", "currencies.manage",
    },
    "dg": {"roles.view", "audit.view", "data.import"},
    "daf": {"audit.view"},
    "compta": set(),
    "stock": set(),
    "commercial": {"data.import"},
    "caissier": set(),
    "auditeur": {"audit.view", "roles.view"},
}
