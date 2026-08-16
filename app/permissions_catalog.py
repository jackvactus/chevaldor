"""Catalogue des permissions (modules × actions fines)."""
from app.rbac_matrix import (
    RBAC_ACTIONS,
    RBAC_MODULES,
    ROLE_LABELS,
    ROLE_LEGACY_PERMISSIONS,
    SYSTEM_ROLES,
    default_matrix_for_role,
    matrix_to_flat_permissions,
    normalize_role,
)
from app.role_constants import ROLE_PERMISSIONS

# Compatibilité
ACTIONS = RBAC_ACTIONS
MODULE_ACTIONS = RBAC_MODULES

PERMISSIONS_CATALOG = {
    "dashboard": "Tableau de bord",
    "clients": "Clients CRM",
    "deals": "Pipeline / Affaires",
    "quotes": "Devis",
    "invoices": "Factures",
    "projects": "Projets",
    "trainings": "Formations",
    "stock": "Stock",
    "accounting": "Comptabilité",
    "clientele": "Clientèle PC",
    "suppliers": "Fournisseurs",
    "purchases": "Achats",
    "treasury": "Trésorerie",
    "journal": "Écritures comptables",
    "comptarep": "États comptables",
    "analytic": "Budgets / Analytique",
    "hr": "Ressources humaines",
    "exports": "Exports",
    "imports": "Import données",
    "data.import": "Import données (legacy)",
    "users.manage": "Gestion utilisateurs",
    "roles.manage": "Gestion des rôles",
    "roles.view": "Voir les rôles",
    "audit.view": "Journal d'audit",
    "audit": "Audit",
    "settings.manage": "Paramètres système",
    "attachments": "Pièces jointes",
}


def all_permission_ids():
    return list(PERMISSIONS_CATALOG.keys())
