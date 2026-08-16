"""Initialisation : compte admin bootstrap (pas de données factices)."""
from sqlalchemy.orm import Session
import os

from app.auth import hash_password
from app.models import User, CompanyProfile
from app.models_prefs import SystemSettings, EmailTemplate
from app.services.smtp_service import get_smtp_settings
from app.routers.currencies import ensure_currencies_seeded
from app.region_config import REGION

_FALLBACK_ADMIN_EMAIL = "admin@peyacompany.com"
_FALLBACK_ADMIN_PASSWORD = "Password1234@"


def _bootstrap_admin_credentials() -> tuple[str, str]:
    """Lit les identifiants bootstrap admin depuis l'environnement."""
    from app.server_config import is_production

    email = (os.environ.get("PEYA_ADMIN_EMAIL") or _FALLBACK_ADMIN_EMAIL).strip().lower()
    password = (os.environ.get("PEYA_ADMIN_PASSWORD") or "").strip()
    if not password and not is_production():
        password = _FALLBACK_ADMIN_PASSWORD

    if is_production():
        if not email or email == _FALLBACK_ADMIN_EMAIL:
            raise RuntimeError(
                "PEYA_ADMIN_EMAIL obligatoire en production (ne pas utiliser la valeur par défaut)."
            )
        if not password or password == _FALLBACK_ADMIN_PASSWORD:
            raise RuntimeError(
                "PEYA_ADMIN_PASSWORD obligatoire en production (ne pas utiliser la valeur par défaut)."
            )
    return email, password

DEFAULT_COMPANY_DESCRIPTION = REGION["description"]


def ensure_company_profile(db: Session) -> None:
    if db.query(CompanyProfile).filter(CompanyProfile.id == 1).first():
        return
    db.add(CompanyProfile(
        id=1,
        name=REGION["company_name"],
        legal_form=REGION["legal_form"],
        tagline=REGION["tagline"],
        description=DEFAULT_COMPANY_DESCRIPTION,
        address=REGION["address_default"],
        email="contact@peyacompany.com",
        logo_path="/static/logo-peya.png",
        currency=REGION["currency_label"],
    ))
    db.commit()


DEFAULT_SYSTEM_TAXES = [{"code": "TVA0", "name": "TVA", "rate": 0, "default": True}]


def _ensure_default_vat_tax_settings(sys) -> None:
    """Assure un taux TVA par défaut explicite (0 % si legacy sans flag default)."""
    import json
    try:
        taxes = json.loads(sys.taxes_json or "[]")
    except json.JSONDecodeError:
        taxes = []
    if not taxes:
        sys.taxes_json = json.dumps(DEFAULT_SYSTEM_TAXES)
        return
    if any(t.get("default") for t in taxes):
        return
    zero = next((t for t in taxes if float(t.get("rate") or 0) == 0), None)
    pick = zero or taxes[0]
    for t in taxes:
        t["default"] = t.get("code") == pick.get("code") and float(t.get("rate") or 0) == float(pick.get("rate") or 0)
    if not any(t.get("default") for t in taxes):
        taxes[0]["default"] = True
    sys.taxes_json = json.dumps(taxes)


def ensure_platform_defaults(db: Session) -> None:
    """Tables système (paramètres, SMTP, modèles e-mail par défaut)."""
    if not db.query(SystemSettings).filter(SystemSettings.id == 1).first():
        import json
        from app.syscohada.constants import JOURNALS, DEFAULT_ACCOUNTS
        db.add(SystemSettings(
            id=1,
            accounting_plan="SYSCOHADA",
            journals_json=json.dumps([j["code"] for j in JOURNALS]),
            taxes_json=json.dumps(DEFAULT_SYSTEM_TAXES),
            default_accounts_json=json.dumps(DEFAULT_ACCOUNTS),
        ))
    get_smtp_settings(db)
    templates = [
        ("invoice.created", "Facture {{number}} créée", "<p>La facture <strong>{{number}}</strong> a été créée.</p>"),
        ("invoice.paid", "Paiement reçu — {{number}}", "<p>Paiement enregistré pour la facture {{number}}.</p>"),
        ("quote.created", "Devis {{number}} créé", "<p>Le devis <strong>{{number}}</strong> est disponible.</p>"),
        ("import.done", "Import terminé", "<p>L'import de données s'est terminé.</p>"),
    ]
    for code, subject, body in templates:
        if not db.query(EmailTemplate).filter(EmailTemplate.code == code).first():
            db.add(EmailTemplate(code=code, subject=subject, body=body, is_active=True))
    db.commit()
    ensure_currencies_seeded(db)
    from app.services.stock_service import ensure_default_warehouses
    ensure_default_warehouses(db)
    from app.routers.enterprise import ensure_default_companies
    ensure_default_companies(db)
    ensure_syscohada_chart(db)
    patch_region_togo(db)
    from app.services.approval_engine import seed_default_rules
    from app.services.notification_engine import seed_notification_rules, run_scheduled_checks
    seed_default_rules(db)
    seed_notification_rules(db)
    try:
        run_scheduled_checks(db)
    except Exception:
        pass
    from app.services.enterprise_suite_service import seed_connectors
    seed_connectors(db)
    from app.services.enterprise_suite_service import ensure_default_ged_folder
    ensure_default_ged_folder(db)


