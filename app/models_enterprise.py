"""Modèles entreprise — multi-sociétés, workflows, sécurité, planification."""
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Text, Date
from app.database import Base


class Company(Base):
    """Multi-sociétés."""
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    legal_form = Column(String, default="SARL")
    address = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    currency = Column(String, default="XOF")
    logo_path = Column(String, default="")
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)


class UserSecurity(Base):
    __tablename__ = "user_security"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    totp_secret = Column(String, default="")
    totp_enabled = Column(Boolean, default=False)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(String, default="")
    preferred_language = Column(String, default="fr")
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    token_jti = Column(String, index=True)
    ip_address = Column(String, default="")
    user_agent = Column(String, default="")
    device_label = Column(String, default="")
    created_at = Column(String, default="")
    last_seen_at = Column(String, default="")
    revoked = Column(Boolean, default=False)


class PendingLogin2FA(Base):
    __tablename__ = "pending_login_2fa"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    challenge_token = Column(String, unique=True, index=True)
    expires_at = Column(String, default="")


class UserGroup(Base):
    __tablename__ = "user_groups"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    group_type = Column(String, default="permission")  # permission | mail
    permissions_json = Column(Text, default="[]")
    extra_emails = Column(Text, default="")  # e-mails additionnels (liste JSON ou CSV)
    parent_group_id = Column(Integer, ForeignKey("user_groups.id"), nullable=True)
    is_active = Column(Boolean, default=True)


class UserGroupMember(Base):
    __tablename__ = "user_group_members"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("user_groups.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True, nullable=True)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id = Column(Integer, primary_key=True, index=True)
    module = Column(String, default="")  # invoice, quote, purchase, expense
    entity_type = Column(String, default="")
    entity_id = Column(Integer, nullable=True)
    title = Column(String, default="")
    amount = Column(Float, default=0)
    status = Column(String, default="pending")  # pending, approved, rejected, cancelled
    requested_by = Column(Integer, ForeignKey("users.id"))
    current_level = Column(Integer, default=1)
    max_levels = Column(Integer, default=2)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    created_at = Column(String, default="")
    notes = Column(Text, default="")


class ApprovalStep(Base):
    __tablename__ = "approval_steps"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("approval_requests.id"), index=True)
    level = Column(Integer, default=1)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approver_role = Column(String, default="manager")
    status = Column(String, default="pending")
    decided_at = Column(String, default="")
    comment = Column(Text, default="")


class ScheduledReport(Base):
    __tablename__ = "scheduled_reports"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, default="")
    report_type = Column(String, default="balance")  # balance, invoices, stock, compte_resultat
    format = Column(String, default="xlsx")  # xlsx, pdf, csv
    cron_label = Column(String, default="weekly")  # daily, weekly, monthly
    email_to = Column(String, default="")
    is_active = Column(Boolean, default=True)
    last_run_at = Column(String, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)


class DocumentSignature(Base):
    __tablename__ = "document_signatures"
    id = Column(Integer, primary_key=True, index=True)
    document_type = Column(String)  # quote, invoice, contract
    document_id = Column(Integer)
    signed_by = Column(Integer, ForeignKey("users.id"))
    signer_name = Column(String, default="")
    signature_png = Column(Text, default="")  # base64
    signed_at = Column(String, default="")
    ip_address = Column(String, default="")


class OcrExtraction(Base):
    __tablename__ = "ocr_extractions"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, default="")
    raw_text = Column(Text, default="")
    extracted_json = Column(Text, default="{}")
    corrected_json = Column(Text, default="")
    document_type = Column(String, default="unknown")
    amount = Column(Float, nullable=True)
    supplier_name = Column(String, default="")
    invoice_number = Column(String, default="")
    invoice_date = Column(String, default="")
    confidence_score = Column(Float, default=0)
    validation_json = Column(Text, default="[]")
    status = Column(String, default="pending")  # pending, corrected, validated, applied
    applied_entity_type = Column(String, default="")
    applied_entity_id = Column(Integer, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, default="")


class OcrLearningPattern(Base):
    """Corrections utilisateur mémorisées pour améliorer l'extraction."""
    __tablename__ = "ocr_learning_patterns"
    id = Column(Integer, primary_key=True, index=True)
    document_type = Column(String, default="")
    field_key = Column(String, default="")
    pattern = Column(String, default="")
    replacement_value = Column(String, default="")
    context_snippet = Column(Text, default="")
    hit_count = Column(Integer, default=1)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, default="")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user_name = Column(String, default="")
    message = Column(Text, default="")
    created_at = Column(String, default="")


class NotificationOutbox(Base):
    """File d'attente SMS / WhatsApp."""
    __tablename__ = "notification_outbox"
    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String)  # sms, whatsapp, email
    recipient = Column(String, default="")
    body = Column(Text, default="")
    status = Column(String, default="pending")
    created_at = Column(String, default="")
    sent_at = Column(String, default="")
    error = Column(Text, default="")
