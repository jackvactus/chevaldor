"""Endpoints CMS avancés — dashboard, identité, médiathèque, bannières."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models_cms import CmsBanner, CmsMedia, CmsPage, CmsPageVersion, CmsSiteSettings
from app.routers.cms import _require_cms_admin, _require_cms_write
from app.services.audit_log import log_audit
from app.services.cms_service import (
    _now,
    _parse_json,
    default_dashboard_content,
    default_login_content,
    default_site_settings,
    ensure_cms_seeded,
)
from app.services.cms_identity_service import (
    LOGO_SLOTS,
    apply_identity_globally,
    get_identity_bundle,
    set_logo_slot,
)
from app.services.cms_media_service import (
    media_to_dict,
    save_upload,
    scan_media_usages,
    storage_stats,
)

router = APIRouter(prefix="/api/cms", tags=["cms-admin-ext"])


@router.get("/dashboard")
def cms_dashboard(db: Session = Depends(get_db), _: User = Depends(_require_cms_admin)):
    ensure_cms_seeded(db)
    stats = storage_stats(db)
    pages = db.query(CmsPage).count()
    published = db.query(CmsPage).filter(CmsPage.status == "published").count()
    banners = db.query(CmsBanner).count()
    recent_media = (
        db.query(CmsMedia)
        .filter(CmsMedia.archived == False)
        .order_by(CmsMedia.id.desc())
        .limit(8)
        .all()
    )
    recent_pages = (
        db.query(CmsPage)
        .order_by(CmsPage.updated_at.desc())
        .limit(8)
        .all()
    )
    return {
        "pages_total": pages,
        "pages_published": published,
        "banners_total": banners,
        "storage": stats,
        "recent_media": [media_to_dict(m) for m in recent_media],
        "recent_pages": [
            {"id": p.id, "slug": p.slug, "title": p.title, "status": p.status, "updated_at": p.updated_at}
            for p in recent_pages
        ],
    }


@router.get("/identity")
def get_identity(draft: bool = True, db: Session = Depends(get_db), _: User = Depends(_require_cms_admin)):
    ensure_cms_seeded(db)
    return {
        "slots": [{"key": k, "label": l, "hint": h} for k, l, h in LOGO_SLOTS],
        "identity": get_identity_bundle(db, draft=draft),
    }


class IdentityDraftIn(BaseModel):
    footer_text: Optional[str] = None
    logos: dict = {}
    dashboard_content: dict = {}
    login_content: dict = {}
    pdf_settings: dict = {}


class DashboardContentIn(BaseModel):
    dashboard_content: dict = {}
    login_content: dict = {}
    publish: bool = False


@router.put("/identity/draft")
def save_identity_draft(
    body: IdentityDraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    draft = _parse_json(row.draft_json or row.settings_json, {})
    if body.footer_text is not None:
        draft["footer_text"] = body.footer_text
    if body.logos:
        draft.setdefault("logos", {}).update(body.logos)
    if body.pdf_settings:
        draft["pdf_settings"] = {**draft.get("pdf_settings", default_site_settings().get("pdf_settings", {})), **body.pdf_settings}
    if body.dashboard_content:
        draft["dashboard_content"] = {**draft.get("dashboard_content", {}), **body.dashboard_content}
    if body.login_content:
        draft["login_content"] = {**draft.get("login_content", {}), **body.login_content}
    history = draft.setdefault("_history", [])
    history.append({
        "at": _now(),
        "by": user.email,
        "type": "identity_draft",
        "detail": "Brouillon identité / contenus",
    })
    draft["_history"] = history[-30:]
    row.draft_json = json.dumps(draft, ensure_ascii=False)
    row.updated_at = _now()
    row.updated_by = user.id
    db.commit()
    return get_identity_bundle(db, draft=True)


@router.post("/identity/slot/{slot}/upload")
async def upload_logo_slot(
    slot: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    try:
        media = await save_upload(
            db, file, category="logos", folder="logos", user_id=user.id, user_email=user.email,
        )
        entry = set_logo_slot(db, slot, media.id)
        log_audit(
            db, "update", "cms", "identity", 1,
            detail=f"Logo {slot}",
            user_id=user.id, user_email=user.email,
            ip=request.client.host if request.client else "",
            new_value=json.dumps(entry),
        )
        return {
            "ok": True,
            "slot": slot,
            "logo": entry,
            "media": media_to_dict(media),
            "asset_version": entry.get("asset_version"),
            "auto_synced": entry.get("auto_synced", False),
            "message": "Logo appliqué immédiatement dans l'ERP, les PDF et le site." if entry.get("auto_synced") else "",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/identity/slot/{slot}/media/{media_id}")
def assign_logo_from_library(
    slot: str,
    media_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    try:
        entry = set_logo_slot(db, slot, media_id)
        return {
            "ok": True,
            "slot": slot,
            "logo": entry,
            "asset_version": entry.get("asset_version"),
            "auto_synced": entry.get("auto_synced", False),
            "message": "Logo appliqué immédiatement dans l'ERP, les PDF et le site." if entry.get("auto_synced") else "",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/identity/apply")
def apply_identity(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    result = apply_identity_globally(db, user.id)
    log_audit(
        db, "publish", "cms", "identity", 1,
        detail=result.get("message", ""),
        user_id=user.id, user_email=user.email,
        ip=request.client.host if request.client else "",
    )
    return result


@router.get("/media/{media_id}/usages")
def media_usages(media_id: int, db: Session = Depends(get_db), _: User = Depends(_require_cms_admin)):
    return scan_media_usages(db, media_id)


class MediaUpdateIn(BaseModel):
    display_name: str = ""
    alt_text: str = ""
    category: str = ""
    folder: str = ""


@router.patch("/media/{media_id}")
def update_media_meta(
    media_id: int,
    body: MediaUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    row = db.query(CmsMedia).filter(CmsMedia.id == media_id).first()
    if not row:
        raise HTTPException(404)
    if body.display_name:
        row.display_name = body.display_name[:200]
        row.original_name = body.display_name[:200]
    if body.alt_text is not None:
        row.alt_text = body.alt_text[:200]
    if body.category:
        row.category = body.category[:40]
    if body.folder:
        row.folder = body.folder[:80]
    db.commit()
    return media_to_dict(row)


@router.post("/media/{media_id}/replace")
async def replace_media_file(
    media_id: int,
    request: Request,
    file: UploadFile = File(...),
    propagate: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    old = db.query(CmsMedia).filter(CmsMedia.id == media_id).first()
    if not old:
        raise HTTPException(404)
    from app.services.cms_media_service import media_public_url, propagate_url_swap

    media = await save_upload(
        db, file, category=old.category, folder=old.folder or old.category,
        replace_media_id=media_id, user_id=user.id, user_email=user.email,
    )
    updated_places = 1 if propagate else 0
    db.commit()
    log_audit(db, "update", "cms", "media", media_id, detail=f"Remplacement ({updated_places} refs)",
              user_id=user.id, user_email=user.email,
              ip=request.client.host if request.client else "")
    return {"ok": True, "media": media_to_dict(media), "references_updated": updated_places}


# ---------- Bannières ----------


class BannerIn(BaseModel):
    title: str = ""
    locale: str = "fr"
    image_media_id: Optional[int] = None
    link_url: str = ""
    link_label: str = ""
    is_active: bool = True
    sort_order: int = 0
    start_at: str = ""
    end_at: str = ""
    status: str = "draft"


@router.get("/banners")
def list_banners(locale: str = "fr", db: Session = Depends(get_db), _: User = Depends(_require_cms_admin)):
    rows = db.query(CmsBanner).filter(CmsBanner.locale == locale).order_by(CmsBanner.sort_order).all()
    out = []
    for b in rows:
        img = None
        if b.image_media_id:
            m = db.query(CmsMedia).filter(CmsMedia.id == b.image_media_id).first()
            if m:
                img = media_to_dict(m)
        out.append({
            "id": b.id,
            "title": b.title,
            "locale": b.locale,
            "image": img,
            "image_media_id": b.image_media_id,
            "link_url": b.link_url,
            "link_label": b.link_label,
            "is_active": b.is_active,
            "sort_order": b.sort_order,
            "start_at": b.start_at,
            "end_at": b.end_at,
            "status": b.status,
            "updated_at": b.updated_at,
        })
    return out


@router.post("/banners")
def create_banner(body: BannerIn, db: Session = Depends(get_db), user: User = Depends(_require_cms_write)):
    row = CmsBanner(**body.model_dump(), updated_at=_now(), updated_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


@router.put("/banners/{banner_id}")
def update_banner(
    banner_id: int,
    body: BannerIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    row = db.query(CmsBanner).filter(CmsBanner.id == banner_id).first()
    if not row:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    row.updated_at = _now()
    row.updated_by = user.id
    db.commit()
    return {"ok": True}


@router.delete("/banners/{banner_id}")
def delete_banner(banner_id: int, db: Session = Depends(get_db), user: User = Depends(_require_cms_write)):
    row = db.query(CmsBanner).filter(CmsBanner.id == banner_id).first()
    if not row:
        raise HTTPException(404)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/dashboard-content")
def get_dashboard_content(
    draft: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(_require_cms_admin),
):
    ensure_cms_seeded(db)
    bundle = get_identity_bundle(db, draft=draft)
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    raw = _parse_json(
        (row.draft_json if draft and row.draft_json else None) or row.settings_json,
        default_site_settings(),
    )
    return {
        "dashboard_content": bundle.get("dashboard_content") or raw.get("dashboard_content") or default_dashboard_content(),
        "login_content": bundle.get("login_content") or raw.get("login_content") or default_login_content(),
        "history": raw.get("_history", [])[-15:],
        "updated_at": row.updated_at if row else "",
    }


@router.put("/dashboard-content")
def save_dashboard_content(
    body: DashboardContentIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    draft = _parse_json(row.draft_json or row.settings_json, default_site_settings())
    if body.dashboard_content:
        draft["dashboard_content"] = {**draft.get("dashboard_content", default_dashboard_content()), **body.dashboard_content}
    if body.login_content:
        draft["login_content"] = {**draft.get("login_content", default_login_content()), **body.login_content}
    history = draft.setdefault("_history", [])
    history.append({
        "at": _now(),
        "by": user.email,
        "type": "dashboard_content",
        "detail": "Contenus ERP / login",
    })
    draft["_history"] = history[-30:]
    row.draft_json = json.dumps(draft, ensure_ascii=False)
    row.updated_at = _now()
    row.updated_by = user.id
    if body.publish:
        row.settings_json = json.dumps(draft, ensure_ascii=False)
    db.commit()
    log_audit(
        db, "update", "cms", "dashboard_content", 1,
        detail="Contenus dashboard/login",
        user_id=user.id, user_email=user.email,
        ip=request.client.host if request.client else "",
    )
    bundle = get_identity_bundle(db, draft=True)
    raw = _parse_json(row.draft_json or row.settings_json, default_site_settings())
    return {
        "dashboard_content": raw.get("dashboard_content") or default_dashboard_content(),
        "login_content": raw.get("login_content") or default_login_content(),
        "history": raw.get("_history", [])[-15:],
        "updated_at": row.updated_at,
        "asset_version": bundle.get("asset_version", ""),
    }
