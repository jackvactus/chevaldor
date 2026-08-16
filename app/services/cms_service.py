"""Service CMS site vitrine — seed, publication, versions."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models_cms import CmsDynamicSection, CmsMedia, CmsPage, CmsPageVersion, CmsSiteSettings

CMS_MEDIA_ROOT = Path(__file__).resolve().parents[2] / "data" / "cms" / "media"
CMS_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_LOCALES = ["fr", "en", "es"]

PAGE_SLUGS = [
    ("home", "Accueil", 0),
    ("about", "À propos", 10),
    ("services", "Services", 20),
    ("products", "Produits", 30),
    ("pricing", "Tarifs", 40),
    ("blog", "Blog", 50),
    ("faq", "FAQ", 60),
    ("contact", "Contact", 70),
    ("privacy", "Politique de confidentialité", 80),
    ("terms", "Conditions d'utilisation", 90),
]

BLOCK_TYPES = [
    "hero", "text", "features", "stats", "testimonials", "partners",
    "faq", "gallery", "banner", "video", "cta", "team",
]

SECTION_TYPES = ["testimonial", "partner", "stat", "feature", "team", "project", "faq"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_json(raw: str, default: Any = None) -> Any:
    if not raw:
        return default if default is not None else {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default if default is not None else {}


def default_home_blocks() -> list:
    return [
        {
            "id": "hero-1",
            "type": "hero",
            "data": {
                "title": "Votre entreprise, pilotée en un seul endroit",
                "subtitle": "ERP Peya Company pour le Togo",
                "body": (
                    "Clients, pipeline commercial, devis et factures, projets, stock, "
                    "formation et comptabilité — toutes vos données en Franc CFA (XOF), "
                    "enregistrées de façon sécurisée."
                ),
                "cta_primary_label": "Se connecter à l'ERP",
                "cta_primary_url": "/login",
                "cta_secondary_label": "Découvrir les modules",
                "cta_secondary_url": "#fonctionnalites",
                "image_url": "/static/logo-peya.png",
                "video_url": "",
            },
        },
        {
            "id": "features-1",
            "type": "features",
            "data": {
                "title": "Une plateforme complète pour Peya Company",
                "items": [
                    {"icon": "◎", "title": "CRM & pipeline", "text": "Fiches clients 360°, opportunités, kanban par étapes."},
                    {"icon": "📄", "title": "Devis & factures", "text": "Lignes détaillées, TVA, export PDF, suivi des impayés."},
                    {"icon": "📊", "title": "Clientèle PC", "text": "Import Excel, tableau de bord matriciel, soldes cumulés."},
                    {"icon": "📦", "title": "Stock & projets", "text": "Mouvements entrée/sortie, seuils d'alerte, tâches projet."},
                    {"icon": "🎓", "title": "Formation", "text": "Sessions, stagiaires, Qualiopi, financeurs OPCO."},
                    {"icon": "🔒", "title": "Sécurité & rôles", "text": "Connexion sécurisée, utilisateurs et permissions."},
                ],
            },
        },
        {
            "id": "stats-1",
            "type": "stats",
            "data": {
                "title": "Peya Company · SARL · Lomé, Togo 🇹🇬",
                "items": [
                    {"value": "10+", "label": "modules métier"},
                    {"value": "100%", "label": "données en base"},
                    {"value": "FCFA", "label": "devise native"},
                ],
            },
        },
    ]


def default_dashboard_content() -> dict:
    return {
        "welcome_title": "Bienvenue, {name}",
        "welcome_subtitle": (
            "ERP multi-modules : CRM 360°, pipeline glisser-déposer, devis/factures avec lignes & PDF, "
            "stock, projets, formation, compta, clientèle PC."
        ),
        "banner_text": "",
        "announcement": "",
        "quick_links_title": "Accès rapide",
        "page_title": "Accueil",
    }


def default_login_content() -> dict:
    return {
        "title": "Espace professionnel",
        "subtitle": "Connectez-vous pour accéder à votre espace ERP",
        "hero_title": "Peya Company ERP",
        "hero_tagline": (
            "Pilotage intégré pour le commercial, les opérations, la formation et la finance — "
            "conçu pour les équipes exigeantes au Togo et en Afrique de l'Ouest."
        ),
        "features": [
            "Tableaux de bord et KPI en temps réel",
            "CRM, devis, factures et trésorerie unifiés",
            "Stock, projets et conformité comptable",
            "Sécurité renforcée et gestion des rôles",
        ],
        "badge": "🇹🇬 Togo · XOF · Multi-devises",
    }


def asset_version_token(updated_at: str = "") -> str:
    if not updated_at:
        return _now().replace(":", "").replace("-", "")[:14]
    return re.sub(r"[^0-9]", "", updated_at)[:14] or updated_at


def default_site_settings() -> dict:
    def _u(path: str) -> dict:
        return {"media_id": None, "url": path}

    return {
        "locales": DEFAULT_LOCALES,
        "default_locale": "fr",
        "logos": {
            "main": _u("/static/logo-peya.png"),
            "white": _u("/static/logo-peya.png"),
            "dark": _u("/static/logo-peya.png"),
            "favicon": _u("/favicon.ico"),
            "footer": _u("/static/logo-peya.png"),
            "pdf": _u("/static/logo-peya.png"),
            "email": _u("/static/logo-peya.png"),
            "institutional": _u("/static/logo-peya.png"),
        },
        "footer_text": "© Peya Company — Tous droits réservés",
        "pdf_settings": {
            "footer_legal": "Peya Company ERP — Document confidentiel",
            "header_subtitle": "",
            "show_signature": False,
            "show_stamp": False,
            "signature_slot": "institutional",
            "stamp_slot": "institutional",
        },
        "nav_links": [
            {"label": "Fonctionnalités", "url": "#fonctionnalites"},
            {"label": "Connexion", "url": "/login"},
        ],
        "dashboard_content": default_dashboard_content(),
        "login_content": default_login_content(),
    }


def resolve_settings_for_public(raw: dict, db: Session) -> dict:
    """URLs logos prêtes pour le site public."""
    from app.services.cms_identity_service import normalize_logos

    out = dict(raw)
    out["logos"] = {
        k: (v.get("url") or v.get("preview") or "")
        for k, v in normalize_logos(raw, db).items()
    }
    return out


def default_page_content(slug: str) -> dict:
    titles = {s: t for s, t, _ in PAGE_SLUGS}
    if slug == "home":
        return {"blocks": default_home_blocks()}
    title = titles.get(slug, slug.replace("-", " ").title())
    return {
        "blocks": [
            {
                "id": f"text-{slug}",
                "type": "text",
                "data": {
                    "title": title,
                    "body": f"Contenu de la page « {title} » — modifiable depuis l'ERP (Contenu du site).",
                },
            }
        ]
    }


def _ensure_default_logo_files() -> None:
    """Copie le logo assets vers frontend/static si absent (évite 404 avant premier apply)."""
    assets = Path(__file__).resolve().parents[2] / "assets" / "logo-peya.png"
    frontend = Path(__file__).resolve().parents[3] / "frontend" / "logo-peya.png"
    if assets.is_file() and not frontend.is_file():
        frontend.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(assets, frontend)


def ensure_cms_seeded(db: Session) -> None:
    _ensure_default_logo_files()
    if not db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first():
        db.add(CmsSiteSettings(
            id=1,
            settings_json=json.dumps(default_site_settings(), ensure_ascii=False),
            draft_json="",
            updated_at=_now(),
        ))
    for slug, title, order in PAGE_SLUGS:
        for locale in DEFAULT_LOCALES:
            key = f"{slug}:{locale}"
            exists = db.query(CmsPage).filter(CmsPage.slug == slug, CmsPage.locale == locale).first()
            if exists:
                continue
            content = default_page_content(slug)
            if locale != "fr":
                for b in content.get("blocks", []):
                    if b.get("type") == "text" and "data" in b:
                        b["data"]["body"] += f" ({locale.upper()})"
            payload = json.dumps(content, ensure_ascii=False)
            page = CmsPage(
                slug=slug,
                title=title,
                locale=locale,
                status="published" if slug == "home" and locale == "fr" else "draft",
                is_enabled=slug in ("home", "about", "services", "contact", "faq"),
                sort_order=order,
                seo_title=f"{title} — Peya Company",
                seo_description="Peya Company ERP — Togo",
                seo_slug=slug if slug != "home" else "",
                content_json=payload,
                draft_json=payload,
                published_at=_now() if slug == "home" and locale == "fr" else "",
                updated_at=_now(),
            )
            db.add(page)
    db.flush()
    if not db.query(CmsDynamicSection).first():
        _seed_dynamic_sections(db)
    db.commit()


def _seed_dynamic_sections(db: Session) -> None:
    samples = [
        ("testimonial", "Témoignages", {"items": [
            {"name": "Client A", "role": "PME Lomé", "text": "ERP simple et efficace pour notre équipe."},
        ]}),
        ("partner", "Partenaires", {"items": [
            {"name": "Partenaire 1", "logo_url": "/static/logo-peya.png"},
        ]}),
        ("faq", "FAQ", {"items": [
            {"q": "Comment accéder à l'ERP ?", "a": "Utilisez le bouton Connexion avec vos identifiants."},
        ]}),
    ]
    for i, (stype, title, content) in enumerate(samples):
        db.add(CmsDynamicSection(
            section_type=stype,
            locale="fr",
            title=title,
            status="published",
            sort_order=i,
            content_json=json.dumps(content, ensure_ascii=False),
            draft_json=json.dumps(content, ensure_ascii=False),
            updated_at=_now(),
        ))


def get_published_settings(db: Session) -> dict:
    row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    if not row:
        ensure_cms_seeded(db)
        row = db.query(CmsSiteSettings).filter(CmsSiteSettings.id == 1).first()
    raw = _parse_json(row.settings_json, default_site_settings())
    out = resolve_settings_for_public(raw, db)
    out["footer_text"] = raw.get("footer_text", "")
    out["nav_links"] = raw.get("nav_links", [])
    out["dashboard_content"] = raw.get("dashboard_content") or default_dashboard_content()
    out["login_content"] = raw.get("login_content") or default_login_content()
    out["updated_at"] = row.updated_at or ""
    out["asset_version"] = asset_version_token(row.updated_at or "")
    return out


def get_page_for_public(db: Session, slug: str, locale: str = "fr", *, preview: bool = False) -> Optional[CmsPage]:
    page = db.query(CmsPage).filter(CmsPage.slug == slug, CmsPage.locale == locale).first()
    if not page or not page.is_enabled:
        return None
    if preview:
        return page
    if page.status != "published":
        return None
    return page


def page_payload(page: CmsPage, *, use_draft: bool = False) -> dict:
    raw = page.draft_json if use_draft and page.draft_json else page.content_json
    content = _parse_json(raw, default_page_content(page.slug))
    og_url = ""
    if page.og_image_id:
        media = None  # filled by router if needed
    return {
        "id": page.id,
        "slug": page.slug,
        "title": page.title,
        "locale": page.locale,
        "status": page.status,
        "is_enabled": page.is_enabled,
        "seo": {
            "title": page.seo_title or page.title,
            "description": page.seo_description or "",
            "keywords": page.seo_keywords or "",
            "slug": page.seo_slug or page.slug,
            "og_image_id": page.og_image_id,
            "og_image_url": og_url,
        },
        "content": content,
        "published_at": page.published_at,
        "updated_at": page.updated_at,
    }


def save_version(db: Session, page: CmsPage, user_id: int, user_email: str, snapshot: dict) -> CmsPageVersion:
    last = (
        db.query(CmsPageVersion)
        .filter(CmsPageVersion.page_id == page.id)
        .order_by(CmsPageVersion.version_no.desc())
        .first()
    )
    vn = (last.version_no + 1) if last else 1
    row = CmsPageVersion(
        page_id=page.id,
        version_no=vn,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        status=page.status,
        created_at=_now(),
        created_by=user_id,
        created_by_email=user_email or "",
    )
    db.add(row)
    return row


def publish_page(db: Session, page: CmsPage, user_id: int, user_email: str) -> CmsPage:
    draft = _parse_json(page.draft_json or page.content_json, default_page_content(page.slug))
    page.content_json = json.dumps(draft, ensure_ascii=False)
    page.status = "published"
    page.published_at = _now()
    page.updated_at = _now()
    page.updated_by = user_id
    page.updated_by_email = user_email or ""
    save_version(db, page, user_id, user_email, {
        "content": draft,
        "seo_title": page.seo_title,
        "seo_description": page.seo_description,
        "title": page.title,
    })
    return page


def restore_version(db: Session, page: CmsPage, version: CmsPageVersion) -> CmsPage:
    snap = _parse_json(version.snapshot_json, {})
    if "content" in snap:
        page.draft_json = json.dumps(snap["content"], ensure_ascii=False)
    if snap.get("seo_title"):
        page.seo_title = snap["seo_title"]
    if snap.get("seo_description"):
        page.seo_description = snap["seo_description"]
    if snap.get("title"):
        page.title = snap["title"]
    page.updated_at = _now()
    return page


def media_public_url(file_path: str) -> str:
    if file_path.startswith("/"):
        return file_path
    return f"/media/cms/{file_path.lstrip('/')}"


def safe_filename(name: str) -> str:
    base = re.sub(r"[^\w.\-]+", "_", name.strip())[:120] or "file"
    return base
