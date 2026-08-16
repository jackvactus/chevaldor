"""Cession d'immobilisations — écriture SYSCOHADA."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.fiscal_service import assert_fiscal_year_open
from app.models_syscohada import FixedAsset, AssetCategory, DepreciationEntry, AssetDisposal
from app.models_erp import JournalEntry, JournalLine
from app.services.accounting_reports import validate_entry_balance


def _accumulated_depreciation(db: Session, asset_id: int) -> float:
  total = 0.0
  for d in db.query(DepreciationEntry).filter(
      DepreciationEntry.asset_id == asset_id,
      DepreciationEntry.status == "validée",
  ):
      total += float(d.amount or 0)
  return round(total, 2)


def dispose_fixed_asset(
    db: Session,
    asset_id: int,
    *,
    disposal_date: date | None = None,
    proceeds: float = 0,
    notes: str = "",
) -> AssetDisposal:
    asset = db.query(FixedAsset).filter(FixedAsset.id == asset_id).first()
    if not asset:
        raise ValueError("Immobilisation introuvable")
    if asset.status == "cede":
        raise ValueError("Immobilisation déjà cédée")

    d_date = disposal_date or date.today()
    assert_fiscal_year_open(db, d_date.year)

    accum = _accumulated_depreciation(db, asset.id)
    gross = float(asset.acquisition_cost or 0)
    book_value = round(gross - accum, 2)
    gain_loss = round(float(proceeds or 0) - book_value, 2)

    cat = db.query(AssetCategory).filter(AssetCategory.id == asset.category_id).first()
    asset_acc = asset.account_code or (cat.account_asset if cat else "244200")
    deprec_acc = (cat.account_depreciation if cat else "284400") or "284400"
    gain_acc = "775000"
    loss_acc = "675000"
    bank_acc = "521100"

    lines: list[dict] = []
    if proceeds and abs(proceeds) >= 0.01:
        lines.append({"account_code": bank_acc, "debit": proceeds, "credit": 0, "label": f"Cession {asset.code}"})
    if accum >= 0.01:
        lines.append({"account_code": deprec_acc, "debit": accum, "credit": 0, "label": "Amort. cumulé"})
    if gross >= 0.01:
        lines.append({"account_code": asset_acc, "debit": 0, "credit": gross, "label": asset.label or asset.code})
    if gain_loss >= 0.01:
        lines.append({"account_code": gain_acc, "debit": 0, "credit": gain_loss, "label": "Plus-value cession"})
    elif gain_loss <= -0.01:
        lines.append({"account_code": loss_acc, "debit": abs(gain_loss), "credit": 0, "label": "Moins-value cession"})

    validate_entry_balance(lines)

    entry = JournalEntry(
        date=d_date,
        journal="OD",
        reference=f"CESS-{asset.code}",
        label=f"Cession immobilisation {asset.code}",
        status="validée",
        fiscal_year=d_date.year,
        source_type="asset_disposal",
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
            label=ln.get("label") or "",
        ))

    disposal = AssetDisposal(
        asset_id=asset.id,
        date=d_date,
        proceeds=float(proceeds or 0),
        book_value=book_value,
        gain_loss=gain_loss,
        journal_entry_id=entry.id,
        notes=notes or "",
    )
    db.add(disposal)
    asset.status = "cede"
    asset.disposal_date = d_date
    asset.disposal_amount = float(proceeds or 0)
    db.commit()
    db.refresh(disposal)
    return disposal
