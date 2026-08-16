"""Résolution comptes SYSCOHADA — ID ou code vers code comptable."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Account


def account_code(
    db: Session,
    *,
    code: str = "",
    account_id: int | None = None,
    fallback: str = "",
) -> str:
    if code and str(code).strip():
        return str(code).strip()
    if account_id:
        row = db.query(Account).filter(Account.id == account_id).first()
        if row and row.code:
            return row.code
    return fallback


def resolve_product_accounts_db(
    db: Session,
    item,
    product_type: str,
) -> dict[str, str]:
    """Fusionne typologie + comptes article (ID ou code)."""
    from app.syscohada.product_types import resolve_line_accounts

    ptype = getattr(item, "product_accounting_type", None) or product_type
    acc = resolve_line_accounts(ptype)
    if not item:
        return {k: v or "" for k, v in acc.items() if v}

    acc["purchase"] = account_code(
        db,
        code=getattr(item, "purchase_account", ""),
        account_id=getattr(item, "purchase_account_id", None),
        fallback=acc.get("purchase") or "",
    )
    acc["sale"] = account_code(
        db,
        code=getattr(item, "sale_account", ""),
        account_id=getattr(item, "sale_account_id", None),
        fallback=acc.get("sale") or "",
    )
    acc["stock"] = account_code(
        db,
        code=getattr(item, "stock_account", ""),
        account_id=getattr(item, "stock_account_id", None),
        fallback=acc.get("stock") or "",
    )
    vat = account_code(
        db,
        code=getattr(item, "vat_account", ""),
        account_id=getattr(item, "vat_account_id", None),
        fallback=acc.get("vat_deductible") or "",
    )
    acc["vat_deductible"] = vat
    acc["vat_collected"] = vat
    return acc
