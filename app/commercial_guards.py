"""Règles métier documents commerciaux (verrous)."""
from fastapi import HTTPException

from app.models import Invoice, Quote

INVOICE_LOCKED_STATUSES = frozenset({"envoyée", "payée", "en retard", "annulée"})
QUOTE_LOCKED_STATUSES = frozenset({"envoyé", "accepté", "refusé"})


def _invoice_admin_override(user, db) -> bool:
    if not user:
        return False
    if user.role == "admin":
        return True
    if db:
        from app.permissions import has_module_action
        return has_module_action(user.role, "invoices", "approve", db)
    return False


def assert_invoice_mutable(inv: Invoice, user=None, db=None, *, allow_status_only: bool = False):
    if inv.status not in INVOICE_LOCKED_STATUSES:
        return
    if _invoice_admin_override(user, db):
        return
    if allow_status_only:
        return
    raise HTTPException(
        400,
        f"La facture {inv.number or inv.id} est verrouillée (statut : {inv.status}). "
        "Seul un administrateur peut la repasser en brouillon.",
    )


def assert_invoice_deletable(inv: Invoice):
    """Suppression autorisée quel que soit le statut, à la demande explicite de
    l'utilisateur — les appelants (main.py::delete_invoice) nettoient l'écriture
    comptable liée si la facture avait déjà été comptabilisée."""
    return


def _quote_admin_override(user, db) -> bool:
    if not user:
        return False
    if user.role == "admin":
        return True
    if db:
        from app.permissions import has_module_action
        return has_module_action(user.role, "quotes", "approve", db)
    return False


def assert_quote_mutable(q: Quote, user=None, db=None):
    if q.status not in QUOTE_LOCKED_STATUSES:
        return
    if _quote_admin_override(user, db):
        return
    raise HTTPException(
        400,
        f"Le devis {q.number or q.id} est verrouillé (statut : {q.status}).",
    )


def assert_quote_deletable(q: Quote):
    """Suppression autorisée quel que soit le statut, à la demande explicite de
    l'utilisateur (les devis ne sont jamais comptabilisés directement, rien à nettoyer
    côté journal)."""
    return
