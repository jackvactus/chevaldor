"""API CMS site vitrine — public + administration."""
from __future__ import annotations

import json
import shutil
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_permission
from app.database import get_db
from app.models import User
from app.models_cms import CmsBanner, CmsDynamicSection, CmsMedia, CmsPage, CmsPageVersion, CmsSiteSettings
from app.services.audit_log import log_audit
from app.services.cms_service import (
    BLOCK_TYPES,
    CMS_MEDIA_ROOT,
    PAGE_SLUGS,
    SECTION_TYPES,
    _now,
    _parse_json,
    default_page_content,
    default_site_settings,
    ensure_cms_seeded,
    get_page_for_public,
    get_published_settings,
    media_public_url,
    page_payload,
    publish_page,
    restore_version,
    safe_filename,
    save_version,
)

public_router = APIRouter(prefix="/api/public/cms", tags=["cms-public"])
admin_router = APIRouter(prefix="/api/cms", tags=["cms-admin"])


def _require_cms_admin(user: User = Depends(get_current_user)) -> User:
    """Site vitrine : administrateurs uniquement."""
    if user.role != "admin":
        raise HTTPException(403, "Module « Contenu du site » réservé aux administrateurs")
    return user


def _require_cms_write(user: User = Depends(_require_cms_admin)) -> User:
    return user


# ---------- Public ----------


@public_router.get("/settings")
def public_settings(db: Session = Depends(get_db)):
    ensure_cms_seeded(db)
    return get_published_settings(db)


@public_router.get("/pages")
def public_pages_list(locale: str = "fr", db: Session = Depends(get_db)):
    ensure_cms_seeded(db)
    rows = (
        db.query(CmsPage)
        .filter(CmsPage.locale == locale, CmsPage.status == "published", CmsPage.is_enabled == True)
        .order_by(CmsPage.sort_order)
        .all()
    )
    return [
        {
            "slug": p.slug,
            "title": p.title,
            "seo_slug": p.seo_slug or p.slug,
            "url": "/" if p.slug == "home" else f"/site/{p.seo_slug or p.slug}",
        }
        for p in rows
    ]


@public_router.get("/pages/{slug}")
def public_page(slug: str, locale: str = "fr", db: Session = Depends(get_db)):
    ensure_cms_seeded(db)
    page = get_page_for_public(db, slug, locale)
    if not page:
        raise HTTPException(404, "Page introuvable ou non publiée")
    out = page_payload(page)
    if page.og_image_id:
        m = db.query(CmsMedia).filter(CmsMedia.id == page.og_image_id).first()
        if m:
            out["seo"]["og_image_url"] = media_public_url(m.file_path)
    return out


@public_router.get("/home")
def public_home(locale: str = "fr", db: Session = Depends(get_db)):
    return public_page("home", locale, db)


@public_router.get("/banners")
def public_banners(locale: str = "fr", db: Session = Depends(get_db)):
    from app.services.cms_media_service import media_to_dict

    ensure_cms_seeded(db)
    rows = (
        db.query(CmsBanner)
        .filter(
            CmsBanner.locale == locale,
            CmsBanner.status == "published",
            CmsBanner.is_active == True,
        )
        .order_by(CmsBanner.sort_order)
        .all()
    )
    out = []
    for b in rows:
        img = None
        if b.image_media_id:
            m = db.query(CmsMedia).filter(CmsMedia.id == b.image_media_id).first()
            if m:
                img = media_to_dict(m)
        out.append({
            "title": b.title,
            "image": img,
            "link_url": b.link_url,
            "link_label": b.link_label,
        })
    return out


@public_router.get("/sections")
def public_sections(
    section_type: Optional[str] = None,
    locale: str = "fr",
    db: Session = Depends(get_db),
):
    ensure_cms_seeded(db)
    q = db.query(CmsDynamicSection).filter(
        CmsDynamicSection.locale == locale,
        CmsDynamicSection.status == "published",
    )
    if section_type:
        q = q.filter(CmsDynamicSection.section_type == section_type)
    rows = q.order_by(CmsDynamicSection.sort_order).all()
    return [
        {
            "id": r.id,
            "type": r.section_type,
            "title": r.title,
            "content": _parse_json(r.content_json, {}),
        }
        for r in rows
    ]


# ---------- Admin schemas ----------


class PageSaveIn(BaseModel):
    title: str = ""
    draft_json: dict = Field(default_factory=dict)
    seo_title: str = ""
    seo_description: str = ""
    seo_keywords: str = ""
    seo_slug: str = ""
    og_image_id: Optional[int] = None
    is_enabled: bool = True


class SiteSettingsIn(BaseModel):
    settings: dict = Field(default_factory=dict)
    publish: bool = False


class SectionSaveIn(BaseModel):
    title: str = ""
    section_type: str
    locale: str = "fr"
    content: dict = Field(default_factory=dict)
    status: str = "draft"


class BlockReorderIn(BaseModel):
    block_ids: List[str]


