"""Paramètres, graphiques, recherche, sauvegarde, 20+ utilitaires."""
import json
import shutil
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, Form
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from app.database import get_db, DB_PATH
from app.auth import get_current_user, require_permission, hash_password
from app.api_guards import require_action
from app.models import User, Client, Invoice, Quote, Deal, StockItem, Transaction, Project
from app.models_prefs import (
    UserPreferences,
    AppNotification,
    SystemSettings,
    SmtpSettings,
    EmailTemplate,
    EmailLog,
    NotificationPreference,
)
from app.models_erp import Supplier, SupplierInvoice
from pydantic import BaseModel
from app.services.smtp_service import get_smtp_settings, send_email_via_smtp
from app.services.notify import create_app_notification

router = APIRouter(prefix="/api", tags=["settings-extra"])


class SettingsIn(BaseModel):
    theme: Optional[str] = None
    theme_mode: Optional[str] = None
    color_palette: Optional[str] = None
    custom_theme: Optional[dict] = None
    font_scale: Optional[float] = None
    display_currency_code: Optional[str] = None
    fiscal_year: Optional[int] = None
    language: Optional[str] = None
    auto_refresh: Optional[bool] = None
    widgets: Optional[List[str]] = None


class AppearanceIn(BaseModel):
    appearance: Optional[dict] = None
    documents: Optional[dict] = None
    storage: Optional[dict] = None
    integrations: Optional[dict] = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class BackupRestoreIn(BaseModel):
    admin_password: str
    confirm_text: str = ""


def _verify_restore_credentials(user: User, admin_password: str, confirm_text: str) -> None:
    from app.auth import verify_password

    if (confirm_text or "").strip().upper() != "RESTAURER":
        raise HTTPException(400, "Tapez RESTAURER pour confirmer l'opération")
    if not admin_password:
        raise HTTPException(400, "Mot de passe administrateur requis")
    if not verify_password(admin_password, user.password_hash):
        raise HTTPException(403, "Mot de passe administrateur incorrect")


class PaymentIn(BaseModel):
    amount: float
    date: Optional[date] = None
    method: str = "virement"
    notes: str = ""


class SystemSettingsIn(BaseModel):
    company_name: Optional[str] = None
    company_logo: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    accounting_year: Optional[int] = None
    accounting_plan: Optional[str] = None
    journals: Optional[list[str]] = None
    taxes: Optional[list[dict]] = None
    default_accounts: Optional[dict] = None
    password_policy: Optional[dict] = None
    two_factor_enabled: Optional[bool] = None
    session_timeout_min: Optional[int] = None
    backup_enabled: Optional[bool] = None
    backup_frequency: Optional[str] = None
    backup_retention_days: Optional[int] = None
    archive_enabled: Optional[bool] = None


