"""Ressources graphiques centralisées pour tous les PDF et documents."""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

_LOGO_OVERRIDE: Optional[Path] = None
_CURRENT_DB: Optional[Session] = None

PDF_LOGO_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "assets" / "logo-peya.png",
    Path(__file__).resolve().parents[2] / "assets" / "logo-peya.png",
    Path(__file__).resolve().parents[3] / "frontend" / "logo-peya.png",
]


@dataclass
class BrandingBundle:
    logo_path: Optional[Path] = None
    company_name: str = "Peya Company"
    legal_form: str = ""
    tagline: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    footer_legal: str = ""
    asset_version: str = ""
    logo_media_id: Optional[int] = None
    pdf_settings: dict = field(default_factory=dict)


def get_current_db() -> Optional[Session]:
    return _CURRENT_DB


def _settings_raw(db: Session, *, prefer_published: bool = True) -> dict:
    from app.models_cms import CmsSiteSettings
    from app.services.cms_service import _parse_json, default_site_settings

    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    if not row:
        return default_site_settings()
    if prefer_published and row.settings_json:
        return _parse_json(row.settings_json, default_site_settings())
    return _parse_json(row.draft_json or row.settings_json, default_site_settings())


def resolve_media_file_path(db: Session, slot: str) -> Optional[Path]:
    """Fichier physique d'un slot logo CMS (pdf, main, signature, stamp…)."""
    from app.models_cms import CmsMedia
    from app.services.cms_service import CMS_MEDIA_ROOT

    raw = _settings_raw(db)
    logos = raw.get("logos") or {}
    entry = logos.get(slot) or {}
    mid = entry.get("media_id") if isinstance(entry, dict) else None
    if not mid:
        return None
    m = db.query(CmsMedia).filter(CmsMedia.id == mid).first()
    if not m or not m.file_path:
        return None
    src = CMS_MEDIA_ROOT / m.file_path
    return src if src.is_file() else None


def resolve_pdf_logo_path(db: Optional[Session] = None) -> Optional[Path]:
    """Logo PDF : slot « pdf » puis « main », puis fichiers statiques."""
    if db is not None:
        for slot in ("pdf", "main"):
            p = resolve_media_file_path(db, slot)
            if p:
                return p
    for p in PDF_LOGO_CANDIDATES:
        if p.is_file():
            return p
    return None


def get_active_logo_path(db: Optional[Session] = None) -> Optional[Path]:
    if _LOGO_OVERRIDE and _LOGO_OVERRIDE.is_file():
        return _LOGO_OVERRIDE
    return resolve_pdf_logo_path(db or _CURRENT_DB)


def get_company_profile(db: Session):
    from app.models import CompanyProfile

    return db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()


def get_branding_bundle(db: Session) -> BrandingBundle:
    from app.services.cms_identity_service import normalize_logos
    from app.services.cms_service import asset_version_token
    from app.models_cms import CmsSiteSettings

    raw = _settings_raw(db)
    logos = normalize_logos(raw, db)
    pdf_entry = logos.get("pdf") or logos.get("main") or {}
    prof = get_company_profile(db)
    pdf_settings = raw.get("pdf_settings") or {}
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    version = asset_version_token(row.updated_at if row else "")

    return BrandingBundle(
        logo_path=resolve_pdf_logo_path(db),
        company_name=(prof.name if prof and prof.name else "Peya Company"),
        legal_form=(prof.legal_form if prof else "") or "",
        tagline=(prof.tagline if prof else "") or "",
        address=(prof.address if prof else "") or "",
        phone=(prof.phone if prof else "") or "",
        email=(prof.email if prof else "") or "",
        footer_legal=pdf_settings.get("footer_legal") or raw.get("footer_text") or "Document confidentiel",
        asset_version=version,
        logo_media_id=pdf_entry.get("media_id"),
        pdf_settings=pdf_settings,
    )


def company_header_lines(db: Optional[Session] = None) -> list[str]:
    db = db or _CURRENT_DB
    if db is None:
        return ["Peya Company"]
    b = get_branding_bundle(db)
    lines = [b.company_name]
    if b.legal_form:
        lines[0] = f"{b.company_name} · {b.legal_form}"
    if b.address:
        lines.append(b.address)
    contact = " · ".join(x for x in [b.phone, b.email] if x)
    if contact:
        lines.append(contact)
    return lines


def log_pdf_generation(
    db: Session,
    report_type: str,
    *,
    user_id: int = None,
    user_email: str = "",
    fiscal_year: Optional[int] = None,
):
    """Trace génération PDF : modèle, version logo, utilisateur."""
    from app.services.audit_log import log_audit

    b = get_branding_bundle(db)
    detail = json.dumps(
        {
            "report": report_type,
            "fiscal_year": fiscal_year,
            "logo_media_id": b.logo_media_id,
            "asset_version": b.asset_version,
        },
        ensure_ascii=False,
    )
    log_audit(
        db,
        "export_pdf",
        "documents",
        "pdf_report",
        entity_id=0,
        detail=detail,
        user_id=user_id,
        user_email=user_email,
    )


@contextmanager
def pdf_branding_context(db: Session):
    """Contexte de génération PDF avec logo CMS résolu dynamiquement."""
    global _LOGO_OVERRIDE, _CURRENT_DB
    prev_logo = _LOGO_OVERRIDE
    prev_db = _CURRENT_DB
    _CURRENT_DB = db
    _LOGO_OVERRIDE = resolve_pdf_logo_path(db)
    try:
        yield get_branding_bundle(db)
    finally:
        _LOGO_OVERRIDE = prev_logo
        _CURRENT_DB = prev_db
