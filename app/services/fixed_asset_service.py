"""Immobilisations SYSCOHADA — amortissements linéaires."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models_syscohada import FixedAsset, AssetCategory, DepreciationEntry
from app.models_erp import JournalEntry, JournalLine
from app.fiscal_service import assert_fiscal_year_open
from app.services.accounting_reports import validate_entry_balance


def create_fixed_asset(db: Session, data: dict) -> FixedAsset:
    cat = None
    if data.get("category_id"):
        cat = db.query(AssetCategory).filter(AssetCategory.id == data["category_id"]).first()
    row = FixedAsset(
        code=data["code"],
        label=data["label"],
        category_id=data.get("category_id"),
        acquisition_date=data.get("acquisition_date"),
        service_date=data.get("service_date") or data.get("acquisition_date"),
        acquisition_cost=float(data.get("acquisition_cost") or 0),
        residual_value=float(data.get("residual_value") or 0),
        account_code=data.get("account_code") or (cat.account_asset if cat else "244200"),
        status=data.get("status") or "en_service",
        notes=data.get("notes") or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def monthly_depreciation_amount(asset: FixedAsset, category: AssetCategory | None) -> float:
    months = (category.duration_months if category else 36) or 36
    base = float(asset.acquisition_cost or 0) - float(asset.residual_value or 0)
    if base <= 0 or months <= 0:
        return 0.0
    return round(base / months, 2)


def run_depreciation(
    db: Session,
    *,
    year: int,
    month: int,
    asset_id: int | None = None,
) -> dict:
    """Génère les dotations d'amortissement (compte 681 → 284)."""
    assert_fiscal_year_open(db, year)
    q = db.query(FixedAsset).filter(FixedAsset.status == "en_service")
    if asset_id:
        q = q.filter(FixedAsset.id == asset_id)
    assets = q.all()
    cats = {c.id: c for c in db.query(AssetCategory).all()}
    created = 0
    total = 0.0
    period_date = date(year, month, 28)

    for asset in assets:
        existing = db.query(DepreciationEntry).filter(
            DepreciationEntry.asset_id == asset.id,
            DepreciationEntry.fiscal_year == year,
            DepreciationEntry.period == month,
        ).first()
        if existing and existing.status == "validée":
            continue

        cat = cats.get(asset.category_id)
        amount = monthly_depreciation_amount(asset, cat)
        if amount <= 0:
            continue

        charge_acc = (cat.account_charge if cat else "681300") or "681300"
        deprec_acc = (cat.account_depreciation if cat else "284400") or "284400"
        lines = [
            {"account_code": charge_acc, "debit": amount, "credit": 0, "label": f"Amort. {asset.code}"},
            {"account_code": deprec_acc, "debit": 0, "credit": amount, "label": f"Amort. {asset.code}"},
        ]
        if not validate_entry_balance(lines):
            continue

        entry = JournalEntry(
            date=period_date,
            journal="OD",
            reference=f"AMORT-{asset.code}-{year}{month:02d}",
            label=f"Amortissement {asset.label}",
            status="validée",
            fiscal_year=year,
            period=month,
            source_type="depreciation",
            source_id=asset.id,
        )
        db.add(entry)
        db.flush()
        for ln in lines:
            db.add(JournalLine(
                entry_id=entry.id,
                account_code=ln["account_code"],
                debit=ln["debit"],
                credit=ln["credit"],
                label=ln["label"],
            ))

        if existing:
            existing.amount = amount
            existing.journal_entry_id = entry.id
            existing.status = "validée"
        else:
            db.add(DepreciationEntry(
                asset_id=asset.id,
                period_date=period_date,
                fiscal_year=year,
                period=month,
                amount=amount,
                journal_entry_id=entry.id,
                status="validée",
            ))
        created += 1
        total += amount

    db.commit()
    return {"ok": True, "entries": created, "total_amount": round(total, 2), "year": year, "month": month}