class SmtpSettingsIn(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    use_tls: Optional[bool] = None
    use_ssl: Optional[bool] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    provider: Optional[str] = None
    enabled: Optional[bool] = None


class SmtpTestIn(BaseModel):
    to_email: str
    subject: str = "Test SMTP Peya ERP"
    body: str = "<p>Votre configuration SMTP fonctionne.</p>"


class EmailTemplateIn(BaseModel):
    code: str
    subject: str
    body: str
    is_active: bool = True


class NotificationPrefsIn(BaseModel):
    email_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None
    categories: Optional[list[str]] = None


def _prefs(db: Session, user_id: int) -> UserPreferences:
    p = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if not p:
        p = UserPreferences(user_id=user_id)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _system_settings(db: Session) -> SystemSettings:
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if not row:
        row = SystemSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _notification_prefs(db: Session, user_id: int) -> NotificationPreference:
    row = db.query(NotificationPreference).filter(NotificationPreference.user_id == user_id).first()
    if not row:
        row = NotificationPreference(user_id=user_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _parse_json(text: str, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(text or "") or default
    except json.JSONDecodeError:
        return default


@router.get("/settings/me")
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _prefs(db, user.id)
    mode = getattr(p, "theme_mode", None) or p.theme or "light"
    return {
        "theme": p.theme,
        "theme_mode": mode,
        "color_palette": getattr(p, "color_palette", None) or "peya",
        "custom_theme": _parse_json(getattr(p, "custom_theme_json", None) or "{}"),
        "font_scale": float(getattr(p, "font_scale", None) or 1.0),
        "display_currency_code": getattr(p, "display_currency_code", None) or "XOF",
        "fiscal_year": p.fiscal_year,
        "language": p.language,
        "auto_refresh": p.auto_refresh,
        "widgets": json.loads(p.widgets_json or "[]"),
        "email": user.email,
        "full_name": user.full_name,
    }


@router.put("/settings/me")
def update_settings(body: SettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _prefs(db, user.id)
    if body.theme_mode is not None:
        mode = body.theme_mode if body.theme_mode in ("dark", "light", "auto") else "light"
        p.theme_mode = mode
        p.theme = "light" if mode == "light" else "dark"
    if body.theme is not None and body.theme_mode is None:
        p.theme = body.theme if body.theme in ("dark", "light") else "light"
        p.theme_mode = p.theme
    if body.color_palette is not None:
        p.color_palette = (body.color_palette or "peya")[:40]
    if body.custom_theme is not None:
        p.custom_theme_json = json.dumps(body.custom_theme or {})
    if body.font_scale is not None:
        scale = max(0.8, min(1.35, float(body.font_scale)))
        p.font_scale = str(round(scale, 2))
    if body.display_currency_code is not None:
        code = body.display_currency_code.strip().upper()
        if len(code) >= 3:
            p.display_currency_code = code
    if body.fiscal_year is not None:
        p.fiscal_year = body.fiscal_year
    if body.language is not None:
        p.language = body.language
    if body.auto_refresh is not None:
        p.auto_refresh = body.auto_refresh
    if body.widgets is not None:
        p.widgets_json = json.dumps(body.widgets)
    db.commit()
    return get_settings(db, user)


@router.post("/settings/change-password")
def change_password(body: PasswordChangeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.auth import verify_password
    from app.services.password_service import set_user_password, user_security_flags

    flags = user_security_flags(user, db)
    if flags["requires_password_change"]:
        raise HTTPException(
            400,
            "Utilisez l'écran de changement obligatoire après connexion (mot de passe temporaire ou expiré).",
        )
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Mot de passe actuel incorrect")
    set_user_password(db, user, body.new_password, must_change=False)
    return {"ok": True}


@router.get("/settings/system")
def get_system_settings(_: User = Depends(require_permission("users.manage")), db: Session = Depends(get_db)):
    s = _system_settings(db)
    return {
        "company_name": s.company_name,
        "company_logo": s.company_logo,
        "address": s.address,
        "phone": s.phone,
        "email": s.email,
        "website": s.website,
        "currency": s.currency,
        "timezone": s.timezone,
        "language": s.language,
        "accounting_year": s.accounting_year,
        "accounting_plan": s.accounting_plan,
        "journals": json.loads(s.journals_json or "[]"),
        "taxes": json.loads(s.taxes_json or "[]"),
        "default_accounts": json.loads(s.default_accounts_json or "{}"),
        "password_policy": json.loads(s.password_policy_json or "{}"),
        "two_factor_enabled": s.two_factor_enabled,
        "session_timeout_min": s.session_timeout_min,
        "backup_enabled": s.backup_enabled,
        "backup_frequency": s.backup_frequency,
        "backup_retention_days": s.backup_retention_days,
        "backup_last_run": s.backup_last_run,
        "archive_enabled": s.archive_enabled,
        "appearance": _parse_json(getattr(s, "appearance_json", None) or "{}"),
        "documents": _parse_json(getattr(s, "documents_json", None) or "{}"),
        "storage": _parse_json(getattr(s, "storage_json", None) or "{}"),
        "integrations": _parse_json(getattr(s, "integrations_json", None) or "{}"),
    }


@router.get("/settings/extended")
def get_extended_settings(
    _: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    s = _system_settings(db)
    from app.services.database_backup_service import list_backups
    backups = list_backups(30)
    db_size = round(DB_PATH.stat().st_size / (1024 * 1024), 2) if DB_PATH.exists() else 0
    return {
        "backups": backups,
        "db_size_mb": db_size,
        "backup_last_run": s.backup_last_run,
        "backup_enabled": s.backup_enabled,
    }


@router.put("/settings/extended")
def update_extended_settings(
    body: AppearanceIn,
    _: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    s = _system_settings(db)
    if body.appearance is not None:
        s.appearance_json = json.dumps(body.appearance)
    if body.documents is not None:
        s.documents_json = json.dumps(body.documents)
    if body.storage is not None:
        s.storage_json = json.dumps(body.storage)
    if body.integrations is not None:
        s.integrations_json = json.dumps(body.integrations)
    db.commit()
    return get_extended_settings(_, db)


@router.put("/settings/system")
def update_system_settings(
    body: SystemSettingsIn,
    _: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    s = _system_settings(db)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "journals":
            s.journals_json = json.dumps(value or [])
        elif key == "taxes":
            s.taxes_json = json.dumps(value or [])
        elif key == "default_accounts":
            s.default_accounts_json = json.dumps(value or {})
        elif key == "password_policy":
            s.password_policy_json = json.dumps(value or {})
        else:
            setattr(s, key, value)
    db.commit()
    return get_system_settings(_, db)


@router.get("/settings/smtp")
def get_smtp_settings_api(_: User = Depends(require_permission("users.manage")), db: Session = Depends(get_db)):
    s = get_smtp_settings(db)
    return {
        "host": s.host,
        "port": s.port,
        "username": s.username,
        "password": "***" if s.password else "",
        "use_tls": s.use_tls,
        "use_ssl": s.use_ssl,
        "sender_email": s.sender_email,
        "sender_name": s.sender_name,
        "provider": s.provider,
        "enabled": s.enabled,
    }


@router.put("/settings/smtp")
def update_smtp_settings(
    body: SmtpSettingsIn,
    _: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    s = get_smtp_settings(db)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "password" and value == "***":
            continue
        setattr(s, key, value)
    db.commit()
    return get_smtp_settings_api(_, db)


@router.post("/settings/smtp/test")
def test_smtp(
    body: SmtpTestIn,
    _: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    result = send_email_via_smtp(db, to_email=body.to_email, subject=body.subject, body=body.body)
    if not result["ok"]:
        raise HTTPException(400, result["message"])
    return result


@router.get("/settings/email-templates")
def list_email_templates(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(EmailTemplate).order_by(EmailTemplate.id.desc()).all()
    return [{"id": r.id, "code": r.code, "subject": r.subject, "body": r.body, "is_active": r.is_active} for r in rows]


@router.post("/settings/email-templates")
def upsert_email_template(
    body: EmailTemplateIn,
    _: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    row = db.query(EmailTemplate).filter(EmailTemplate.code == body.code).first()
    if not row:
        row = EmailTemplate(code=body.code)
        db.add(row)
    row.subject = body.subject
    row.body = body.body
    row.is_active = body.is_active
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "subject": row.subject, "body": row.body, "is_active": row.is_active}


@router.get("/settings/email-logs")
def list_email_logs(
    limit: int = Query(default=100, le=500),
    _: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    rows = db.query(EmailLog).order_by(EmailLog.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "to_email": r.to_email,
            "subject": r.subject,
            "status": r.status,
            "provider": r.provider,
            "error": r.error,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/settings/notifications")
def get_notification_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = _notification_prefs(db, user.id)
    return {
        "email_enabled": row.email_enabled,
        "in_app_enabled": row.in_app_enabled,
        "sms_enabled": row.sms_enabled,
        "whatsapp_enabled": row.whatsapp_enabled,
        "categories": json.loads(row.categories_json or "[]"),
    }


@router.put("/settings/notifications")
def update_notification_preferences(
    body: NotificationPrefsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _notification_prefs(db, user.id)
    data = body.model_dump(exclude_unset=True)
    if "categories" in data:
        row.categories_json = json.dumps(data.pop("categories") or [])
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    return get_notification_preferences(db, user)


@router.get("/charts/sales-monthly")
def chart_sales_monthly(year: int = Query(default=0), db: Session = Depends(get_db)):
    from datetime import date as date_cls
    y = year or date_cls.today().year
    rows = db.query(
        extract("month", Invoice.date).label("m"),
        func.coalesce(func.sum(Invoice.amount), 0).label("total"),
    ).filter(
        Invoice.date != None,
        extract("year", Invoice.date) == y,
    ).group_by("m").all()
    months = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    data = [0.0] * 12
    for m, total in rows:
        if m:
            data[int(m) - 1] = float(total)
    return {"labels": months, "data": data, "year": y}


@router.get("/charts/purchases-monthly")
def chart_purchases_monthly(year: int = Query(default=0), db: Session = Depends(get_db)):
    from datetime import date as date_cls
    from app.models_erp import SupplierInvoice
    y = year or date_cls.today().year
    rows = db.query(
        extract("month", SupplierInvoice.date).label("m"),
        func.coalesce(func.sum(SupplierInvoice.amount), 0).label("total"),
    ).filter(
        SupplierInvoice.date != None,
        extract("year", SupplierInvoice.date) == y,
    ).group_by("m").all()
    months = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    data = [0.0] * 12
    for m, total in rows:
        if m:
            data[int(m) - 1] = float(total)
    return {"labels": months, "data": data, "year": y}


@router.get("/charts/expenses-category")
def chart_expenses(db: Session = Depends(get_db)):
    rows = db.query(
        Transaction.category,
        func.sum(Transaction.amount).label("t"),
    ).filter(Transaction.type == "charge").group_by(Transaction.category).all()
    return {
        "labels": [r[0] or "Autre" for r in rows],
        "data": [float(r[1] or 0) for r in rows],
    }


@router.get("/charts/pipeline-stages")
def chart_pipeline(db: Session = Depends(get_db)):
    rows = db.query(Deal.stage, func.count(Deal.id), func.sum(Deal.amount)).group_by(Deal.stage).all()
    return {
        "labels": [r[0] for r in rows],
        "counts": [r[1] for r in rows],
        "amounts": [float(r[2] or 0) for r in rows],
    }


@router.get("/charts/stock-value")
def chart_stock(db: Session = Depends(get_db)):
    items = db.query(StockItem).order_by((StockItem.quantity * StockItem.unit_cost).desc()).limit(8).all()
    return {
        "labels": [i.name[:20] for i in items],
        "data": [float((i.quantity or 0) * (i.unit_cost or 0)) for i in items],
    }


@router.get("/charts/cashflow")
def chart_cashflow(db: Session = Depends(get_db)):
    prod = db.query(Transaction).filter(Transaction.type == "produit").order_by(Transaction.date).limit(12).all()
    chg = db.query(Transaction).filter(Transaction.type == "charge").order_by(Transaction.date).limit(12).all()
    labels = [f"M{i+1}" for i in range(12)]
    p = [0.0] * 12
    c = [0.0] * 12
    for i, t in enumerate(prod[:12]):
        p[i] = t.amount or 0
    for i, t in enumerate(chg[:12]):
        c[i] = t.amount or 0
    return {"labels": labels, "products": p, "charges": c}


@router.get("/search")
def global_search(q: str = Query(min_length=1), db: Session = Depends(get_db)):
    term = f"%{q}%"
    results = []
    for c in db.query(Client).filter(Client.name.ilike(term)).limit(8):
        results.append({"type": "client", "id": c.id, "label": c.name, "view": "clients"})
    for i in db.query(Invoice).filter(Invoice.number.ilike(term)).limit(5):
        results.append({"type": "invoice", "id": i.id, "label": i.number, "view": "invoices"})
    for qo in db.query(Quote).filter(Quote.number.ilike(term)).limit(5):
        results.append({"type": "quote", "id": qo.id, "label": qo.number, "view": "quotes"})
    for s in db.query(Supplier).filter(Supplier.name.ilike(term)).limit(5):
        results.append({"type": "supplier", "id": s.id, "label": s.name, "view": "suppliers"})
    return results


@router.post("/invoices/{iid}/payment")
def record_payment(
    iid: int,
    body: PaymentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "update")),
):
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    if not inv:
        raise HTTPException(404)
    inv.paid = (inv.paid or 0) + body.amount
    if inv.paid >= (inv.amount or 0):
        inv.status = "payée"
    pay_date = body.date or date.today()
    db.add(Transaction(
        date=pay_date,
        label=f"Paiement facture {inv.number}",
        type="produit",
        amount=body.amount,
        category="Encaissement",
        payment_method=body.method,
        reference=inv.number,
        notes=body.notes,
    ))
    from app.models_accounting import PaymentRecord
    from app.services.accounting_hooks import dispatch_invoice_posting, dispatch_payment

    pr = PaymentRecord(
        direction="in",
        invoice_id=inv.id,
        date=pay_date,
        amount=body.amount,
        method=body.method or "banque",
        reference=inv.number or "",
        notes=body.notes or "",
    )
    db.add(pr)
    db.flush()
    if not getattr(inv, "journal_entry_id", None):
        dispatch_invoice_posting(db, inv)
    pay_res = dispatch_payment(
        db,
        direction="in",
        amount=body.amount,
        method=body.method or "banque",
        reference=inv.number or "",
        label=f"Encaissement {inv.number}",
        payment_record_id=pr.id,
        entry_date=pay_date,
    )
    if pay_res.get("journal_entry_id"):
        pr.journal_entry_id = pay_res["journal_entry_id"]
    db.commit()
    db.refresh(inv)
    create_app_notification(
        db,
        user_id=user.id,
        type_="success",
        title=f"Paiement reçu {inv.number}",
        message=f"Encaissement de {body.amount:.2f}",
        category="billing",
    )
    db.commit()
    from app.services.notification_engine import notify_payment_received
    notify_payment_received(db, body.amount, inv.number or "", user.id)
    return inv


@router.post("/quotes/{qid}/duplicate")
def duplicate_quote(
    qid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("quotes", "create")),
):
    from app.models import DocumentLine  # noqa: F401
    from app.commercial_service import next_quote_number
    q = db.query(Quote).filter(Quote.id == qid).first()
    if not q:
        raise HTTPException(404)
    new_q = Quote(
        number=next_quote_number(db),
        client_id=q.client_id,
        title=(q.title or "") + " (copie)",
        date=date.today(),
        valid_until=q.valid_until,
        amount=q.amount,
        vat_rate=q.vat_rate or 0,
        status="brouillon",
    )
    db.add(new_q)
    db.flush()
    for ln in db.query(DocumentLine).filter(DocumentLine.quote_id == qid).all():
        db.add(DocumentLine(
            quote_id=new_q.id, position=ln.position,
            description=ln.description, quantity=ln.quantity,
            unit_price=ln.unit_price, vat_rate=ln.vat_rate,
        ))
    db.commit()
    db.refresh(new_q)
    return new_q


_notif_gen_at: dict[int, float] = {}
NOTIF_GENERATE_INTERVAL_SEC = 900  # 15 min — évite de ralentir chaque ouverture du panneau


def _maybe_generate_system_notifications(db: Session, user_id: int) -> None:
    now = time.monotonic()
    if now - _notif_gen_at.get(user_id, 0.0) < NOTIF_GENERATE_INTERVAL_SEC:
        return
    _notif_gen_at[user_id] = now
    _generate_system_notifications(db, user_id)


@router.get("/notifications/unread-count")
def notifications_unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Compteur léger pour le badge — sans génération ni liste complète."""
    unread = (
        db.query(AppNotification)
        .filter(AppNotification.user_id == user.id, AppNotification.read == False)
        .count()
    )
    return {"unread": unread}


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(default=False),
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _maybe_generate_system_notifications(db, user.id)
    q = db.query(AppNotification).filter(AppNotification.user_id == user.id)
    if unread_only:
        q = q.filter(AppNotification.read == False)
    if category:
        q = q.filter(AppNotification.category == category)
    rows = q.order_by(AppNotification.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "type": r.type,
            "title": r.title,
            "message": r.message,
            "read": r.read,
            "created_at": r.created_at,
            "category": r.category,
            "channel": r.channel,
        }
        for r in rows
    ]


@router.post("/notifications/{nid}/read")
def mark_read(nid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.query(AppNotification).filter(AppNotification.id == nid, AppNotification.user_id == user.id).first()
    if n:
        n.read = True
        db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(AppNotification).filter(AppNotification.user_id == user.id).update({"read": True})
    db.commit()
    return {"ok": True}


def _generate_system_notifications(db: Session, user_id: int):
    """Alertes auto : factures retard, stock bas."""
    today = datetime.now().isoformat()[:10]
    existing = {n.title for n in db.query(AppNotification).filter(
        AppNotification.user_id == user_id,
        AppNotification.created_at == today,
    ).all()}
    late = db.query(Invoice).filter(Invoice.status == "en retard").count()
    if late and f"retard-{today}" not in existing:
        create_app_notification(
            db,
            user_id=user_id,
            type_="warn",
            title=f"retard-{today}",
            message=f"{late} facture(s) en retard",
            category="billing",
        )
    low = db.query(StockItem).filter(StockItem.quantity <= StockItem.min_quantity).count()
    if low and f"stock-{today}" not in existing:
        create_app_notification(
            db,
            user_id=user_id,
            type_="warn",
            title=f"stock-{today}",
            message=f"{low} article(s) sous le seuil",
            category="stock",
        )
    from app.models_erp import SupplierInvoice, Budget
    from datetime import date as ddate
    due_sup = db.query(SupplierInvoice).filter(
        SupplierInvoice.due_date.isnot(None),
        SupplierInvoice.due_date <= ddate.today(),
        SupplierInvoice.status.in_(["validée", "en retard"]),
    ).count()
    if due_sup and f"supplier-due-{today}" not in existing:
        create_app_notification(
            db,
            user_id=user_id,
            type_="warn",
            title=f"supplier-due-{today}",
            message=f"{due_sup} échéance(s) fournisseur à traiter",
            category="achats",
        )
    for b in db.query(Budget).all():
        planned = b.amount_planned or 0
        actual = b.amount_actual or 0
        if planned > 0 and actual > planned * 1.05:
            key = f"budget-{b.id}-{today}"
            if key not in existing:
                create_app_notification(
                    db,
                    user_id=user_id,
                    type_="warn",
                    title=key,
                    message=f"Budget « {b.name} » dépassé ({actual:,.0f} / {planned:,.0f})",
                    category="finance",
                )
    db.commit()


@router.post("/settings/backup/run")
def run_backup_now(
    user: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    from app.services.database_backup_service import create_backup
    from app.services.audit_log import log_audit

    try:
        backup = create_backup("peya_backup")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    s = _system_settings(db)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    s.backup_last_run = stamp
    s.backup_enabled = True
    log_audit(
        db, "backup", "paramètres", "database", None, backup.name,
        user.id, user.email or "", "",
    )
    db.commit()
    return {"ok": True, "path": str(backup), "filename": backup.name}


@router.get("/settings/backup/list")
def list_db_backups(_: User = Depends(require_permission("users.manage"))):
    from app.services.database_backup_service import list_backups
    return {"ok": True, "backups": list_backups(50)}


@router.get("/settings/backup/download/{filename}")
def download_server_backup(
    filename: str,
    _: User = Depends(require_permission("users.manage")),
):
    from app.services.database_backup_service import resolve_backup_path

    try:
        path = resolve_backup_path(filename)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/settings/backup/restore/{filename}")
def restore_server_backup(
    filename: str,
    body: BackupRestoreIn,
    request: Request,
    user: User = Depends(require_permission("users.manage")),
):
    from app.services.database_backup_service import resolve_backup_path, restore_database
    from app.services.audit_log import log_audit
    from app.database import SessionLocal

    _verify_restore_credentials(user, body.admin_password, body.confirm_text)

    try:
        path = resolve_backup_path(filename)
        result = restore_database(path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    db = SessionLocal()
    try:
        ip = request.client.host if request.client else ""
        log_audit(
            db, "restore", "paramètres", "database", None,
            f"Depuis {filename} — pré-sauvegarde {result['pre_restore_backup']}",
            user.id, user.email or "", ip,
        )
        db.commit()
    finally:
        db.close()

    result["message"] = (
        "Base restaurée. Reconnectez-vous pour utiliser la nouvelle base. "
        f"Sauvegarde de sécurité : {result['pre_restore_backup']}"
    )
    return result


@router.post("/settings/backup/upload")
async def upload_database_backup(
    request: Request,
    file: UploadFile = File(...),
    apply: bool = Form(False),
    admin_password: str = Form(""),
    confirm_text: str = Form(""),
    user: User = Depends(require_permission("users.manage")),
):
    """Importe un fichier .db (validation SQLite). apply=true : restauration immédiate."""
    from app.upload_limits import read_bounded, assert_extension, DATABASE_EXT, MAX_DB_UPLOAD_BYTES
    from app.services.database_backup_service import save_uploaded_database, restore_database
    from app.services.audit_log import log_audit
    from app.database import SessionLocal

    assert_extension(file.filename, DATABASE_EXT)
    data = await read_bounded(file, max_bytes=MAX_DB_UPLOAD_BYTES)

    if apply:
        _verify_restore_credentials(user, admin_password, confirm_text)

    try:
        saved, meta = save_uploaded_database(data, file.filename or "upload.db")
        if apply:
            result = restore_database(saved)
            action = "restore_upload"
            payload = {**result, "uploaded_as": saved.name, "meta": meta}
        else:
            action = "upload"
            payload = {"ok": True, "uploaded_as": saved.name, "meta": meta, "applied": False}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    db = SessionLocal()
    try:
        ip = request.client.host if request.client else ""
        log_audit(
            db, action, "paramètres", "database", None,
            saved.name if not apply else f"Upload+restore {saved.name}",
            user.id, user.email or "", ip,
        )
        db.commit()
    finally:
        db.close()

    if apply:
        payload["message"] = (
            "Base importée et activée. Reconnectez-vous. "
            f"Sauvegarde de sécurité : {payload.get('pre_restore_backup', '—')}"
        )
    else:
        payload["message"] = f"Fichier importé sur le serveur : {saved.name}"
    return payload


@router.delete("/settings/backup/{filename}")
def delete_server_backup(
    filename: str,
    request: Request,
    user: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    from app.services.database_backup_service import delete_backup
    from app.services.audit_log import log_audit

    try:
        delete_backup(filename)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    ip = request.client.host if request.client else ""
    log_audit(db, "delete", "paramètres", "database_backup", None, filename, user.id, user.email or "", ip)
    db.commit()
    return {"ok": True}


@router.get("/backup/database")
def backup_db(_: User = Depends(require_permission("users.manage"))):
    from app.services.database_backup_service import create_backup

    if not DB_PATH.exists():
        raise HTTPException(404, "Base introuvable")
    try:
        backup = create_backup("peya_download")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return FileResponse(
        backup,
        filename=f"peya_company_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
        media_type="application/octet-stream",
        background=BackgroundTask(lambda p=backup: p.unlink(missing_ok=True)),
    )


DEFAULT_BUSINESS_PLAN = {
    "executive_summary": "Peya Company — ERP intégré pour PME au Togo : consulting, formation, installations et développement.",
    "company_presentation": "SARL basée à Lomé, spécialisée dans l'accompagnement digital et la formation professionnelle.",
    "market_analysis": "Marché togolais en digitalisation accélérée — TPE/PME, collectivités et institutions.",
    "competition_analysis": "Concurrence fragmentée (cabinet comptable, logiciels génériques, prestataires locaux).",
    "products_services": "Consulting, formation Qualiopi, installations réseau, développement sur mesure, ERP Peya.",
    "marketing_strategy": "Réseau, recommandations, contenus, partenariats institutionnels, démonstrations ERP.",
    "financial_forecasts": {"year1": 100_000_000, "year2": 150_000_000, "year3": 220_000_000},
    "objectives": "100 M FCFA CA An 1 · 32 j formation · 50 clients actifs · marge nette > 15%.",
    "action_plan": "Q1 lancement commercial · Q2 industrialisation · Q3 expansion Kara · Q4 consolidation.",
    "swot": {
        "strengths": "Équipe pluridisciplinaire, ERP propriétaire, connaissance locale",
        "weaknesses": "Notoriété à construire, dépendance fondateurs",
        "opportunities": "Digitalisation publique, formation continue, ERP PME",
        "threats": "Concurrence low-cost, change réglementaire",
    },
    "risks": "Retard encaissement, turnover, cybersécurité, dépendance fournisseurs.",
    "conclusion": "Positionnement premium accessible — croissance progressive et rentable.",
}


class BusinessPlanIn(BaseModel):
    plan: dict


@router.get("/business-plan")
def get_business_plan(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("dashboard", "view")),
):
    s = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    docs = _parse_json(getattr(s, "documents_json", None) or "{}", {})
    plan = docs.get("business_plan") if isinstance(docs, dict) else None
    return plan if isinstance(plan, dict) and plan else DEFAULT_BUSINESS_PLAN


@router.put("/business-plan")
def put_business_plan(
    body: BusinessPlanIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    s = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if not s:
        raise HTTPException(404, "Paramètres système introuvables")
    docs = _parse_json(getattr(s, "documents_json", None) or "{}", {})
    if not isinstance(docs, dict):
        docs = {}
    docs["business_plan"] = body.plan
    s.documents_json = json.dumps(docs, ensure_ascii=False)
    db.commit()
    return {"ok": True, "plan": body.plan}

