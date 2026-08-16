"""Règles métier achats — factures fournisseurs."""
from fastapi import HTTPException

from app.models_erp import SupplierInvoice

# Seules les factures entièrement payées sont verrouillées pour les utilisateurs standards.
SUPPLIER_INVOICE_LOCKED_STATUSES = frozenset({"payée", "annulée"})


def _purchase_admin_override(user, db) -> bool:
    if not user:
        return False
    if getattr(user, "role", None) == "admin":
        return True
    if db:
        from app.permissions import has_module_action
        return has_module_action(user.role, "purchases", "approve", db)
    return False


def assert_supplier_invoice_mutable(
    inv: SupplierInvoice,
    user=None,
    db=None,
    *,
    allow_status_only: bool = False,
):
    if inv.status not in SUPPLIER_INVOICE_LOCKED_STATUSES:
        return
    if _purchase_admin_override(user, db):
        return
    if allow_status_only:
        return
    raise HTTPException(
        400,
        f"La facture fournisseur {inv.number or inv.id} est verrouillée (statut : {inv.status}). "
        "Repasser en brouillon ou contacter un administrateur.",
    )


def assert_supplier_invoice_deletable(inv: SupplierInvoice, user=None, db=None):
    """Suppression autorisée quel que soit le statut, à la demande explicite de
    l'utilisateur — l'appelant (routers/erp.py::delete_supplier_invoice) nettoie
    l'écriture comptable liée si la facture avait déjà été comptabilisée."""
    return