# ---------- Admin: settings & meta ----------


@admin_router.get("/meta")
def cms_meta(_: User = Depends(_require_cms_admin)):
    return {
        "page_slugs": [{"slug": s, "title": t, "order": o} for s, t, o in PAGE_SLUGS],
        "block_types": BLOCK_TYPES,
        "section_types": SECTION_TYPES,
        "locales": ["fr", "en", "es"],
        "media_categories": ["logos", "banners", "vitrine", "products", "news", "documents", "general"],
    }


@admin_router.get("/settings")
def get_settings(db: Session = Depends(get_db), _: User = Depends(_require_cms_admin)):
    ensure_cms_seeded(db)
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    return {
        "published": _parse_json(row.settings_json, default_site_settings()),
        "draft": _parse_json(row.draft_json or row.settings_json, default_site_settings()),
        "updated_at": row.updated_at,
    }


@admin_router.put("/settings")
def save_settings(
    body: SiteSettingsIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    ensure_cms_seeded(db)
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    old = row.settings_json
    row.draft_json = json.dumps(body.settings, ensure_ascii=False)
    if body.publish:
        row.settings_json = row.draft_json
        row.updated_at = _now()
        row.updated_by = user.id
        log_audit(
            db, "publish", "cms", "site_settings", 1,
            detail="Publication paramètres site",
            user_id=user.id, user_email=user.email,
            ip=request.client.host if request.client else "",
            old_value=old[:2000], new_value=row.settings_json[:2000],
        )
    else:
        row.updated_at = _now()
        row.updated_by = user.id
    db.commit()
    return {"ok": True, "published": body.publish}


# ---------- Admin: pages ----------


@admin_router.get("/pages")
def list_pages_admin(
    locale: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(_require_cms_admin),
):
    ensure_cms_seeded(db)
    q = db.query(CmsPage).order_by(CmsPage.sort_order, CmsPage.slug)
    if locale:
        q = q.filter(CmsPage.locale == locale)
    return [
        {
            "id": p.id,
            "slug": p.slug,
            "title": p.title,
            "locale": p.locale,
            "status": p.status,
            "is_enabled": p.is_enabled,
            "updated_at": p.updated_at,
            "published_at": p.published_at,
        }
        for p in q.all()
    ]


@admin_router.get("/pages/{page_id}")
def get_page_admin(
    page_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_cms_admin),
):
    page = db.query(CmsPage).filter(CmsPage.id == page_id).first()
    if not page:
        raise HTTPException(404)
    pub = page_payload(page, use_draft=False)
    draft = page_payload(page, use_draft=True)
    return {"page": pub, "draft": draft}


