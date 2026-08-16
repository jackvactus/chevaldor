"""Modèles plateforme enterprise — workflow, notifications, portail, tickets, sync."""
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text

from app.database import Base


class ApprovalRule(Base):
    """Règle d'approbation configurable par module."""
    __tablename__ = "approval_rules"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    module = Column(String, nullable=False)  # invoice, purchase, payment, leave, recruitment
    min_amount = Column(Float, default=0)
    levels_json = Column(Text, default='[{"role":"manager"},{"role":"admin"},{"role":"admin"}]')
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default="")


class NotificationRule(Base):
    """Règle de notification métier."""
    __tablename__ = "notification_rules"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, nullable=False)  # invoice_overdue, stock_low, payment_received, ...
    channels_json = Column(Text, default='["in_app","email"]')
    is_active = Column(Boolean, default=True)
    template_title = Column(String, default="")
    template_body = Column(Text, default="")


class ClientPortalAccess(Base):
    """Accès portail client par token."""
    __tablename__ = "client_portal_access"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    token = Column(String, unique=True, index=True)
    expires_at = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default="")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class SupportTicket(Base):
    """Ticket réclamation / support."""
    __tablename__ = "support_tickets"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    reference = Column(String, default="")
    subject = Column(String, default="")
    description = Column(Text, default="")
    status = Column(String, default="ouvert")  # ouvert, en_cours, resolu, ferme
    priority = Column(String, default="normale")
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    sla_response_hours = Column(Integer, default=24)
    sla_resolve_hours = Column(Integer, default=72)
    opened_at = Column(String, default="")
    first_response_at = Column(String, default="")
    resolved_at = Column(String, default="")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class SupportTicketMessage(Base):
    """Message / réponse sur ticket."""
    __tablename__ = "support_ticket_messages"
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id"), index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    author_name = Column(String, default="")
    body = Column(Text, default="")
    is_internal = Column(Boolean, default=False)
    created_at = Column(String, default="")


class OfflineSyncBatch(Base):
    """Lot de synchronisation offline (audit)."""
    __tablename__ = "offline_sync_batches"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    device_id = Column(String, default="")
    items_count = Column(Integer, default=0)
    status = Column(String, default="processed")
    created_at = Column(String, default="")
    detail_json = Column(Text, default="{}")