def ensure_syscohada_chart(db: Session) -> dict | None:
    """Complète le plan SYSCOHADA officiel au démarrage (1409 comptes)."""
    from app.models import Account
    from app.syscohada.chart import SYSCOHADA_CHART
    from app.syscohada.service import import_syscohada_chart

    if db.query(Account).count() >= len(SYSCOHADA_CHART):
        return None
    return import_syscohada_chart(db, force=False)


def patch_region_togo(db: Session) -> None:
    """Met à jour profil société et paramètres système vers le Togo (bases existantes)."""
    from app.models_prefs import SystemSettings
    from app.models_enterprise import Company

    prof = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if prof:
        if not prof.address or "Guyane" in (prof.address or "") or "Cayenne" in (prof.address or ""):
            prof.address = REGION["address_default"]
        if prof.tagline and "Guyane" in prof.tagline:
            prof.tagline = REGION["tagline"]
        if prof.description and "Guyane" in prof.description:
            prof.description = REGION["description"]
        prof.currency = REGION["currency_label"]
        if prof.legal_form == "SASU":
            prof.legal_form = REGION["legal_form"]

    sys = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if sys:
        if not sys.timezone or sys.timezone in ("America/Cayenne", "Africa/Abidjan"):
            sys.timezone = REGION["timezone"]
        if not sys.currency or sys.currency == "FCFA":
            sys.currency = REGION["currency_iso"]
        if hasattr(sys, "company_name") and sys.company_name and "Guyane" in (sys.company_name or ""):
            sys.company_name = REGION["company_name"]
        _ensure_default_vat_tax_settings(sys)
        if getattr(sys, "accounting_plan", "PCG") in ("PCG", "", None):
            import json
            from app.syscohada.constants import JOURNALS, DEFAULT_ACCOUNTS
            sys.accounting_plan = "SYSCOHADA"
            if not sys.journals_json or sys.journals_json == '["VE","AC","BQ","CA","OD"]':
                sys.journals_json = json.dumps([j["code"] for j in JOURNALS])
            if not sys.default_accounts_json or "706" in (sys.default_accounts_json or ""):
                sys.default_accounts_json = json.dumps(DEFAULT_ACCOUNTS)

    default_co = db.query(Company).filter(Company.is_default == True).first()
    if default_co and ("Guyane" in (default_co.address or "") or default_co.code == "PEYA"):
        default_co.address = REGION["address_default"]
        default_co.name = REGION["company_name"]
        default_co.legal_form = REGION["legal_form"]
        default_co.currency = REGION["currency_iso"]

    try:
        from app.models_stock import Warehouse
        renames = {
            "DEP-CAY": ("DEP-LOM", "Dépôt Lomé", "Lomé"),
            "ENT-STL": ("ENT-KAR", "Entrepôt Kara", "Kara"),
            "MAG-CAY": ("MAG-LOM", "Magasin Lomé", "Lomé"),
        }
        for old_code, (new_code, name, city) in renames.items():
            w = db.query(Warehouse).filter(Warehouse.code == old_code).first()
            if w:
                w.code, w.name, w.city = new_code, name, city
    except Exception:
        pass

    db.commit()


def ensure_admin_user(db: Session) -> None:
    if db.query(User).filter(User.role == "admin").first():
        return
    admin_email, admin_password = _bootstrap_admin_credentials()
    if db.query(User).filter(User.email == admin_email).first():
        return
    from datetime import datetime, timezone
    from app.services.password_service import compute_password_expires_at, get_password_policy

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    policy = get_password_policy(db)
    admin = User(
        email=admin_email,
        username="admin",
        first_name="Administrateur",
        last_name="Peya",
        full_name="Administrateur Peya Company",
        role="admin",
        password_hash=hash_password(admin_password),
        must_change_password=True,
        last_password_change=now,
        is_active=True,
    )
    admin.password_expires_at = compute_password_expires_at(admin, policy)
    db.add(admin)
    db.commit()
    ensure_company_profile(db)
