"""Récupération intelligente — auto-fill clients, produits, comptes, taxes."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Client, Invoice, StockItem
from app.models_erp import Supplier, JournalLine, JournalEntry
from app.models_business_ext import ClientType
from app.services.account_resolver import resolve_product_accounts_db
from app.services.accounting_intelligence_service import get_suggestions, record_context_use


def _system_default_vat(db: Session) -> float:
    from app.fiscal_service import get_default_vat_rate
    return get_default_vat_rate(db)


def _resolve_vat_pct(client, db: Session | None = None) -> float:
    """Retourne le taux TVA client (0 % est une valeur valide)."""
    if getattr(client, "default_vat_pct", None) is not None:
        return float(client.default_vat_pct)
    if getattr(client, "vat_rate", None) is not None:
        return float(client.vat_rate)
    return _system_default_vat(db) if db else 0.0


def resolve_client_defaults(db: Session, client_id: int | None) -> dict[str, Any]:
    if not client_id:
        return {}
    c = db.query(Client).filter(Client.id == client_id).first()
    if not c:
        return {}
    out = {
        "client_id": c.id,
        "name": c.name,
        "payment_terms": c.payment_terms,
        "account_code": c.account_code,
        "discount_pct": float(getattr(c, "default_discount_pct", 0) or 0),
        "vat_pct": _resolve_vat_pct(c, db),
        "commission_pct": float(getattr(c, "default_commission_pct", 0) or 0),
        "withholding_pct": float(getattr(c, "default_withholding_pct", 0) or 0),
    }
    tid = getattr(c, "client_type_id", None)
    if tid:
        ct = db.query(ClientType).filter(ClientType.id == tid).first()
        if ct:
            out["client_type"] = ct.name
            ct_vat = ct.default_vat_pct
            if ct_vat is not None and getattr(c, "default_vat_pct", None) is None and getattr(c, "vat_rate", None) is None:
                out["vat_pct"] = float(ct_vat)
            out["commission_pct"] = out["commission_pct"] or float(ct.default_commission_pct or 0)
            out["withholding_pct"] = out["withholding_pct"] or float(ct.default_withholding_pct or 0)
    return out


def resolve_product_accounts(db: Session, stock_item_id: int | None = None, product_type: str = "SERVICE") -> dict[str, str]:
    item = None
    if stock_item_id:
        item = db.query(StockItem).filter(StockItem.id == stock_item_id).first()
        if item:
            product_type = getattr(item, "product_accounting_type", None) or product_type
    from app.services.account_resolver import resolve_product_accounts_db
    acc = resolve_product_accounts_db(db, item, product_type)
    return {
        "sale_account": acc.get("sale", ""),
        "purchase_account": acc.get("purchase", ""),
        "stock_account": acc.get("stock", ""),
        "vat_account": acc.get("vat_collected", "") or acc.get("vat_deductible", ""),
    }


def resolve_supplier_accounts(db: Session, supplier_id: int | None) -> dict[str, Any]:
    if not supplier_id:
        return {}
    s = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not s:
        return {}
    return {
        "supplier_id": s.id,
        "name": s.name,
        "account_code": s.account_code,
        "payment_terms": s.payment_terms,
    }


def smart_lookup(
    db: Session,
    *,
    user_id: int | None = None,
    client_id: int | None = None,
    supplier_id: int | None = None,
    stock_item_id: int | None = None,
    product_type: str = "SERVICE",
    doc_type: str = "invoice",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "suggestions": get_suggestions(db, user_id),
        "client": resolve_client_defaults(db, client_id),
        "supplier": resolve_supplier_accounts(db, supplier_id),
        "accounts": resolve_product_accounts(db, stock_item_id, product_type),
        "doc_type": doc_type,
    }
    if client_id:
        last_inv = (
            db.query(Invoice)
            .filter(Invoice.client_id == client_id)
            .order_by(Invoice.id.desc())
            .first()
        )
        if last_inv:
            payload["last_invoice"] = {
                "vat_rate": float(last_inv.vat_rate or 0),
                "payment_terms_days": last_inv.payment_terms_days,
                "doc_type": getattr(last_inv, "doc_type", "invoice"),
            }
    return payload


def touch_context(db: Session, user_id: int | None, pairs: dict[str, str]) -> None:
    for k, v in pairs.items():
        record_context_use(db, user_id, k, v)
