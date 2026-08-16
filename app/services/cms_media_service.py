"""Médiathèque CMS — upload, optimisation, remplacement global."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models_cms import CmsBanner, CmsDynamicSection, CmsMedia, CmsPage, CmsSiteSettings
from app.services.cms_service import CMS_MEDIA_ROOT, _now, _parse_json, media_public_url, safe_filename
from app.upload_limits import MAX_UPLOAD_BYTES, read_bounded

ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
ALLOWED_VIDEO = {".mp4", ".webm", ".mov"}
ALLOWED_DOC = {".pdf", ".docx", ".xlsx", ".doc", ".xls"}


def _ext(name: str) -> str:
    return Path(name).suffix.lower()


def detect_kind(filename: str, mime: str) -> str:
    ext = _ext(filename)
    if ext in ALLOWED_IMAGE or (mime or "").startswith("image/"):
        return "image"
    if ext in ALLOWED_VIDEO or (mime or "").startswith("video/"):
        return "video"
    if ext in ALLOWED_DOC or mime in ("application/pdf",):
        return "document"
    return "other"


def process_image_file(dest: Path, *, max_side: int = 2000) -> Tuple[int, int, Optional[str]]:
    """Compression + WebP. Retourne (width, height, webp_filename)."""
    try:
        from PIL import Image
    except ImportError:
        return 0, 0, None
    try:
        with Image.open(dest) as im:
            im = im.convert("RGBA") if im.mode in ("RGBA", "P") else im.convert("RGB")
            w, h = im.size
            if max(w, h) > max_side:
                im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                w, h = im.size
                if dest.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    im.save(dest, optimize=True, quality=88)
            webp_path = dest.with_suffix(".webp")
            im.save(webp_path, "WEBP", quality=85, method=4)
            return w, h, webp_path.name
    except Exception:
        return 0, 0, None


async def save_upload(
    db: Session,
    file: UploadFile,
    *,
    category: str = "general",
    folder: str = "",
    alt_text: str = "",
    display_name: str = "",
    user_id: int = 0,
    user_email: str = "",
    replace_media_id: Optional[int] = None,
) -> CmsMedia:
    if not file.filename:
        raise HTTPException(400, "Fichier requis")
    ext = _ext(file.filename)
    kind = detect_kind(file.filename, file.content_type or "")
    if kind == "other":
        raise HTTPException(400, "Type de fichier non supporté")

    sub = (folder or category or "general").strip().replace("..", "")
    dest_dir = CMS_MEDIA_ROOT / sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_filename(file.filename)
    dest_name = f"{_now().replace(':', '').replace('-', '')}_{safe}"
    dest_path = dest_dir / dest_name

    contents = await read_bounded(file, MAX_UPLOAD_BYTES)
    with dest_path.open("wb") as out:
        out.write(contents)

    w, h, webp_name = (0, 0, None)
    if kind == "image" and ext != ".svg":
        w, h, webp_name = process_image_file(dest_path)

    rel = f"{sub}/{dest_name}"
    webp_rel = f"{sub}/{webp_name}" if webp_name else ""

    if replace_media_id:
        old = db.query(CmsMedia).filter(CmsMedia.id == replace_media_id).first()
        if not old:
            raise HTTPException(404, "Média à remplacer introuvable")
        old_url = media_public_url(old.file_path)
        new_url = media_public_url(rel)
        w, h, webp_name = (0, 0, None)
        if kind == "image" and ext != ".svg":
            w, h, webp_name = process_image_file(dest_path)
        old.filename = dest_name
        old.original_name = display_name or file.filename
        old.file_path = rel
        old.mime_type = file.content_type or "application/octet-stream"
        old.category = category[:40] or old.category
        old.alt_text = alt_text[:200] or old.alt_text
        old.folder = sub
        old.size_bytes = dest_path.stat().st_size
        old.width = w
        old.height = h
        old.webp_path = f"{sub}/{webp_name}" if webp_name else ""
        old.archived = False
        if display_name:
            old.display_name = display_name[:200]
        db.flush()
        propagate_url_swap(db, old_url, new_url, old.id, old.id)
        db.commit()
        db.refresh(old)
        return old

    row = CmsMedia(
        filename=dest_name,
        original_name=display_name or file.filename,
        file_path=rel,
        mime_type=file.content_type or "application/octet-stream",
        category=category[:40] if category else "general",
        alt_text=alt_text[:200],
        folder=sub,
        size_bytes=dest_path.stat().st_size,
        created_at=_now(),
        created_by=user_id,
        created_by_email=user_email or "",
    )
    if hasattr(row, "width"):
        row.width = w
        row.height = h
    if hasattr(row, "webp_path") and webp_rel:
        row.webp_path = webp_rel
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def media_to_dict(m: CmsMedia) -> dict:
    url = media_public_url(m.file_path)
    webp = media_public_url(getattr(m, "webp_path", "") or "") if getattr(m, "webp_path", None) else ""
    return {
        "id": m.id,
        "filename": m.filename,
        "original_name": m.original_name,
        "display_name": getattr(m, "display_name", None) or m.original_name,
        "url": url,
        "webp_url": webp or url,
        "category": m.category,
        "mime_type": m.mime_type,
        "alt_text": m.alt_text,
        "folder": m.folder,
        "size_bytes": m.size_bytes,
        "width": getattr(m, "width", 0) or 0,
        "height": getattr(m, "height", 0) or 0,
        "archived": m.archived,
        "created_at": m.created_at,
        "kind": detect_kind(m.original_name or m.filename, m.mime_type),
    }


def scan_media_usages(db: Session, media_id: int) -> list:
    m = db.query(CmsMedia).filter(CmsMedia.id == media_id).first()
    if not m:
        return []
    url = media_public_url(m.file_path)
    usages = []

    def _scan_json(label: str, obj_id: int, raw: str, field: str):
        if not raw:
            return
        if str(media_id) in raw or url in raw:
            usages.append({"type": label, "id": obj_id, "field": field})

    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    if row:
        _scan_json("site_settings", 1, row.settings_json or "", "settings_json")
        _scan_json("site_settings", 1, row.draft_json or "", "draft_json")

    for p in db.query(CmsPage).all():
        _scan_json("page", p.id, p.content_json or "", "content")
        _scan_json("page", p.id, p.draft_json or "", "draft")
        if p.og_image_id == media_id:
            usages.append({"type": "page", "id": p.id, "field": "og_image_id"})

    for s in db.query(CmsDynamicSection).all():
        _scan_json("section", s.id, s.content_json or "", "content")

    if hasattr(CmsBanner, "__tablename__"):
        for b in db.query(CmsBanner).filter(CmsBanner.image_media_id == media_id).all():
            usages.append({"type": "banner", "id": b.id, "field": "image_media_id"})

    return usages


def propagate_url_swap(
    db: Session,
    old_url: str,
    new_url: str,
    old_media_id: int,
    new_media_id: Optional[int],
) -> int:
    """Remplace ancienne URL / media_id dans tout le CMS. Retourne nb de zones touchées."""
    count = 0
    nid = new_media_id

    def _replace_in_text(text: str) -> str:
        if not text:
            return text
        out = text.replace(old_url, new_url)
        if old_media_id and nid:
            out = out.replace(f'"media_id": {old_media_id}', f'"media_id": {nid}')
            out = out.replace(f'"image_id": {old_media_id}', f'"image_id": {nid}')
        return out

    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    if row:
        for attr in ("settings_json", "draft_json"):
            raw = getattr(row, attr) or ""
            if old_url in raw or (old_media_id and str(old_media_id) in raw):
                setattr(row, attr, _replace_in_text(raw))
                count += 1

    for p in db.query(CmsPage).all():
        changed = False
        for attr in ("content_json", "draft_json"):
            raw = getattr(p, attr) or ""
            if old_url in raw or (old_media_id and str(old_media_id) in raw):
                setattr(p, attr, _replace_in_text(raw))
                changed = True
        if p.og_image_id == old_media_id and nid:
            p.og_image_id = nid
            changed = True
        if changed:
            count += 1

    for s in db.query(CmsDynamicSection).all():
        for attr in ("content_json", "draft_json"):
            raw = getattr(s, attr) or ""
            if old_url in raw or (old_media_id and str(old_media_id) in raw):
                setattr(s, attr, _replace_in_text(raw))
                count += 1

    try:
        for b in db.query(CmsBanner).filter(CmsBanner.image_media_id == old_media_id).all():
            if nid:
                b.image_media_id = nid
                count += 1
    except Exception:
        pass

    if nid:
        try:
            from app.services.cms_identity_service import resync_logo_assets_for_media
            resync_logo_assets_for_media(db, nid)
        except Exception:
            pass
    return count


def storage_stats(db: Session) -> dict:
    rows = db.query(CmsMedia).filter(CmsMedia.archived == False).all()
    total = sum(r.size_bytes or 0 for r in rows)
    images = sum(1 for r in rows if detect_kind(r.filename, r.mime_type) == "image")
    videos = sum(1 for r in rows if detect_kind(r.filename, r.mime_type) == "video")
    docs = sum(1 for r in rows if detect_kind(r.filename, r.mime_type) == "document")
    return {
        "total_bytes": total,
        "total_mb": round(total / (1024 * 1024), 2),
        "files": len(rows),
        "images": images,
        "videos": videos,
        "documents": docs,
    }