@admin_router.put("/pages/{page_id}")
def save_page_draft(
    page_id: int,
    body: PageSaveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    page = db.query(CmsPage).filter(CmsPage.id == page_id).first()
    if not page:
        raise HTTPException(404)
    old = page.draft_json
    page.title = body.title or page.title
    page.draft_json = json.dumps(body.draft_json, ensure_ascii=False)
    page.seo_title = body.seo_title
    page.seo_description = body.seo_description
    page.seo_keywords = body.seo_keywords
    page.seo_slug = body.seo_slug
    page.og_image_id = body.og_image_id
    page.is_enabled = body.is_enabled
    page.updated_at = _now()
    page.updated_by = user.id
    page.updated_by_email = user.email
    log_audit(
        db, "update", "cms", "page", page.id,
        detail=f"Brouillon page {page.slug}",
        user_id=user.id, user_email=user.email,
        ip=request.client.host if request.client else "",
        old_value=old[:1500] if old else "",
        new_value=page.draft_json[:1500],
    )
    db.commit()
    return {"ok": True, "page": page_payload(page, use_draft=True)}


@admin_router.post("/pages/{page_id}/publish")
def publish_page_endpoint(
    page_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    page = db.query(CmsPage).filter(CmsPage.id == page_id).first()
    if not page:
        raise HTTPException(404)
    old = page.content_json
    publish_page(db, page, user.id, user.email)
    log_audit(
        db, "publish", "cms", "page", page.id,
        detail=f"Publication {page.slug}/{page.locale}",
        user_id=user.id, user_email=user.email,
        ip=request.client.host if request.client else "",
        old_value=old[:1500], new_value=page.content_json[:1500],
    )
    db.commit()
    return {"ok": True, "page": page_payload(page)}


@admin_router.get("/pages/{page_id}/preview")
def preview_page(
    page_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_cms_admin),
):
    page = db.query(CmsPage).filter(CmsPage.id == page_id).first()
    if not page:
        raise HTTPException(404)
    return page_payload(page, use_draft=True)


@admin_router.get("/pages/{page_id}/versions")
def list_versions(
    page_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(_require_cms_admin),
):
    rows = (
        db.query(CmsPageVersion)
        .filter(CmsPageVersion.page_id == page_id)
        .order_by(CmsPageVersion.version_no.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": v.id,
            "version_no": v.version_no,
            "status": v.status,
            "created_at": v.created_at,
            "created_by_email": v.created_by_email,
        }
        for v in rows
    ]


@admin_router.post("/pages/{page_id}/versions/{version_id}/restore")
def restore_page_version(
    page_id: int,
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    page = db.query(CmsPage).filter(CmsPage.id == page_id).first()
    ver = db.query(CmsPageVersion).filter(
        CmsPageVersion.id == version_id, CmsPageVersion.page_id == page_id
    ).first()
    if not page or not ver:
        raise HTTPException(404)
    restore_version(db, page, ver)
    page.updated_by = user.id
    page.updated_by_email = user.email
    log_audit(
        db, "restore", "cms", "page", page.id,
        detail=f"Restauration version {ver.version_no}",
        user_id=user.id, user_email=user.email,
        ip=request.client.host if request.client else "",
    )
    db.commit()
    return {"ok": True, "draft": page_payload(page, use_draft=True)}


# ---------- Admin: media ----------


@admin_router.get("/media")
def list_media(
    q: str = "",
    category: str = "",
    kind: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(_require_cms_admin),
):
    from app.services.cms_media_service import detect_kind, media_to_dict

    query = db.query(CmsMedia).filter(CmsMedia.archived == False)
    if category:
        query = query.filter(CmsMedia.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (CmsMedia.original_name.like(like))
            | (CmsMedia.filename.like(like))
            | (CmsMedia.display_name.like(like))
        )
    rows = query.order_by(CmsMedia.id.desc()).limit(300).all()
    if kind:
        rows = [m for m in rows if detect_kind(m.filename, m.mime_type) == kind]
    return [media_to_dict(m) for m in rows]


@admin_router.post("/media/upload")
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form("general"),
    folder: str = Form(""),
    alt_text: str = Form(""),
    display_name: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    from app.services.cms_media_service import media_to_dict, save_upload

    media = await save_upload(
        db, file, category=category, folder=folder, alt_text=alt_text,
        display_name=display_name, user_id=user.id, user_email=user.email,
    )
    log_audit(
        db, "create", "cms", "media", media.id,
        detail=f"Upload {file.filename}",
        user_id=user.id, user_email=user.email,
        ip=request.client.host if request.client else "",
        new_value=media.file_path,
    )
    return media_to_dict(media)


@admin_router.delete("/media/{media_id}")
def delete_media(
    media_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    row = db.query(CmsMedia).filter(CmsMedia.id == media_id).first()
    if not row:
        raise HTTPException(404)
    row.archived = True
    log_audit(
        db, "archive", "cms", "media", media_id,
        detail=row.file_path,
        user_id=user.id, user_email=user.email,
        ip=request.client.host if request.client else "",
    )
    db.commit()
    return {"ok": True}


# ---------- Admin: dynamic sections ----------


@admin_router.get("/sections")
def list_sections_admin(
    locale: str = "fr",
    db: Session = Depends(get_db),
    _: User = Depends(_require_cms_admin),
):
    rows = (
        db.query(CmsDynamicSection)
        .filter(CmsDynamicSection.locale == locale)
        .order_by(CmsDynamicSection.section_type, CmsDynamicSection.sort_order)
        .all()
    )
    return [
        {
            "id": r.id,
            "section_type": r.section_type,
            "title": r.title,
            "status": r.status,
            "locale": r.locale,
            "content": _parse_json(r.draft_json or r.content_json, {}),
        }
        for r in rows
    ]


@admin_router.post("/sections")
def save_section(
    body: SectionSaveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    if body.section_type not in SECTION_TYPES:
        raise HTTPException(400, f"Type invalide. Choix : {SECTION_TYPES}")
    payload = json.dumps(body.content, ensure_ascii=False)
    row = CmsDynamicSection(
        section_type=body.section_type,
        locale=body.locale,
        title=body.title,
        status=body.status,
        content_json=payload if body.status == "published" else "",
        draft_json=payload,
        updated_at=_now(),
        updated_by=user.id,
    )
    db.add(row)
    log_audit(db, "create", "cms", "section", None, detail=body.section_type,
              user_id=user.id, user_email=user.email,
              ip=request.client.host if request.client else "")
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


@admin_router.put("/sections/{section_id}")
def update_section(
    section_id: int,
    body: SectionSaveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cms_write),
):
    row = db.query(CmsDynamicSection).filter(CmsDynamicSection.id == section_id).first()
    if not row:
        raise HTTPException(404)
    old = row.content_json
    payload = json.dumps(body.content, ensure_ascii=False)
    row.title = body.title
    row.draft_json = payload
    if body.status == "published":
        row.content_json = payload
        row.status = "published"
    else:
        row.status = "draft"
    row.updated_at = _now()
    row.updated_by = user.id
    log_audit(db, "update", "cms", "section", section_id,
              user_id=user.id, user_email=user.email,
              ip=request.client.host if request.client else "",
              old_value=old[:1000], new_value=payload[:1000])
    db.commit()
    return {"ok": True}
