"""Comptes auxiliaires SYSCOHADA — 411xxx clients, 401xxx fournisseurs."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Account, Client
from app.models_erp import Supplier
from app.syscohada.constants import DEFAULT_ACCOUNTS


def auxiliary_code(prefix: str, entity_id: int) -> str:
    """Code auxiliaire : 41100042 / 40100017 (6 chiffres après préfixe classe)."""
    p = (prefix or "411")[:3]
    return f"{p}{int(entity_id):06d}"


def _ensure_chart_account(
    db: Session,
    *,
    code: str,
    label: str,
    class_code: str,
    parent_code: str,
    acc_type: str = "actif",
) -> Account:
    row = db.query(Account).filter(Account.code == code).first()
    if row:
        return row
    row = Account(
        code=code,
        label=label[:120],
        type=acc_type,
        class_code=class_code,
        parent_code=parent_code,
        level=3,
    )
    db.add(row)
    db.flush()
    return row


def ensure_client_auxiliary(db: Session, client: Client) -> str:
    """Crée le sous-compte 411xxx et l'associe au client."""
    if getattr(client, "account_code", None):
        return client.account_code
    code = auxiliary_code("411", client.id)
    _ensure_chart_account(
        db,
        code=code,
        label=f"Client — {client.name}",
        class_code="4",
        parent_code=DEFAULT_ACCOUNTS["clients"],
        acc_type="actif",
    )
    client.account_code = code
    db.flush()
    return code


def set_client_account_code(db: Session, client: Client, code: str) -> str:
    """Applique un compte auxiliaire choisi manuellement par l'utilisateur — crée l'entrée
    correspondante au plan comptable si elle n'existe pas encore (sinon la réutilise telle
    quelle). N'efface jamais l'ancien compte du plan comptable : seules les nouvelles écritures
    utiliseront le nouveau code, l'historique existant reste inchangé."""
    code = (code or "").strip()
    if not code:
        return ensure_client_auxiliary(db, client)
    _ensure_chart_account(
        db,
        code=code,
        label=f"Client — {client.name}",
        class_code=code[:1] or "4",
        parent_code=DEFAULT_ACCOUNTS["clients"],
        acc_type="actif",
    )
    client.account_code = code
    db.flush()
    return code


def ensure_supplier_auxiliary(db: Session, supplier: Supplier) -> str:
    if getattr(supplier, "account_code", None):
        return supplier.account_code
    code = auxiliary_code("401", supplier.id)
    _ensure_chart_account(
        db,
        code=code,
        label=f"Fournisseur — {supplier.name}",
        class_code="4",
        parent_code=DEFAULT_ACCOUNTS["suppliers"],
        acc_type="passif",
    )
    supplier.account_code = code
    db.flush()
    return code


def client_account_for_invoice(db: Session, client_id: int | None, accounts: dict) -> str:
    if not client_id:
        return accounts.get("clients", DEFAULT_ACCOUNTS["clients"])
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return accounts.get("clients", DEFAULT_ACCOUNTS["clients"])
    if not getattr(client, "account_code", None):
        ensure_client_auxiliary(db, client)
        db.refresh(client)
    return client.account_code or accounts.get("clients", DEFAULT_ACCOUNTS["clients"])


def supplier_account_for_invoice(db: Session, supplier_id: int | None, accounts: dict) -> str:
    if not supplier_id:
        return accounts.get("suppliers", DEFAULT_ACCOUNTS["suppliers"])
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        return accounts.get("suppliers", DEFAULT_ACCOUNTS["suppliers"])
    if not getattr(supplier, "account_code", None):
        ensure_supplier_auxiliary(db, supplier)
        db.refresh(supplier)
    return supplier.account_code or accounts.get("suppliers", DEFAULT_ACCOUNTS["suppliers"])


def backfill_auxiliary_accounts(db: Session) -> dict:
    """Attribue un compte auxiliaire à tous les tiers existants."""
    clients_ok = suppliers_ok = 0
    for c in db.query(Client).filter((Client.is_archived == False) | (Client.is_archived.is_(None))).all():  # noqa: E712
        if not getattr(c, "account_code", None) or c.account_code == "":
            ensure_client_auxiliary(db, c)
            clients_ok += 1
    for s in db.query(Supplier).filter((Supplier.is_archived == False) | (Supplier.is_archived.is_(None))).all():  # noqa: E712
        if not getattr(s, "account_code", None) or s.account_code == "":
            ensure_supplier_auxiliary(db, s)
            suppliers_ok += 1
    db.commit()
    return {"clients": clients_ok, "suppliers": suppliers_ok}
