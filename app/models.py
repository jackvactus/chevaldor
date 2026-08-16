"""Modèles de données SQLAlchemy"""
from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, default="Entreprise")  # Collectivité, Entreprise, Particulier, Institution
    segment = Column(String, default="")  # Public, Industrie, BTP, Résidentiel...
    contact = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    city = Column(String, default="")
    status = Column(String, default="prospect")  # prospect, actif, inactif
    credit_limit = Column(Float, default=0)
    payment_terms = Column(Integer, default=30)
    account_code = Column(String, default="")
    is_archived = Column(Boolean, default=False)
    client_type_id = Column(Integer, nullable=True)
    default_discount_pct = Column(Float, default=0)
    default_vat_pct = Column(Float, default=0)
    default_commission_pct = Column(Float, default=0)
    default_withholding_pct = Column(Float, default=0)
    notes = Column(Text, default="")


class Deal(Base):
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"))
    stage = Column(String, default="lead")  # lead, qualified, proposal, negotiation, won, lost
    amount = Column(Float, default=0)
    probability = Column(Integer, default=20)  # %
    owner = Column(String, default="Peya Company")
    sales_rep_id = Column(Integer, nullable=True)
    close_date = Column(Date)
    pole = Column(String, default="Consulting")  # Consulting, Formation, Installations, Développement, Automatisation
    notes = Column(Text, default="")


class Quote(Base):
    __tablename__ = "quotes"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    number = Column(String, unique=True)  # Q2026-001
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"))
    deal_id = Column(Integer, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, default="")
    date = Column(Date)
    valid_until = Column(Date)
    amount = Column(Float, default=0)
    vat_rate = Column(Float, default=0)  # % TVA globale si pas de lignes détaillées
    status = Column(String, default="brouillon")  # brouillon, envoyé, accepté, refusé, expiré
    discount_pct = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    notes = Column(Text, default="")


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    number = Column(String, unique=True)  # F2026-001
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"))
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    quote_id = Column(Integer, ForeignKey("quotes.id", ondelete="SET NULL"), nullable=True)
    date = Column(Date)
    due_date = Column(Date)
    amount = Column(Float, default=0)
    vat_rate = Column(Float, default=0)
    paid = Column(Float, default=0)
    status = Column(String, default="brouillon")  # brouillon, envoyée, payée, en retard, annulée
    doc_type = Column(String, default="invoice")  # invoice | credit_note | proforma | deposit
    credit_note_type = Column(String, default="")  # RETURN | RABAIS | REMISE | RISTOURNE | ESCOMPTE
    related_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    delivery_date = Column(Date, nullable=True)
    discount_pct = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    commission_pct = Column(Float, default=0)
    withholding_pct = Column(Float, default=0)
    recurring_plan_id = Column(Integer, nullable=True)
    journal_entry_id = Column(Integer, nullable=True)
    is_archived = Column(Boolean, default=False)
    notes = Column(Text, default="")
    description = Column(Text, default="")
    payment_terms_days = Column(Integer, default=30)
    issued_at = Column(String, default="")
    payment_date = Column(Date, nullable=True)
    validated_at = Column(String, default="")
    cancelled_at = Column(String, default="")
    created_at = Column(String, default="")
    updated_at = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)


class DocumentLine(Base):
    """Lignes de devis / facture (FreshBooks, Zoho Invoice)."""
    __tablename__ = "document_lines"
    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(Integer, ForeignKey("quotes.id"), nullable=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True)
    position = Column(Integer, default=0)
    reference = Column(String, default="")
    description = Column(String, default="")
    unit = Column(String, default="unité")
    quantity = Column(Float, default=1)
    unit_price = Column(Float, default=0)
    vat_rate = Column(Float, default=0)  # %
    discount_pct = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    product_type = Column(String, default="SERVICE")
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    account_code = Column(String, default="")
    sale_account = Column(String, default="")
    sale_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    purchase_account = Column(String, default="")
    purchase_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)


