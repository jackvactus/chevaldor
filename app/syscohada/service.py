"""Services d'import et initialisation SYSCOHADA."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import Account
from app.models_syscohada import AccountClass
from app.models_prefs import SystemSettings
from app.syscohada.chart import SYSCOHADA_CHART
from app.syscohada.constants import ACCOUNT_CLASSES, JOURNALS, DEFAULT_ACCOUNTS, TOGO_VAT_RATES


def seed_account_classes(db: Session) -> int:
    count = 0
    for cls in ACCOUNT_CLASSES:
        existing = db.query(AccountClass).filter(AccountClass.code == cls["code"]).first()
        if existing:
            existing.label = cls["label"]
            existing.kind = cls["kind"]
            existing.description = cls.get("description", "")
        else:
            db.add(AccountClass(
                code=cls["code"],
                label=cls["label"],
                kind=cls["kind"],
                description=cls.get("description", ""),
            ))
            count += 1
    db.commit()
    return count


def import_syscohada_chart(db: Session, *, force: bool = False) -> dict:
    """Importe ou complète le plan SYSCOHADA officiel (1409 comptes, classes 1–9)."""
    full_size = len(SYSCOHADA_CHART)
    existing = db.query(Account).count()
    if existing >= full_size and not force:
        return {
            "ok": True,
            "message": "Plan SYSCOHADA complet déjà en base",
            "existing": existing,
            "total": full_size,
        }

    if force:
        db.query(Account).delete()
        db.flush()

    seed_account_classes(db)
    imported = updated = 0
    for acc in SYSCOHADA_CHART:
        row = db.query(Account).filter(Account.code == acc["code"]).first()
        if row:
            row.label = acc["label"]
            row.type = acc["type"]
            row.class_code = acc["class_code"]
            row.parent_code = acc.get("parent_code", "")
            row.level = acc.get("level", len(acc["code"]))
            updated += 1
        else:
            db.add(Account(
                code=acc["code"],
                label=acc["label"],
                type=acc["type"],
                class_code=acc["class_code"],
                parent_code=acc.get("parent_code", ""),
                level=acc.get("level", len(acc["code"])),
            ))
            imported += 1

    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if row:
        row.accounting_plan = "SYSCOHADA"
        row.journals_json = json.dumps([j["code"] for j in JOURNALS])
        row.taxes_json = json.dumps(TOGO_VAT_RATES)
        row.default_accounts_json = json.dumps(DEFAULT_ACCOUNTS)

    _seed_asset_categories(db)
    from app.services.accounting_engine import seed_tax_rates, seed_stock_categories, seed_credit_note_types
    seed_tax_rates(db)
    seed_stock_categories(db)
    seed_credit_note_types(db)
    db.commit()
    return {
        "ok": True,
        "imported": imported,
        "updated": updated,
        "existing_before": existing,
        "total": full_size,
        "plan": "SYSCOHADA",
    }


def _seed_asset_categories(db: Session) -> None:
    """Catégories d'immobilisations par défaut (SYSCOHADA cl. 2)."""
    from app.models_syscohada import AssetCategory
    defaults = [
        ("MAT-BUREAU", "Matériel de bureau", "244400", "284400", "681300", 36),
        ("MAT-INFO", "Matériel informatique", "244200", "284400", "681300", 36),
        ("MAT-TRANS", "Matériel de transport", "245100", "284500", "681300", 60),
        ("LOGICIEL", "Logiciels", "213000", "281300", "681300", 36),
        ("BATIMENT", "Bâtiments", "231100", "283100", "681300", 240),
    ]
    for code, name, asset, deprec, charge, months in defaults:
        if db.query(AssetCategory).filter(AssetCategory.code == code).first():
            continue
        db.add(AssetCategory(
            code=code,
            name=name,
            account_asset=asset,
            account_depreciation=deprec,
            account_charge=charge,
            duration_months=months,
            method="lineaire",
        ))


def syscohada_config() -> dict:
    return {
        "plan": "SYSCOHADA",
        "version": "révisé",
        "classes": ACCOUNT_CLASSES,
        "journals": JOURNALS,
        "vat_rates": TOGO_VAT_RATES,
        "default_accounts": DEFAULT_ACCOUNTS,
        "chart_size": len(SYSCOHADA_CHART),
        "chart_complete": True,
        "classes": "1-9",
        "perpetual_inventory": True,
        "double_entry": True,
    }
