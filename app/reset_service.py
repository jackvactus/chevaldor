"""Remise à zéro application — métier ou complète (utilisateurs toujours conservés)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List, Type

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bootstrap import ensure_company_profile, ensure_platform_defaults
from app.models import (
    Activity,
    Attachment,
    Client,
    ClientLedgerEntry,
    CompanyProfile,
    Deal,
    DocumentLine,
    ImportBatch,
    Invoice,
    Project,
    Quote,
    StockItem,
    StockMovement,
    Task,
    Trainee,
    Training,
    Transaction,
    Account,
)
from app.models_calendar import CalendarEvent
from app.models_cms import CmsBanner, CmsDynamicSection, CmsMedia, CmsPage, CmsPageVersion, CmsSiteSettings
from app.models_enterprise import (
    ApprovalRequest,
    ApprovalStep,
    ChatMessage,
    DocumentSignature,
    NotificationOutbox,
    OcrExtraction,
    PendingLogin2FA,
    ScheduledReport,
    UserSession,
)
from app.models_erp import (
    AuditLog,
    BankAccount,
    Budget,
    CostCenter,
    Employee,
    JournalEntry,
    JournalLine,
    LeaveRequest,
    Supplier,
    SupplierInvoice,
    TreasuryMovement,
    UserDashboard,
)
from app.models_prefs import AppNotification, EmailLog, LoginLog
from app.models_accounting import (
    AccountingTransaction,
    Consignment,
    ConsignmentMovement,
    CorporateTaxInstallment,
    Grant,
    PaymentRecord,
    PayrollRun,
    PrepaidExpense,
    SalaryLine,
    SupplierInvoiceLine,
    TaxReport,
    VatDeclaration,
    VatPeriod,
)
from app.models_syscohada import AssetDisposal, DepreciationEntry, FixedAsset
from app.models_stock import StockInventory, Warehouse
from app.region_config import REGION
from app.services.cms_service import CMS_MEDIA_ROOT, default_site_settings, ensure_cms_seeded, _now


# Données métier effacées — jamais les comptes utilisateurs ni leurs préférences / mots de passe.
_BUSINESS_MODELS: List[Type] = [
    AuditLog, DocumentLine, Activity, JournalLine, TreasuryMovement,
    LeaveRequest, Task, StockMovement, StockInventory, Trainee,
    ClientLedgerEntry, Attachment, SupplierInvoiceLine, SupplierInvoice,
    CalendarEvent, JournalEntry, Budget, Employee, CostCenter, UserDashboard,
    Invoice, Quote, Deal, Transaction, Project, Training,
    StockItem, BankAccount, Supplier, Account, Client,
    Warehouse, ImportBatch,
    AccountingTransaction, VatDeclaration, VatPeriod, PaymentRecord, PrepaidExpense,
    Consignment, ConsignmentMovement, CorporateTaxInstallment, PayrollRun,
    SalaryLine, Grant, TaxReport, FixedAsset, DepreciationEntry, AssetDisposal,
]

_ENTERPRISE_CLEAR: List[Type] = [
    ApprovalStep, ApprovalRequest, DocumentSignature, OcrExtraction,
    ChatMessage, NotificationOutbox, ScheduledReport,
    PendingLogin2FA, UserSession,
]

_PREFS_CLEAR: List[Type] = [
    AppNotification, EmailLog, LoginLog,
]


def _delete_all(db: Session, models: List[Type]) -> int:
    total = 0
    for model in models:
        n = db.query(model).delete(synchronize_session=False)
        total += n or 0
    return total


def reset_business_data(db: Session) -> dict:
    """Supprime les données métier. Conserve : utilisateurs, rôles, préférences, config système."""
    db.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        deleted = _delete_all(db, _BUSINESS_MODELS)
        db.flush()
    finally:
        db.execute(text("PRAGMA foreign_keys=ON"))
    return {
        "scope": "business",
        "rows_deleted": deleted,
        "users_preserved": True,
        "message": "Données métier réinitialisées — tous les comptes utilisateurs sont conservés.",
    }


def _clear_upload_dirs() -> List[str]:
    from app.paths import uploads_root

    cleared = []
    for root in (uploads_root(), CMS_MEDIA_ROOT):
        if root.exists():
            for child in root.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
            cleared.append(str(root))
    return cleared


def _reset_company_profile(db: Session) -> None:
    prof = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not prof:
        ensure_company_profile(db)
        return
    prof.name = REGION["company_name"]
    prof.legal_form = REGION["legal_form"]
    prof.tagline = REGION["tagline"]
    prof.description = REGION["description"]
    prof.address = REGION["address_default"]
    prof.email = "contact@peyacompany.com"
    prof.phone = ""
    prof.logo_path = "/static/logo-peya.png"
    prof.currency = REGION["currency_label"]


def _reset_cms_defaults(db: Session) -> None:
    for model in (CmsPageVersion, CmsBanner, CmsDynamicSection, CmsMedia, CmsPage, CmsSiteSettings):
        db.query(model).delete(synchronize_session=False)
    db.flush()
    ensure_cms_seeded(db)
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    if row:
        row.settings_json = json.dumps(default_site_settings(), ensure_ascii=False)
        row.draft_json = json.dumps(default_site_settings(), ensure_ascii=False)
        row.updated_at = _now()


def reset_application_full(db: Session) -> dict:
    """
    Remise à zéro étendue : métier, CMS, notifications, sessions, fichiers uploadés.
    Conserve : TOUS les utilisateurs, préférences, historique MDP, groupes, config système.
    """
    cms = [CmsPageVersion, CmsBanner, CmsDynamicSection, CmsMedia, CmsPage]

    db.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        deleted = _delete_all(db, _ENTERPRISE_CLEAR + _PREFS_CLEAR + _BUSINESS_MODELS + cms)
        db.query(CmsSiteSettings).delete(synchronize_session=False)
        db.flush()
    finally:
        db.execute(text("PRAGMA foreign_keys=ON"))

    cleared_dirs = _clear_upload_dirs()
    _reset_company_profile(db)
    ensure_platform_defaults(db)
    _reset_cms_defaults(db)
    from app.bootstrap import ensure_syscohada_chart
    ensure_syscohada_chart(db)

    return {
        "scope": "full",
        "rows_deleted": deleted,
        "cleared_dirs": cleared_dirs,
        "users_preserved": True,
        "message": "Application remise à zéro — tous les utilisateurs et leurs accès sont conservés.",
    }
