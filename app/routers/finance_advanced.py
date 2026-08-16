"""Finance avancée — immobilisations, paie, lettrage, rapprochement, liasse OHADA."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.api_guards import require_action
from app.models import User
from app.models_syscohada import FixedAsset, AssetCategory, DepreciationEntry
from app.models_accounting import (
    PayrollRun, SalaryLine, Consignment, ConsignmentMovement,
    Grant, CorporateTaxInstallment, PrepaidExpense,
)
from app.models_erp import Employee
from app.fiscal_service import reopen_fiscal_year, list_closed_fiscal_years
from app.services.fiscal_close_service import close_fiscal_year_full
from app.services.journal_reversal_service import reverse_journal_entry
from app.services.vat_fiscal_service import list_vat_declarations, vat_fiscal_journal
from app.services.auxiliary_account_service import backfill_auxiliary_accounts
from app.services.accounting_reports import balance_auxiliaire_gl, aged_balance_clients, aged_balance_suppliers
from app.services.fixed_asset_service import create_fixed_asset, run_depreciation
from app.services.payroll_service import generate_payroll_run, validate_payroll_run
from app.services.lettering_service import open_lettering_lines, apply_lettering
from app.services.bank_reconcile_service import reconciliation_dashboard, reconcile_movement
from app.services.payroll_pdf_service import payroll_run_pdf, cnss_export_csv
from app.syscohada.reports import bilan_ohada, compte_resultat_ohada, tafire_simplifie, vat_position

router = APIRouter(prefix="/api/erp/finance", tags=["finance-advanced"])


# ——— Immobilisations ———

@router.get("/fixed-assets")
def list_assets(db: Session = Depends(get_db), _: User = Depends(require_action("journal", "view"))):
    assets = db.query(FixedAsset).order_by(FixedAsset.code).all()
    cats = {c.id: c.name for c in db.query(AssetCategory).all()}
    deps = db.query(DepreciationEntry).filter(DepreciationEntry.status == "validée").all()
    dep_by_asset: dict[int, float] = {}
    for d in deps:
        dep_by_asset[d.asset_id] = dep_by_asset.get(d.asset_id, 0) + (d.amount or 0)
    return [
        {
            "id": a.id,
            "code": a.code,
            "label": a.label,
            "category_id": a.category_id,
            "category": cats.get(a.category_id, "—"),
            "acquisition_cost": a.acquisition_cost,
            "residual_value": a.residual_value,
            "accumulated_depreciation": round(dep_by_asset.get(a.id, 0), 2),
            "net_book_value": round((a.acquisition_cost or 0) - dep_by_asset.get(a.id, 0), 2),
            "status": a.status,
            "acquisition_date": str(a.acquisition_date) if a.acquisition_date else "",
            "service_date": str(a.service_date) if a.service_date else "",
            "account_code": a.account_code,
        }
        for a in assets
    ]


@router.get("/fixed-assets/categories")
def asset_categories(db: Session = Depends(get_db), _: User = Depends(require_action("journal", "view"))):
    return db.query(AssetCategory).filter(AssetCategory.is_active == True).all()  # noqa: E712


@router.post("/fixed-assets")
def add_asset(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    if not body.get("code") or not body.get("label"):
        raise HTTPException(400, "Code et libellé requis")
    if db.query(FixedAsset).filter(FixedAsset.code == body["code"]).first():
        raise HTTPException(400, "Code immobilisation déjà utilisé")
    for k in ("acquisition_date", "service_date"):
        if body.get(k) and isinstance(body[k], str):
            body[k] = date.fromisoformat(body[k][:10])
    row = create_fixed_asset(db, body)
    return {"ok": True, "id": row.id, "code": row.code}


@router.post("/depreciation/run")
def depreciation_run(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    asset_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    try:
        return run_depreciation(db, year=year, month=month, asset_id=asset_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


# ——— Paie ———

@router.get("/payroll-runs")
def list_payroll(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    runs = db.query(PayrollRun).order_by(PayrollRun.period_year.desc(), PayrollRun.period_month.desc()).all()
    return [
        {
            "id": r.id,
            "period_year": r.period_year,
            "period_month": r.period_month,
            "status": r.status,
            "total_gross": r.total_gross,
            "total_net": r.total_net,
            "total_charges": r.total_charges,
            "journal_entry_id": r.journal_entry_id,
        }
        for r in runs
    ]


@router.get("/payroll-runs/{run_id}/lines")
def payroll_lines(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "view")),
):
    lines = db.query(SalaryLine).filter(SalaryLine.payroll_run_id == run_id).all()
    emps = {e.id: f"{e.firstname} {e.lastname}".strip() for e in db.query(Employee).all()}
    return [
        {
            "id": ln.id,
            "employee_id": ln.employee_id,
            "employee_name": emps.get(ln.employee_id, f"#{ln.employee_id}"),
            "gross_salary": ln.gross_salary,
            "net_salary": ln.net_salary,
            "employee_charges": ln.employee_charges,
            "employer_charges": ln.employer_charges,
            "withholding_tax": ln.withholding_tax,
        }
        for ln in lines
    ]


@router.post("/payroll-runs/generate")
def payroll_generate(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "create")),
):
    try:
        run = generate_payroll_run(db, year, month)
        return {"ok": True, "id": run.id, "status": run.status, "total_gross": run.total_gross}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/payroll-runs/{run_id}/validate")
def payroll_validate(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "create")),
):
    try:
        return validate_payroll_run(db, run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/payroll-runs/{run_id}/pdf")
def payroll_pdf(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "view")),
):
    try:
        data = payroll_run_pdf(db, run_id)
        return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename=paie-{run_id}.pdf"})
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/payroll-runs/{run_id}/cnss-export")
def payroll_cnss(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("hr", "view")),
):
    try:
        csv_data = cnss_export_csv(db, run_id)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=cnss-{run_id}.csv"},
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# ——— Lettrage ———

@router.get("/lettering/open")
def lettering_open(
    prefix: str = Query("411"),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return open_lettering_lines(db, prefix)


@router.post("/lettering/match")
def lettering_match(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    try:
        return apply_lettering(db, body.get("line_ids") or [], body.get("letter_code") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/lettering/unmatch")
def lettering_unmatch(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    from app.services.lettering_service import remove_lettering
    try:
        return remove_lettering(db, body.get("letter_code") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


# ——— Rapprochement ———

@router.get("/reconciliation")
def reconciliation(db: Session = Depends(get_db), _: User = Depends(require_action("treasury", "view"))):
    return reconciliation_dashboard(db)


@router.post("/reconciliation/{movement_id}")
def reconciliation_toggle(
    movement_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "update")),
):
    try:
        return reconcile_movement(db, movement_id, reconciled=bool(body.get("reconciled", True)))
    except ValueError as e:
        raise HTTPException(404, str(e))


# ——— Consignes & subventions ———

@router.get("/consignments")
def list_consignments(db: Session = Depends(get_db), _: User = Depends(require_action("journal", "view"))):
    return db.query(Consignment).order_by(Consignment.code).all()


@router.post("/consignments")
def create_consignment(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    row = Consignment(
        code=body.get("code") or f"CONS-{db.query(Consignment).count() + 1}",
        label=body.get("label") or "Consigne",
        unit_value=float(body.get("unit_value") or 0),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/consignments/{cid}/movement")
def consignment_move(
    cid: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    row = db.query(Consignment).filter(Consignment.id == cid).first()
    if not row:
        raise HTTPException(404)
    direction = body.get("direction") or "out"
    qty = float(body.get("quantity") or 0)
    if direction == "out":
        row.qty_out = (row.qty_out or 0) + qty
    else:
        row.qty_returned = (row.qty_returned or 0) + qty
    mv = ConsignmentMovement(
        consignment_id=cid,
        date=date.today(),
        direction=direction,
        quantity=qty,
        partner_type=body.get("partner_type") or "client",
        partner_id=body.get("partner_id"),
        notes=body.get("notes") or "",
    )
    db.add(mv)
    db.commit()
    return {"ok": True, "balance": (row.qty_out or 0) - (row.qty_returned or 0)}


@router.get("/grants")
def list_grants(db: Session = Depends(get_db), _: User = Depends(require_action("journal", "view"))):
    return db.query(Grant).order_by(Grant.code).all()


@router.post("/grants")
def create_grant(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    row = Grant(
        code=body.get("code") or f"SUB-{db.query(Grant).count() + 1}",
        label=body.get("label") or "Subvention",
        grant_type=body.get("grant_type") or "exploitation",
        amount=float(body.get("amount") or 0),
        received=float(body.get("received") or 0),
        status=body.get("status") or "active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/corporate-tax")
def list_corporate_tax(db: Session = Depends(get_db), _: User = Depends(require_action("journal", "view"))):
    return db.query(CorporateTaxInstallment).order_by(CorporateTaxInstallment.fiscal_year.desc()).all()


@router.post("/corporate-tax")
def create_corporate_tax(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    row = CorporateTaxInstallment(
        fiscal_year=int(body.get("fiscal_year") or date.today().year),
        period=int(body.get("period") or 1),
        amount=float(body.get("amount") or 0),
        status=body.get("status") or "planned",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/prepaid-expenses")
def list_prepaid(db: Session = Depends(get_db), _: User = Depends(require_action("journal", "view"))):
    return db.query(PrepaidExpense).order_by(PrepaidExpense.id.desc()).all()


# ——— Clôture exercice ———

@router.get("/fiscal-years")
def fiscal_years(db: Session = Depends(get_db), _: User = Depends(require_action("journal", "view"))):
    closed = list_closed_fiscal_years(db)
    current = date.today().year
    years = list(range(current - 3, current + 2))
    return {
        "closed": closed,
        "years": [{"year": y, "closed": y in closed} for y in years],
    }


@router.post("/fiscal-years/{year}/close")
def fiscal_close(
    year: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "approve")),
):
    try:
        return close_fiscal_year_full(db, year)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/journal-entries/{entry_id}/reverse")
def reverse_entry(
    entry_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "approve")),
):
    try:
        return reverse_journal_entry(db, entry_id, label=body.get("label") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/vat/declarations")
def vat_declarations_history(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return list_vat_declarations(db)


@router.get("/vat/journal")
def vat_fiscal_journal_route(
    year: int = Query(...),
    period: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return vat_fiscal_journal(db, fiscal_year=year, period=period)


@router.post("/auxiliary/backfill")
def auxiliary_backfill(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    return backfill_auxiliary_accounts(db)


@router.get("/auxiliary/clients")
def auxiliary_clients_gl(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return balance_auxiliaire_gl(db, "411")


@router.get("/auxiliary/suppliers")
def auxiliary_suppliers_gl(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return balance_auxiliaire_gl(db, "401")


@router.get("/reports/aged-balance/clients")
def report_aged_clients(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return aged_balance_clients(db)


@router.get("/reports/aged-balance/suppliers")
def report_aged_suppliers(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    return aged_balance_suppliers(db)


@router.post("/fiscal-years/{year}/reopen")
def fiscal_reopen(
    year: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "approve")),
):
    closed = reopen_fiscal_year(db, year)
    db.commit()
    return {"ok": True, "closed": closed}


# ——— Liasse OHADA ———

@router.get("/reports/liasse")
def liasse_ohada(
    year: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    bilan = bilan_ohada(db, year)
    resultat = compte_resultat_ohada(db, year)
    tafire = tafire_simplifie(db, year)
    vat = vat_position(db, year)
    return {
        "fiscal_year": year,
        "generated_at": date.today().isoformat(),
        "bilan": bilan,
        "compte_resultat": resultat,
        "tafire": tafire,
        "vat_position": vat,
        "notes": [
            "États conformes SYSCOHADA révisé — niveau PME",
            "Vérifier les comptes de classe 1 à 8 avant dépôt légal",
            "Annexes détaillées : immobilisations, stocks, créances âgées",
        ],
    }


@router.get("/reports/liasse.pdf")
def liasse_ohada_pdf(
    year: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    from app.services.pdf_reports import liasse_ohada_pdf as build_liasse_pdf
    data = build_liasse_pdf(db, year)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=liasse-{year}.pdf"},
    )