class Activity(Base):
    """Timeline CRM (Salesforce, HubSpot)."""
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    type = Column(String, default="note")  # note, call, email, meeting, deal, invoice
    subject = Column(String, default="")
    body = Column(Text, default="")
    date = Column(Date)
    user_name = Column(String, default="")
    related_type = Column(String, default="")
    related_id = Column(Integer, nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"))
    pole = Column(String, default="Consulting")
    status = Column(String, default="planifié")  # planifié, en cours, terminé, suspendu
    progress = Column(Integer, default=0)  # %
    budget = Column(Float, default=0)
    billed = Column(Float, default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    manager = Column(String, default="Peya Company")
    description = Column(Text, default="")


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    label = Column(String, nullable=False)
    done = Column(Boolean, default=False)
    date = Column(Date)
    assignee = Column(String, default="Peya Company")
    kanban_status = Column(String, default="todo")  # todo | in_progress | review | done


class Training(Base):
    __tablename__ = "trainings"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    start_date = Column(Date)
    end_date = Column(Date)
    duration = Column(Integer, default=1)  # jours
    daily_rate = Column(Float, default=1000)
    location = Column(String, default="")
    mode = Column(String, default="intra")  # intra, inter, distance
    status = Column(String, default="planifiée")  # planifiée, en cours, terminée, annulée
    qualiopi = Column(Boolean, default=False)
    funder = Column(String, default="")  # OPCO, CPF, Client direct...
    notes = Column(Text, default="")


class Trainee(Base):
    __tablename__ = "trainees"
    id = Column(Integer, primary_key=True, index=True)
    training_id = Column(Integer, ForeignKey("trainings.id"))
    firstname = Column(String, default="")
    lastname = Column(String, default="")
    email = Column(String, default="")
    company = Column(String, default="")
    attendance = Column(Float, default=100)  # % présence
    evaluation = Column(Float, default=0)  # note /20
    certified = Column(Boolean, default=False)


class StockItem(Base):
    __tablename__ = "stock_items"
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True)
    barcode = Column(String, default="")
    name = Column(String, nullable=False)
    category = Column(String, default="")  # Énergie, Réseau, IRVE, TEGIS, Outillage...
    unit = Column(String, default="unité")
    quantity = Column(Float, default=0)  # stock physique
    qty_theoretical = Column(Float, default=0)
    qty_reserved = Column(Float, default=0)
    qty_on_order = Column(Float, default=0)
    min_quantity = Column(Float, default=0)
    max_quantity = Column(Float, default=0)
    safety_stock = Column(Float, default=0)
    reorder_point = Column(Float, default=0)
    unit_cost = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    supplier = Column(String, default="")
    location = Column(String, default="")
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    expiry_date = Column(Date, nullable=True)
    product_accounting_type = Column(String, default="MERCHANDISE")
    stock_category_id = Column(Integer, ForeignKey("stock_categories.id"), nullable=True)
    purchase_account = Column(String, default="")
    purchase_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    sale_account = Column(String, default="")
    sale_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    stock_account = Column(String, default="")
    stock_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    vat_account = Column(String, default="")
    vat_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(String, default="")  # date/heure d'intégration
    updated_at = Column(String, default="")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("stock_items.id"))
    date = Column(Date)
    logged_at = Column(String, default="")
    type = Column(String)  # entrée, sortie
    movement_kind = Column(String, default="")  # entrée, sortie, ajustement, inventaire, transfert
    quantity = Column(Float, default=0)
    qty_before = Column(Float, nullable=True)
    qty_after = Column(Float, nullable=True)
    unit_cost = Column(Float, nullable=True)  # PRU au moment du mouvement (grand livre stock)
    reason = Column(String, default="")
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    warehouse_to_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_email = Column(String, default="")
    notes = Column(Text, default="")


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True)  # 706, 622, 641...
    label = Column(String)
    type = Column(String)  # produit, charge, actif, passif
    class_code = Column(String, default="")  # classe SYSCOHADA 1-8
    parent_code = Column(String, default="")
    level = Column(Integer, default=2)  # 2=compte principal, 3-4=divisionnaire


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date)
    label = Column(String)
    type = Column(String)  # produit, charge
    category = Column(String, default="")  # Consulting, Formation, Loyer, Salaires...
    amount = Column(Float, default=0)
    account_code = Column(String, default="")
    payment_method = Column(String, default="virement")
    reference = Column(String, default="")  # n° facture
    notes = Column(Text, default="")


class ClientLedgerEntry(Base):
    """Mouvements clientèle PC : commandes, remboursements, soldes par date."""
    __tablename__ = "client_ledger"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    date = Column(Date, index=True)
    commande = Column(Float, default=0)
    remboursement = Column(Float, default=0)
    solde = Column(Float, default=0)
    source_file = Column(String, default="")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    first_name = Column(String, default="")
    last_name = Column(String, default="")
    full_name = Column(String, default="")
    department = Column(String, default="")  # service
    role = Column(String, default="viewer")  # admin, manager, commercial, compta, viewer
    password_hash = Column(String, nullable=False)
    must_change_password = Column(Boolean, default=False)
    password_expires_at = Column(String, default="")
    last_password_change = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(Date)
    updated_at = Column(String, default="")


class ImportBatch(Base):
    """Historique des imports Excel / fichiers."""
    __tablename__ = "import_batches"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, default="")
    sheet_type = Column(String, default="")
    status = Column(String, default="pending")  # pending, processing, done, error
    rows_total = Column(Integer, default=0)
    rows_ok = Column(Integer, default=0)
    errors_json = Column(Text, default="[]")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Date)


class CompanyProfile(Base):
    """Informations société (page d'accueil, en-têtes documents) — ligne unique id=1."""
    __tablename__ = "company_profile"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="Peya Company")
    legal_form = Column(String, default="SARL")
    tagline = Column(String, default="Votre entreprise, pilotée en un seul endroit")
    description = Column(Text, default="")
    address = Column(String, default="Lomé, Togo")
    phone = Column(String, default="")
    email = Column(String, default="contact@peyacompany.com")
    logo_path = Column(String, default="/static/logo-peya.png")
    currency = Column(String, default="FCFA")


class Attachment(Base):
    """Fichiers joints : images, PDF, exports liés aux clients ou imports."""
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    mime_type = Column(String, default="application/octet-stream")
    size_bytes = Column(Integer, default=0)
    entity_type = Column(String, default="")  # client, import_batch, project
    entity_id = Column(Integer, nullable=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Date)
