"""Modèles ERP étendus — comptabilité, achats, trésorerie, RH, budget, audit."""
from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey, Text
from app.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    code = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    address = Column(String, default="")
    city = Column(String, default="")
    payment_terms = Column(Integer, default=30)  # jours
    credit_limit = Column(Float, default=0)
    account_code = Column(String, default="")
    status = Column(String, default="actif")
    is_archived = Column(Boolean, default=False)
    notes = Column(Text, default="")


class SupplierInvoice(Base):
    __tablename__ = "supplier_invoices"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    number = Column(String, unique=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    date = Column(Date)
    due_date = Column(Date)
    amount = Column(Float, default=0)
    paid = Column(Float, default=0)
    status = Column(String, default="brouillon")  # brouillon, validée, payée, en retard
    doc_type = Column(String, default="invoice")  # invoice | credit_note
    related_supplier_invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id"), nullable=True)
    three_way_status = Column(String, default="pending")  # pending | matched | mismatch
    three_way_detail = Column(Text, default="")
    reference = Column(String, default="")
    notes = Column(Text, default="")
    journal_entry_id = Column(Integer, nullable=True)
    payment_terms_days = Column(Integer, default=30)
    issued_at = Column(String, default="")
    payment_date = Column(Date, nullable=True)
    validated_at = Column(String, default="")
    cancelled_at = Column(String, default="")
    created_at = Column(String, default="")
    updated_at = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    payment_terms_days = Column(Integer, default=30)
    issued_at = Column(String, default="")
    payment_date = Column(Date, nullable=True)
    validated_at = Column(String, default="")
    cancelled_at = Column(String, default="")
    created_at = Column(String, default="")
    updated_at = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)


class GoodsReceipt(Base):
    """Réception marchandises — bon de réception achats."""
    __tablename__ = "goods_receipts"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String, unique=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), index=True)
    purchase_request_id = Column(Integer, ForeignKey("purchase_requests.id"), nullable=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    supplier_invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    date = Column(Date)
    status = Column(String, default="brouillon")  # brouillon | validée
    notes = Column(Text, default="")


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    id = Column(Integer, primary_key=True, index=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id"), index=True)
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), nullable=True)
    description = Column(String, default="")
    quantity = Column(Float, default=0)
    unit_cost = Column(Float, default=0)
    position = Column(Integer, default=0)


class PurchaseRequest(Base):
    """Demande d'achat (DA)."""
    __tablename__ = "purchase_requests"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String, unique=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    date = Column(Date)
    status = Column(String, default="brouillon")  # brouillon, validée, convertie, rejetée
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(String, default="")
    updated_at = Column(String, default="")


class PurchaseRequestLine(Base):
    __tablename__ = "purchase_request_lines"
    id = Column(Integer, primary_key=True, index=True)
    purchase_request_id = Column(Integer, ForeignKey("purchase_requests.id"), index=True)
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), nullable=True)
    description = Column(String, default="")
    quantity = Column(Float, default=0)
    unit_cost = Column(Float, default=0)
    position = Column(Integer, default=0)


class PurchaseOrder(Base):
    """Bon de commande fournisseur (BC)."""
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String, unique=True, index=True)
    purchase_request_id = Column(Integer, ForeignKey("purchase_requests.id"), nullable=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), index=True)
    date = Column(Date)
    expected_date = Column(Date, nullable=True)
    status = Column(String, default="brouillon")  # brouillon, validée, partiellement_reçue, reçue, facturée
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(String, default="")
    updated_at = Column(String, default="")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), index=True)
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), nullable=True)
    description = Column(String, default="")
    quantity = Column(Float, default=0)
    unit_cost = Column(Float, default=0)
    vat_rate = Column(Float, default=0)
    position = Column(Integer, default=0)


class BankStatement(Base):
    """Relevé bancaire importé."""
    __tablename__ = "bank_statements"
    id = Column(Integer, primary_key=True, index=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), index=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    filename = Column(String, default="")
    imported_at = Column(String, default="")
    status = Column(String, default="imported")


class BankStatementLine(Base):
    __tablename__ = "bank_statement_lines"
    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("bank_statements.id"), index=True)
    line_date = Column(Date)
    label = Column(String, default="")
    amount = Column(Float, default=0)
    reference = Column(String, default="")
    reconciled = Column(Boolean, default=False)
    treasury_movement_id = Column(Integer, ForeignKey("treasury_movements.id"), nullable=True)
    journal_line_id = Column(Integer, ForeignKey("journal_lines.id"), nullable=True)


