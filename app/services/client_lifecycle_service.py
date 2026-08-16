"""Suppression / archivage client — analyse des liens sur toute la plateforme."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import (
    Activity,
    Client,
    ClientLedgerEntry,
    Deal,
    Invoice,
    Project,
    Quote,
    Training,
)
from app.models_business_ext import (
    CollectionCase,
    CollectionPayment,
    InvoiceRecurring,
    SalesContract,
)
from app.models_platform import ClientPortalAccess, SupportTicket
from app.services.audit_log import log_audit

# Liens métier : archivage obligatoire (pas de suppression physique)
_BLOCKING = (
    ("invoices", "facture(s)", Invoice),
    ("quotes", "devis", Quote),
    ("deals", "opportunité(s)", Deal),
    ("projects", "projet(s)", Project),
    ("sales_contracts", "contrat(s)", SalesContract),
    ("invoice_recurring", "plan(s) récurrent(s)", InvoiceRecurring),
    ("collection_cases", "dossier(s) recouvrement", CollectionCase),
)

# Supprimés avec le client si aucun lien bloquant
_CASCADE = (
    ("activities", "activité(s) CRM", Activity),
    ("client_ledger", "mouvement(s) clientèle", ClientLedgerEntry),
    ("collection_payments", "collecte(s)", CollectionPayment),
    ("portal_access", "accès portail", ClientPortalAccess),
)

# client_id mis à NULL
_NULLIFY = (
    ("trainings", "formation(s)", Training),
    ("support_tickets", "ticket(s)", SupportTicket),
)


def _count(db: Session, model, client_id: int) -> int:
    return db.query(model).filter(model.client_id == client_id).count()


def analyze_client_dependencies(db: Session, client_id: int) -> dict[str, Any]:
    """Inventaire complet des enregistrements liés à un client."""
    blocking: dict[str, dict] = {}
    removable: dict[str, dict] = {}
    blocking_total = 0

    for key, label, model in _BLOCKING:
        n = _count(db, model, client_id)
        if n:
            blocking[key] = {"label": label, "count": n}
            blocking_total += n

    for key, label, model in _CASCADE:
        n = _count(db, model, client_id)
        if n:
            removable[key] = {"label": label, "count": n, "action": "delete"}

    for key, label, model in _NULLIFY:
        n = _count(db, model, client_id)
        if n:
            removable[key] = {"label": label, "count": n, "action": "detach"}

    summary_parts = [f"{v['count']} {v['label']}" for v in blocking.values()]
    summary_parts += [f"{v['count']} {v['label']}" for v in removable.values()]
    summary = ", ".join(summary_parts)

    return {
        "client_id": client_id,
        "blocking": blocking,
        "removable": removable,
        "blocking_count": blocking_total,
        "can_hard_delete": blocking_total == 0,
        "summary": summary,
    }


def analyze_clients_bulk(db: Session, client_ids: list[int], *, company_id: Optional[int] = None) -> dict[str, Any]:
    """Synthèse avant action groupée."""
    rows = []
    totals: dict[str, int] = {}
    deletable = 0
    must_archive = 0

    for cid in client_ids:
        q = db.query(Client).filter(Client.id == cid)
        if company_id is not None:
            from app.tenant_service import filter_by_company

            q = filter_by_company(q, Client, company_id)
        obj = q.first()
        if not obj:
            continue
        a = analyze_client_dependencies(db, cid)
        a["name"] = obj.name
        rows.append(a)
        if a["can_hard_delete"]:
            deletable += 1
        else:
            must_archive += 1
        for key, info in {**a["blocking"], **a["removable"]}.items():
            totals[key] = totals.get(key, 0) + info["count"]

    platform_totals = []
    for key, label, _ in _BLOCKING + _CASCADE + _NULLIFY:
        if totals.get(key):
            lbl = next(x[1] for x in _BLOCKING + _CASCADE + _NULLIFY if x[0] == key)
            platform_totals.append({"key": key, "label": lbl, "count": totals[key]})

    return {
        "clients": rows,
        "total": len(rows),
        "deletable": deletable,
        "will_archive": must_archive,
        "platform_totals": platform_totals,
    }


def _archive_enabled(db: Session) -> bool:
    from app.models_prefs import SystemSettings

    sys = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    return bool(sys and getattr(sys, "archive_enabled", True))


def _archive_client(db: Session, client: Client, user_id: int, email: str, ip: str) -> None:
    if hasattr(client, "is_archived"):
        client.is_archived = True
    client.status = "inactif"
    log_audit(db, "archive", "crm", "client", client.id, client.name, user_id, email, ip)


def _cascade_cleanup(db: Session, client_id: int) -> None:
    for _, _, model in _CASCADE:
        db.query(model).filter(model.client_id == client_id).delete(synchronize_session=False)
    for _, _, model in _NULLIFY:
        db.query(model).filter(model.client_id == client_id).update(
            {model.client_id: None}, synchronize_session=False
        )


def delete_or_archive_client(
    db: Session,
    client_id: int,
    *,
    user_id: int,
    user_email: str,
    ip: str = "",
    allow_archive: bool = True,
    company_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    Analyse puis supprime ou archive.
    - Liens métier (factures, devis, deals…) → archivage
    - Sinon → nettoyage des liens légers + suppression
    """
    q = db.query(Client).filter(Client.id == client_id)
    if company_id is not None:
        from app.tenant_service import filter_by_company

        q = filter_by_company(q, Client, company_id)
    client = q.first()
    if not client:
        return {"status": "missing", "client_id": client_id}

    analysis = analyze_client_dependencies(db, client_id)
    name = client.name or f"#{client_id}"

    if analysis["blocking_count"] > 0:
        if allow_archive and _archive_enabled(db) and hasattr(client, "is_archived"):
            _archive_client(db, client, user_id, user_email, ip)
            return {
                "status": "archived",
                "client_id": client_id,
                "name": name,
                "analysis": analysis,
                "message": f"« {name} » archivé — {analysis['summary'] or 'données liées'}",
            }
        return {
            "status": "blocked",
            "client_id": client_id,
            "name": name,
            "analysis": analysis,
            "message": f"Impossible de supprimer « {name} » : {analysis['summary'] or 'données liées'}",
        }

    _cascade_cleanup(db, client_id)
    log_audit(db, "delete", "crm", "client", client_id, name, user_id, user_email, ip)
    db.delete(client)
    return {
        "status": "deleted",
        "client_id": client_id,
        "name": name,
        "analysis": analysis,
        "message": f"« {name} » supprimé",
    }


def format_bulk_delete_message(results: list[dict]) -> str:
    deleted = sum(1 for r in results if r.get("status") == "deleted")
    archived = sum(1 for r in results if r.get("status") == "archived")
    blocked = sum(1 for r in results if r.get("status") == "blocked")
    parts = []
    if deleted:
        parts.append(f"{deleted} supprimé(s)")
    if archived:
        parts.append(f"{archived} archivé(s) (factures, devis ou deals liés)")
    if blocked:
        parts.append(f"{blocked} non traité(s)")
    return " · ".join(parts) if parts else "Aucun client traité"
