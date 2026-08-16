"""Préférences utilisateur, paramètres système, SMTP et notifications."""
from sqlalchemy import Column, Integer, String, ForeignKey, Text, Boolean
from app.database import Base


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    theme = Column(String, default="light")  # dark | light (résolu)
    theme_mode = Column(String, default="light")  # dark | light | auto
    color_palette = Column(String, default="peya")
    custom_theme_json = Column(Text, default="{}")
    font_scale = Column(String, default="1")  # 0.85 | 1 | 1.1 | 1.2 — taille des polices UI
    display_currency_code = Column(String, default="XOF")  # devise affichage plateforme
    fiscal_year = Column(Integer, default=2026)
    language = Column(String, default="fr")
    auto_refresh = Column(Boolean, default=False)
    widgets_json = Column(Text, default='["ca","result","creances","dettes","stock","pipeline"]')
    notifications_json = Column(Text, default="[]")


class PasswordHistory(Base):
    __tablename__ = "password_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(String, default="")


class AppNotification(Base):
    __tablename__ = "app_notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    type = Column(String, default="info")  # info, warn, success
    title = Column(String, default="")
    message = Column(Text, default="")
    read = Column(Boolean, default=False)
    created_at = Column(String, default="")
    category = Column(String, default="system")
    channel = Column(String, default="in_app")


class SystemSettings(Base):
    """Paramètres globaux application (ligne unique id=1)."""
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True)
    company_name = Column(String, default="Peya Company")
    company_logo = Column(String, default="/static/logo-peya.png")
    address = Column(String, default="Lomé, Togo")
    phone = Column(String, default="")
    email = Column(String, default="contact@peyacompany.com")
    website = Column(String, default="")
    currency = Column(String, default="FCFA")
    timezone = Column(String, default="Africa/Lome")
    language = Column(String, default="fr")
    accounting_year = Column(Integer, default=2026)
    accounting_plan = Column(String, default="SYSCOHADA")
    inventory_method = Column(String, default="PERMANENT")  # PERMANENT | INTERMITTENT
    journals_json = Column(Text, default='["VE","AC","BQ","CA","OD"]')
    taxes_json = Column(Text, default='[{"name":"TVA","rate":0}]')
    default_accounts_json = Column(Text, default='{"sales":"706","purchases":"607","bank":"512"}')
    password_policy_json = Column(Text, default=(
        '{"min_length":8,"uppercase":true,"lowercase":true,"digits":true,"special":true,'
        '"history_count":5,"expiry_days":90,"max_failed_attempts":5,"lock_minutes":15}'
    ))
    two_factor_enabled = Column(Boolean, default=False)
    session_timeout_min = Column(Integer, default=720)
    backup_enabled = Column(Boolean, default=False)
    backup_frequency = Column(String, default="daily")
    backup_retention_days = Column(Integer, default=30)
    backup_last_run = Column(String, default="")
    closed_fiscal_years_json = Column(Text, default="[]")
    archive_enabled = Column(Boolean, default=True)
    appearance_json = Column(Text, default="{}")
    documents_json = Column(Text, default="{}")
    storage_json = Column(Text, default="{}")
    integrations_json = Column(Text, default="{}")


class SmtpSettings(Base):
    """Configuration SMTP globale (ligne unique id=1)."""
    __tablename__ = "smtp_settings"
    id = Column(Integer, primary_key=True)
    host = Column(String, default="")
    port = Column(Integer, default=587)
    username = Column(String, default="")
    password = Column(String, default="")
    use_tls = Column(Boolean, default=True)
    use_ssl = Column(Boolean, default=False)
    sender_email = Column(String, default="")
    sender_name = Column(String, default="Peya Company")
    provider = Column(String, default="custom")
    enabled = Column(Boolean, default=False)


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    subject = Column(String, default="")
    body = Column(Text, default="")
    is_active = Column(Boolean, default=True)


class EmailLog(Base):
    __tablename__ = "email_logs"
    id = Column(Integer, primary_key=True, index=True)
    to_email = Column(String, default="")
    subject = Column(String, default="")
    body = Column(Text, default="")
    status = Column(String, default="pending")
    provider = Column(String, default="smtp")
    error = Column(Text, default="")
    created_at = Column(String, default="")


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    email_enabled = Column(Boolean, default=True)
    in_app_enabled = Column(Boolean, default=True)
    sms_enabled = Column(Boolean, default=False)
    whatsapp_enabled = Column(Boolean, default=False)
    categories_json = Column(Text, default='["system","billing","stock","security"]')


class LoginLog(Base):
    __tablename__ = "login_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_email = Column(String, default="")
    success = Column(Boolean, default=False)
    ip_address = Column(String, default="")
    logged_at = Column(String, default="")
    user_agent = Column(String, default="")
