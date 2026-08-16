"""
Modèles avancés pour la gestion complète des paiements récurrents.
Inclut : fréquences, historique, état, options, auto-génération.
"""

from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Boolean, ForeignKey, Index
from app.database import Base
from datetime import datetime, date


class RecurrenceFrequency(Base):
    """Énumération des fréquences supportées."""
    __tablename__ = "recurrence_frequencies"
    
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)  # daily, weekly, biweekly, monthly, etc.
    label = Column(String)  # "Quotidienne", "Hebdomadaire", etc.
    days_interval = Column(Integer)  # intervalle en jours (-1 = custom)
    description = Column(Text, default="")


class PaymentRecurrence(Base):
    """
    Planification complète de paiements récurrents.
    Remplace + étend InvoiceRecurring.
    """
    __tablename__ = "payment_recurrences"
    
    # Identifiants
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    updated_by = Column(Integer, ForeignKey("users.id"))
    
    # Informations générales
    name = Column(String, index=True)  # "Paiement mensuel Client A"
    description = Column(Text, default="")
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    contract_id = Column(Integer, nullable=True)  # référence optionnelle (table contracts peut ne pas exister)
    category = Column(String, default="")  # "recoulement", "facturation", "service", etc.
    recurrence_type = Column(String, default="invoice")  # invoice, payment, expense
    
    # Informations financières
    amount = Column(Float, default=0)
    currency_code = Column(String, default="XOF")
    vat_rate = Column(Float, default=0)  # % TVA
    discount_pct = Column(Float, default=0)  # % remise
    balance = Column(Float, default=0)  # solde/accomp
    
    # Fréquence
    frequency_code = Column(String, default="monthly", index=True)  # lien vers RecurrenceFrequency
    custom_interval_days = Column(Integer, nullable=True)  # pour fréquence personnalisée
    weekdays = Column(String, default="")  # "1,3,5" pour lun/mer/ven
    month_day = Column(Integer, nullable=True)  # jour du mois (15, -1 pour dernier, etc.)
    
    # Dates
    start_date = Column(Date, index=True)
    end_date = Column(Date, nullable=True, index=True)
    next_due_date = Column(Date, index=True)
    last_generated_at = Column(String, default="")  # ISO 8601
    last_payment_date = Column(Date, nullable=True)
    
    # État
    status = Column(String, default="active", index=True)  # active, suspended, terminated, cancelled
    is_active = Column(Boolean, default=True, index=True)
    
    # Options
    auto_generate = Column(Boolean, default=True)  # génération automatique
    auto_notify = Column(Boolean, default=True)  # envoyer notification
    auto_followup = Column(Boolean, default=False)  # relance auto si non payé
    auto_invoice = Column(Boolean, default=False)  # créer facture auto
    draft_days_before = Column(Integer, default=3)  # créer draft 3j avant
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Index composés
    __table_args__ = (
        Index('idx_recurrence_client_status', 'client_id', 'status'),
        Index('idx_recurrence_next_due', 'next_due_date', 'status'),
        Index('idx_recurrence_company_active', 'company_id', 'is_active'),
    )


class RecurrenceGeneration(Base):
    """
    Trace chaque génération automatique de facture/paiement.
    Audit complet : quand, quoi, résultat.
    """
    __tablename__ = "recurrence_generations"
    
    id = Column(Integer, primary_key=True, index=True)
    recurrence_id = Column(Integer, ForeignKey("payment_recurrences.id"), index=True)
    generated_invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True)
    generated_payment_id = Column(Integer, nullable=True)  # référence optionnelle (pas de table payments)
    
    # Détails de génération
    scheduled_date = Column(Date)  # date prévue
    actual_date = Column(DateTime, default=datetime.utcnow)  # date réelle
    amount = Column(Float)
    status = Column(String, default="success")  # success, failed, skipped
    error_message = Column(Text, default="")
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)


class RecurrenceHistory(Base):
    """
    Historique complet de chaque récurrence.
    Modifications, statut, audit.
    """
    __tablename__ = "recurrence_history"
    
    id = Column(Integer, primary_key=True, index=True)
    recurrence_id = Column(Integer, ForeignKey("payment_recurrences.id"), index=True)
    
    # Type d'action
    action = Column(String)  # created, modified, suspended, resumed, terminated, generated
    
    # Modifications
    old_values = Column(Text, default="{}")  # JSON ancien state
    new_values = Column(Text, default="{}")  # JSON nouveau state
    changed_fields = Column(String, default="")  # champs modifiés
    
    # Audit
    modified_by = Column(Integer, ForeignKey("users.id"))
    reason = Column(Text, default="")  # raison de la modif
    created_at = Column(DateTime, default=datetime.utcnow)


class PaymentCollection(Base):
    """
    Fiche de collecte : regroupement des paiements journaliers.
    Importer depuis Excel, gérer par date, agent, client.
    """
    __tablename__ = "payment_collections"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    
    # Identification
    collection_date = Column(Date, index=True)  # date de la collecte
    agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # agent responsable
    
    # Montants
    total_amount = Column(Float, default=0)  # total des paiements
    expected_amount = Column(Float, default=0)  # montant attendu
    balance_amount = Column(Float, default=0)  # écart
    
    # Statut
    status = Column(String, default="draft")  # draft, submitted, verified, closed
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, default="")


class CollectionPaymentDetail(Base):
    """
    Détail d'un paiement dans une fiche de collecte.
    Lié à un client, une récurrence, un agent.
    """
    __tablename__ = "collection_payment_details"
    
    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, ForeignKey("payment_collections.id"), index=True)
    
    # Qui paie
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    recurrence_id = Column(Integer, ForeignKey("payment_recurrences.id"), nullable=True)
    
    # Le paiement
    payment_amount = Column(Float)  # montant payé
    expected_amount = Column(Float)  # montant attendu
    payment_date = Column(Date)
    payment_method = Column(String, default="cash")  # cash, mobile_money, bank, check
    payment_reference = Column(String, default="")  # numéro transaction
    agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # État
    status = Column(String, default="completed")  # completed, pending, late
    is_partial = Column(Boolean, default=False)
    is_anticipate = Column(Boolean, default=False)
    
    # Audit
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"))
    
    __table_args__ = (
        Index('idx_collection_client_date', 'collection_id', 'client_id'),
    )


class CollectionPaymentHistory(Base):
    """
    Historique détaillé de chaque paiement.
    Modifications, corrections, annulations.
    """
    __tablename__ = "collection_payment_history"
    
    id = Column(Integer, primary_key=True, index=True)
    payment_detail_id = Column(Integer, ForeignKey("collection_payment_details.id"), index=True)
    
    # Ce qui a changé
    old_amount = Column(Float, nullable=True)
    new_amount = Column(Float, nullable=True)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)
    old_method = Column(String, nullable=True)
    new_method = Column(String, nullable=True)
    
    # Qui a changé
    modified_by = Column(Integer, ForeignKey("users.id"))
    modification_reason = Column(Text, default="")
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
