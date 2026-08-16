"""API SYSCOHADA — référentiel, import plan, écritures auto, états OHADA."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.api_guards import require_action
from app.models import User, Invoice, Account
from app.models_syscohada import AccountClass, FixedAsset, AssetCategory
from app.syscohada.service import import_syscohada_chart, syscohada_config, seed_account_classes
from app.syscohada.chart import SYSCOHADA_CHART, chart_by_class
from app.syscohada.posting import (
    post_invoice,
    post_supplier_invoice,
    build_sale_entry,
    build_purchase_entry,
    build_vat_regularization,
    persist_entry,
)
from app.syscohada.reports import bilan_ohada, compte_resultat_ohada, tafire_simplifie, vat_position
from app.services.chart_plan_service import (
    chart_overview, search_accounts, build_class_tree, account_detail, export_chart_csv,
)
from app.models import DocumentLine
from app.models_erp import SupplierInvoice

router = APIRouter(prefix="/api/erp/syscohada", tags=["syscohada"])


@router.get("/config")
def get_config(_: User = Depends(require_action("journal", "view"))):
    return syscohada_config()


@router.get("/compliance-audit")
def compliance_audit(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    from app.services.syscohada_audit import run_compliance_audit
    return run_compliance_audit(db)


@router.get("/classes")
def list_classes(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    rows = db.query(AccountClass).order_by(AccountClass.code).all()
    if not rows:
        seed_account_classes(db)
        rows = db.query(AccountClass).order_by(AccountClass.code).all()
    return [{"code": r.code, "label": r.label, "kind": r.kind, "description": r.description} for r in rows]


@router.get("/chart")
def get_chart(
    class_code: Optional[str] = Query(None),
    _: User = Depends(require_action("journal", "view")),
):
    if class_code:
        return [a for a in SYSCOHADA_CHART if a["class_code"] == class_code]
    return {"by_class": chart_by_class(), "accounts": SYSCOHADA_CHART}


@router.post("/import-chart")
def import_chart(
    force: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    return import_syscohada_chart(db, force=force)


@router.get("/accounts/tree")
def accounts_tree(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    """Arbre du plan comptable en base."""
    accounts = db.query(Account).order_by(Account.code).all()
    return [
        {
            "id": a.id,
            "code": a.code,
            "label": a.label,
            "type": a.type,
            "class_code": getattr(a, "class_code", "") or (a.code[0] if a.code else ""),
            "parent_code": getattr(a, "parent_code", ""),
            "level": getattr(a, "level", len(a.code or "")),
        }
        for a in accounts
    ]


@router.get("/chart/overview")
def chart_plan_overview(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return chart_overview(db, fiscal_year=fiscal_year)


@router.get("/chart/search")
def chart_plan_search(
    q: str = Query("", max_length=80),
    class_code: Optional[str] = None,
    account_type: Optional[str] = None,
    used_only: bool = False,
    with_balance: bool = False,
    fiscal_year: Optional[int] = None,
    limit: int = Query(80, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return search_accounts(
        db, q=q, class_code=class_code, account_type=account_type,
        used_only=used_only, with_balance=with_balance,
        fiscal_year=fiscal_year, limit=limit, offset=offset,
    )


@router.get("/chart/tree/{class_code}")
def chart_plan_tree(
    class_code: str,
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    if class_code not in "123456789":
        raise HTTPException(400, "Classe invalide (1-9)")
    return build_class_tree(db, class_code, fiscal_year=fiscal_year)


@router.get("/accounts/{code}/detail")
def chart_account_detail(
    code: str,
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    try:
        return account_detail(db, code, fiscal_year=fiscal_year)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/chart/export.csv")
def chart_plan_export_csv(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    data = export_chart_csv(db)
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=plan-syscohada.csv"},
    )


@router.get("/reports/bilan")
def report_bilan(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return bilan_ohada(db, fiscal_year=fiscal_year)


@router.get("/reports/resultat")
def report_resultat(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return compte_resultat_ohada(db, fiscal_year=fiscal_year)


@router.get("/reports/flux-tresorerie")
def report_tafire(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return tafire_simplifie(db, fiscal_year=fiscal_year)


@router.get("/reports/tva")
def report_tva(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return vat_position(db, fiscal_year=fiscal_year)


@router.get("/posting/preview/invoice/{invoice_id}")
def preview_invoice_posting(
    invoice_id: int,
    with_stock: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Facture introuvable")
    lines = db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice_id).all()
    from app.syscohada.posting import _settings
    from app.services.accounting_engine import build_invoice_lines
    cfg = _settings(db)
    return {
        "journal": "VE",
        "lines": build_invoice_lines(db, invoice, lines, cfg),
    }


@router.post("/posting/invoice/{invoice_id}")
def posting_invoice(
    invoice_id: int,
    with_stock: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    try:
        entry = post_invoice(db, invoice_id, with_stock=with_stock)
        return {"ok": True, "entry_id": entry.id, "journal": entry.journal}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/posting/supplier-invoice/{supplier_invoice_id}")
def posting_supplier_invoice_route(
    supplier_invoice_id: int,
    vat_rate: float = Query(18.0),
    with_stock: bool = Query(True),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    try:
        entry = post_supplier_invoice(db, supplier_invoice_id, vat_rate=vat_rate, with_stock=with_stock)
        return {"ok": True, "entry_id": entry.id, "journal": entry.journal}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/posting/vat-regularization")
def preview_vat_regularization(_: User = Depends(require_action("journal", "view"))):
    return build_vat_regularization()


@router.post("/vat/close-period")
def close_vat_period_route(
    year: int = Query(...),
    period: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "validate")),
):
    try:
        from app.services.accounting_engine import close_vat_period
        return close_vat_period(db, year, period)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/product-types")
def list_product_types(_: User = Depends(require_action("journal", "view"))):
    from app.syscohada.product_types import PRODUCT_ACCOUNTING_TYPES, TYPE_ACCOUNTS, CREDIT_NOTE_TYPES
    return {
        "types": PRODUCT_ACCOUNTING_TYPES,
        "accounts": TYPE_ACCOUNTS,
        "credit_note_types": CREDIT_NOTE_TYPES,
    }


@router.get("/stock-categories")
def list_stock_categories(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    from app.models_accounting import StockCategory
    return db.query(StockCategory).filter(StockCategory.is_active == True).all()  # noqa: E712


@router.get("/accounting-transactions")
def list_accounting_transactions(
    db: Session = Depends(get_db),
    source_type: Optional[str] = None,
    _: User = Depends(require_action("journal", "view")),
):
    from app.models_accounting import AccountingTransaction
    q = db.query(AccountingTransaction).order_by(AccountingTransaction.id.desc())
    if source_type:
        q = q.filter(AccountingTransaction.source_type == source_type)
    return q.limit(200).all()


@router.get("/prepaid-expenses")
def list_prepaid_expenses(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    from app.models_accounting import PrepaidExpense
    return db.query(PrepaidExpense).order_by(PrepaidExpense.id.desc()).all()


@router.post("/prepaid-expenses")
def create_prepaid(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    from app.services.accounting_engine import create_prepaid_expense
    try:
        return create_prepaid_expense(db, body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/prepaid-expenses/{pid}/amortize")
def amortize_prepaid(
    pid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    from app.models_accounting import PrepaidExpense
    from app.services.accounting_engine import amortize_prepaid_expense
    row = db.query(PrepaidExpense).filter(PrepaidExpense.id == pid).first()
    if not row:
        raise HTTPException(404)
    try:
        return amortize_prepaid_expense(db, row)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/fixed-assets")
def list_fixed_assets(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    assets = db.query(FixedAsset).order_by(FixedAsset.code).all()
    cats = {c.id: c.name for c in db.query(AssetCategory).all()}
    return [
        {
            "id": a.id,
            "code": a.code,
            "label": a.label,
            "category": cats.get(a.category_id, "—"),
            "acquisition_cost": a.acquisition_cost,
            "status": a.status,
            "service_date": str(a.service_date) if a.service_date else "",
        }
        for a in assets
    ]


@router.get("/fixed-assets/categories")
def list_asset_categories(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return db.query(AssetCategory).filter(AssetCategory.is_active == True).all()  # noqa: E712
