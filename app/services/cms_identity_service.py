"""Identité visuelle — logos et propagation ERP / PDF / site."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import CompanyProfile
from app.models_cms import CmsMedia, CmsSiteSettings
from app.models_prefs import SystemSettings
from app.services.cms_service import _now, _parse_json, asset_version_token, default_site_settings, media_public_url
from app.services.cms_media_service import media_to_dict

LOGO_SLOTS = [
    ("main", "Logo principal", "Site — en-tête"),
    ("white", "Logo blanc", "Fonds sombres"),
    ("dark", "Logo sombre", "Fonds clairs"),
    ("favicon", "Favicon", "Onglet navigateur"),
    ("footer", "Logo pied de page", "Bas de page"),
    ("pdf", "Logo PDF", "Factures, devis, rapports"),
    ("email", "Logo e-mails", "Notifications"),
    ("institutional", "Image institutionnelle", "Pages institutionnelles"),
]

# Slots propagés immédiatement (sans clic « Appliquer »)
LIVE_SYNC_SLOTS = frozenset({"main", "pdf", "favicon", "white", "dark", "footer", "email", "institutional"})

from app.services.pdf_branding import PDF_LOGO_CANDIDATES

ASSETS_LOGO = PDF_LOGO_CANDIDATES[0]
FRONTEND_LOGO = PDF_LOGO_CANDIDATES[2]


def _slot_entry(media: Optional[CmsMedia] = None, url: str = "") -> dict:
    if media:
        d = media_to_dict(media)
        return {"media_id": media.id, "url": d["webp_url"] or d["url"], "preview": d["url"]}
    return {"media_id": None, "url": url or "", "preview": url or ""}


def normalize_logos(raw: dict, db: Session) -> dict:
    """Convertit anciennes URLs string → structure {media_id, url}."""
    logos_in = raw.get("logos") or {}
    out = {}
    for key, _label, _hint in LOGO_SLOTS:
        val = logos_in.get(key)
        if isinstance(val, dict):
            mid = val.get("media_id")
            url = val.get("url") or ""
            if mid:
                m = db.query(CmsMedia).filter(CmsMedia.id == mid).first()
                out[key] = _slot_entry(m, url)
            else:
                out[key] = _slot_entry(None, url)
        elif isinstance(val, str):
            out[key] = _slot_entry(None, val)
        else:
            out[key] = _slot_entry(None, "")
    return out


def get_identity_bundle(db: Session, *, draft: bool = False) -> dict:
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    raw = _parse_json(
        (row.draft_json if draft and row.draft_json else None) or row.settings_json,
        default_site_settings(),
    )
    logos = normalize_logos(raw, db)
    return {
        "logos": logos,
        "footer_text": raw.get("footer_text", ""),
        "pdf_settings": raw.get("pdf_settings") or default_site_settings().get("pdf_settings", {}),
        "nav_links": raw.get("nav_links", []),
        "locales": raw.get("locales", ["fr", "en", "es"]),
        "dashboard_content": raw.get("dashboard_content") or {},
        "login_content": raw.get("login_content") or {},
        "updated_at": row.updated_at if row else "",
        "asset_version": asset_version_token(row.updated_at if row else ""),
    }


def set_logo_slot(db: Session, slot: str, media_id: Optional[int], url: str = "") -> dict:
    valid = {k for k, _, _ in LOGO_SLOTS}
    if slot not in valid:
        raise ValueError(f"Slot logo inconnu: {slot}")
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    draft = _parse_json(row.draft_json or row.settings_json, default_site_settings())
    logos = draft.setdefault("logos", {})
    if media_id:
        m = db.query(CmsMedia).filter(CmsMedia.id == media_id).first()
        if not m:
            raise ValueError("Média introuvable")
        logos[slot] = {"media_id": media_id, "url": media_public_url(m.file_path)}
    else:
        logos[slot] = {"media_id": None, "url": url}
    row.draft_json = json.dumps(draft, ensure_ascii=False)

    files_updated: list = []
    auto_synced = False
    if slot in LIVE_SYNC_SLOTS:
        published = _parse_json(row.settings_json, default_site_settings())
        published.setdefault("logos", {})[slot] = dict(logos[slot])
        row.settings_json = json.dumps(published, ensure_ascii=False)
        auto_synced = True
        if slot in ("pdf", "main"):
            mid = logos[slot].get("media_id")
            if slot == "pdf" and not mid:
                mid = published.get("logos", {}).get("main", {}).get("media_id")
            files_updated = _copy_logo_file_to_assets(db, mid)
        if slot == "main":
            prof = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
            if prof:
                prof.logo_path = logos[slot].get("url") or prof.logo_path
            sys = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
            if sys and hasattr(sys, "company_logo"):
                sys.company_logo = logos[slot].get("url") or sys.company_logo

    row.updated_at = _now()
    db.commit()
    entry = normalize_logos(draft, db)[slot]
    version = asset_version_token(row.updated_at or "")
    return {
        **entry,
        "asset_version": version,
        "auto_synced": auto_synced,
        "files_updated": files_updated,
    }


def resync_logo_assets_for_media(db: Session, media_id: int) -> list:
    """Recopie assets PDF si un média logo vient d'être remplacé dans la médiathèque."""
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    if not row or not media_id:
        return []
    raw = _parse_json(row.settings_json or row.draft_json, default_site_settings())
    logos = normalize_logos(raw, db)
    updated: list = []
    for slot in ("pdf", "main"):
        if logos.get(slot, {}).get("media_id") == media_id:
            updated.extend(_copy_logo_file_to_assets(db, media_id))
    if updated:
        row.updated_at = _now()
        db.commit()
    return updated


def apply_identity_globally(db: Session, user_id: int = 0) -> dict:
    """Publie identité + propage logos vers profil société, paramètres système, fichiers PDF."""
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    draft = _parse_json(row.draft_json or row.settings_json, default_site_settings())
    row.settings_json = json.dumps(draft, ensure_ascii=False)
    row.updated_at = _now()
    row.updated_by = user_id

    logos = normalize_logos(draft, db)
    main_url = logos.get("main", {}).get("url") or "/static/logo-peya.png"
    pdf_url = logos.get("pdf", {}).get("url") or main_url

    prof = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if prof:
        prof.logo_path = main_url

    sys = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if sys and hasattr(sys, "company_logo"):
        sys.company_logo = main_url

    media_id = logos.get("pdf", {}).get("media_id") or logos.get("main", {}).get("media_id")
    copied = _copy_logo_file_to_assets(db, media_id)

    db.commit()
    version = asset_version_token(row.updated_at or "")
    return {
        "ok": True,
        "main_url": main_url,
        "pdf_url": pdf_url,
        "files_updated": copied,
        "asset_version": version,
        "message": "Identité appliquée : site, PDF, factures et paramètres société.",
    }


def _copy_logo_file_to_assets(db: Session, media_id: Optional[int]) -> list:
    """Copie fichier logo vers assets/ et frontend/ pour ReportLab."""
    if not media_id:
        return []
    from app.services.cms_service import CMS_MEDIA_ROOT

    m = db.query(CmsMedia).filter(CmsMedia.id == media_id).first()
    if not m:
        return []
    src = CMS_MEDIA_ROOT / m.file_path
    if not src.is_file():
        return []
    updated = []
    ASSETS_LOGO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, ASSETS_LOGO)
    updated.append(str(ASSETS_LOGO))
    FRONTEND_LOGO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, FRONTEND_LOGO)
    updated.append(str(FRONTEND_LOGO))
    return updated
