"""CMS site vitrine Peya Company."""
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, UniqueConstraint

from app.database import Base


class CmsMedia(Base):
    __tablename__ = "cms_media"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    original_name = Column(String, default="")
    display_name = Column(String, default="")
    file_path = Column(String, nullable=False)
    webp_path = Column(String, default="")
    mime_type = Column(String, default="image/png")
    category = Column(String, default="general")
    alt_text = Column(String, default="")
    folder = Column(String, default="")
    size_bytes = Column(Integer, default=0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    archived = Column(Boolean, default=False)
    created_at = Column(String, default="")
    created_by = Column(Integer, default=0)
    created_by_email = Column(String, default="")


class CmsBanner(Base):
    __tablename__ = "cms_banners"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, default="")
    locale = Column(String, default="fr", index=True)
    image_media_id = Column(Integer, ForeignKey("cms_media.id"), nullable=True)
    link_url = Column(String, default="")
    link_label = Column(String, default="")
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    start_at = Column(String, default="")
    end_at = Column(String, default="")
    status = Column(String, default="draft")
    content_json = Column(Text, default="{}")
    updated_at = Column(String, default="")
    updated_by = Column(Integer, default=0)


class CmsPage(Base):
    __tablename__ = "cms_pages"
    __table_args__ = (UniqueConstraint("slug", "locale", name="uq_cms_page_slug_locale"),)
    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, index=True, nullable=False)
    title = Column(String, default="")
    locale = Column(String, default="fr", index=True)
    status = Column(String, default="draft")  # draft | published
    is_enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    seo_title = Column(String, default="")
    seo_description = Column(Text, default="")
    seo_keywords = Column(String, default="")
    seo_slug = Column(String, default="")
    og_image_id = Column(Integer, ForeignKey("cms_media.id"), nullable=True)
    content_json = Column(Text, default="{}")
    draft_json = Column(Text, default="")
    published_at = Column(String, default="")
    updated_at = Column(String, default="")
    updated_by = Column(Integer, default=0)
    updated_by_email = Column(String, default="")


class CmsPageVersion(Base):
    __tablename__ = "cms_page_versions"
    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("cms_pages.id"), index=True, nullable=False)
    version_no = Column(Integer, default=1)
    snapshot_json = Column(Text, default="{}")
    status = Column(String, default="published")
    created_at = Column(String, default="")
    created_by = Column(Integer, default=0)
    created_by_email = Column(String, default="")


class CmsSiteSettings(Base):
    __tablename__ = "cms_site_settings"
    id = Column(Integer, primary_key=True)
    settings_json = Column(Text, default="{}")
    draft_json = Column(Text, default="")
    updated_at = Column(String, default="")
    updated_by = Column(Integer, default=0)


class CmsDynamicSection(Base):
    """Sections réutilisables : témoignages, partenaires, stats, FAQ, etc."""
    __tablename__ = "cms_dynamic_sections"
    id = Column(Integer, primary_key=True, index=True)
    section_type = Column(String, index=True)  # testimonial, partner, stat, feature, team, project, faq
    locale = Column(String, default="fr", index=True)
    title = Column(String, default="")
    status = Column(String, default="draft")
    sort_order = Column(Integer, default=0)
    content_json = Column(Text, default="{}")
    draft_json = Column(Text, default="")
    updated_at = Column(String, default="")
    updated_by = Column(Integer, default=0)