class PaymentIntent(Base):
    """Paiement mobile money / FedaPay — intention de collecte."""
    __tablename__ = "payment_intents"
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False)  # fedapay | mixx | flooz | cinetpay
    external_id = Column(String, default="")
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True)
    amount = Column(Float, default=0)
    currency = Column(String, default="XOF")
    status = Column(String, default="pending")  # pending | paid | failed | cancelled
    checkout_url = Column(String, default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(String, default="")


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    bank_name = Column(String, default="")
    iban = Column(String, default="")
    currency = Column(String, default="FCFA")
    balance = Column(Float, default=0)
    account_type = Column(String, default="bank")  # bank | cash | mobile_money | check
    is_active = Column(Boolean, default=True)


class TreasuryMovement(Base):
    """Caisse + banque — entrées / sorties."""
    __tablename__ = "treasury_movements"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date)
    type = Column(String)  # caisse_entree, caisse_sortie, banque_entree, banque_sortie, mobile_money_entree, cheque_entree
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    label = Column(String, default="")
    amount = Column(Float, default=0)
    category = Column(String, default="")
    reference = Column(String, default="")
    payment_method = Column(String, default="")
    reconciled = Column(Boolean, default=False)
    notes = Column(Text, default="")


class JournalEntry(Base):
    """Écriture comptable (en-tête)."""
    __tablename__ = "journal_entries"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date)
    journal = Column(String, default="OD")  # VE, AC, BQ, CA, OD
    reference = Column(String, default="")
    label = Column(String, default="")
    status = Column(String, default="brouillon")  # brouillon, validée
    fiscal_year = Column(Integer, default=2026)
    period = Column(Integer, default=1)  # mois 1-12
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    source_type = Column(String, default="")
    source_id = Column(Integer, nullable=True)
    accounting_transaction_id = Column(Integer, nullable=True)
    reversed_by_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    value_date = Column(Date, nullable=True)
    observation = Column(Text, default="")
    created_at = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    updated_at = Column(String, default="")
    updated_by = Column(Integer, nullable=True)


class JournalLine(Base):
    __tablename__ = "journal_lines"
    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id"), index=True)
    account_code = Column(String, nullable=False)
    label = Column(String, default="")
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    letter_code = Column(String, default="")
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.id"), nullable=True)


class CostCenter(Base):
    """Comptabilité analytique — centres de coûts / profits."""
    __tablename__ = "cost_centers"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True)
    name = Column(String, nullable=False)
    type = Column(String, default="coût")  # coût, profit
    budget = Column(Float, default=0)
    is_active = Column(Boolean, default=True)


class Budget(Base):
    __tablename__ = "budgets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    year = Column(Integer, default=2026)
    department = Column(String, default="")
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    amount_planned = Column(Float, default=0)
    amount_actual = Column(Float, default=0)
    status = Column(String, default="actif")


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    matricule = Column(String, unique=True)
    firstname = Column(String, default="")
    lastname = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    department = Column(String, default="")
    position = Column(String, default="")
    hire_date = Column(Date)
    salary_base = Column(Float, default=0)
    status = Column(String, default="actif")
    notes = Column(Text, default="")
    gender = Column(String, default="")
    contract_type = Column(String, default="CDI")
    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    start_date = Column(Date)
    end_date = Column(Date)
    type = Column(String, default="congé")  # congé, maladie, RTT
    status = Column(String, default="en attente")  # en attente, approuvé, refusé
    days = Column(Float, default=0)
    notes = Column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(Date)
    logged_at = Column(String, default="")  # ISO datetime avec heure
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_email = Column(String, default="")
    action = Column(String)  # create, update, delete, login
    module = Column(String, default="")
    entity_type = Column(String, default="")
    entity_id = Column(Integer, nullable=True)
    detail = Column(Text, default="")
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    ip_address = Column(String, default="")


class UserDashboard(Base):
    """Widgets tableau de bord par utilisateur (JSON)."""
    __tablename__ = "user_dashboards"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    widgets_json = Column(Text, default='["ca","result","creances","stock_alert","pipeline"]')
