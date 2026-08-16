"""Extensions métier — types clients, recouvrement, contrats commerciaux, audit dates."""
from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, Text

from app.database import Base


class ClientType(Base):
    __tablename__ = "client_types"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    default_discount_pct = Column(Float, default=0)
    default_vat_pct = Column(Float, default=0)
    default_commission_pct = Column(Float, default=0)
    default_withholding_pct = Column(Float, default=0)
    is_archived = Column(Integer, default=0)  # SQLite bool
    notes = Column(Text, default="")


class DateChangeLog(Base):
    """Historique des modifications de dates."""
    __tablename__ = "date_change_logs"
    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String, index=True)  # invoice, journal_entry, supplier_invoice, deal...
    entity_id = Column(Integer, index=True)
    field_name = Column(String)
    old_value = Column(String, default="")
    new_value = Column(String, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_email = Column(String, default="")
    logged_at = Column(String, default="")
    detail = Column(Text, default="")


class JournalEntryHistory(Base):
    """Historique modifications écriture brouillon."""
    __tablename__ = "journal_entry_history"
    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id"), index=True)
    action = Column(String)  # create, update, delete_line, validate
    snapshot_json = Column(Text, default="")
    user_id = Column(Integer, nullable=True)
    user_email = Column(String, default="")
    logged_at = Column(String, default="")


class CollectionCase(Base):
    """Dossier de recouvrement."""
    __tablename__ = "collection_cases"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True)
    reference = Column(String, default="")
    amount_due = Column(Float, default=0)
    amount_collected = Column(Float, default=0)
    due_date = Column(Date)
    delay_days = Column(Integer, default=0)
    status = Column(String, default="ouvert")  # ouvert, partiel, clos, contentieux
    assigned_to = Column(String, default="")
    sales_rep_id = Column(Integer, ForeignKey("sales_reps.id"), nullable=True)
    priority = Column(String, default="normale")
    notes = Column(Text, default="")
    created_at = Column(String, default="")
    updated_at = Column(String, default="")


class CollectionPayment(Base):
    """Collecte journalière / encaissement recouvrement."""
    __tablename__ = "collection_payments"
    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("collection_cases.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True)
    collection_date = Column(Date)
    amount = Column(Float, default=0)
    payment_method = Column(String, default="espèces")  # espèces, chèque, virement, mobile
    reference = Column(String, default="")
    sales_rep_id = Column(Integer, ForeignKey("sales_reps.id"), nullable=True)
    collected_by = Column(String, default="")
    notes = Column(Text, default="")
    created_at = Column(String, default="")


class SalesRep(Base):
    """Commercial / représentant."""
    __tablename__ = "sales_reps"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    name = Column(String, nullable=False)
    email = Column(String, default="")
    phone = Column(String, default="")
    zone = Column(String, default="")
    target_amount = Column(Float, default=0)
    commission_pct = Column(Float, default=0)
    status = Column(String, default="actif")
    notes = Column(Text, default="")


class SalesContract(Base):
    """Contrat commercial client."""
    __tablename__ = "sales_contracts"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    reference = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    amount = Column(Float, default=0)
    discount_pct = Column(Float, default=0)
    vat_pct = Column(Float, default=0)
    commission_pct = Column(Float, default=0)
    status = Column(String, default="brouillon")  # brouillon, actif, expiré, résilié
    sales_rep_id = Column(Integer, ForeignKey("sales_reps.id"), nullable=True)
    renewal_of_id = Column(Integer, ForeignKey("sales_contracts.id"), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(String, default="")
    updated_at = Column(String, default="")


class SalesContractAmendment(Base):
    __tablename__ = "sales_contract_amendments"
    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("sales_contracts.id"), index=True)
    reference = Column(String, default="")
    amendment_date = Column(Date)
    description = Column(Text, default="")
    amount_delta = Column(Float, default=0)
    notes = Column(Text, default="")


class InvoiceRecurring(Base):
    """Planification facture récurrente."""
    __tablename__ = "invoice_recurring"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    template_invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True)
    label = Column(String, default="")
    frequency = Column(String, default="monthly")  # weekly, monthly, quarterly, yearly
    next_date = Column(Date)
    end_date = Column(Date, nullable=True)
    amount = Column(Float, default=0)
    active = Column(Integer, default=1)
    last_generated_at = Column(String, default="")
    notes = Column(Text, default="")


class SmartContextCache(Base):
    """Dernières valeurs utilisées (auto-fill)."""
    __tablename__ = "smart_context_cache"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    context_key = Column(String, index=True)  # journal, account_code, client_id...
    context_value = Column(String, default="")
    use_count = Column(Integer, default=1)
    last_used_at = Column(String, default="")
