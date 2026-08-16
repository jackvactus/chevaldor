"""Moteur comptable SYSCOHADA — transactions, TVA, lignes achat, stocks, avoirs, CCA."""
from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey, Text, UniqueConstraint
from app.database import Base


class AccountingTransaction(Base):
    """Lien opération métier → écriture comptable (moteur automatique)."""
    __tablename__ = "accounting_transactions"
    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String, nullable=False, index=True)
    # invoice | supplier_invoice | payment | stock_movement | vat_close | prepaid | credit_note
    source_id = Column(Integer, nullable=False, index=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    status = Column(String, default="draft")  # draft | posted | reversed
    label = Column(String, default="")
    amount = Column(Float, default=0)
    posted_at = Column(String, default="")
    reversed_at = Column(String, default="")
    error_message = Column(Text, default="")
    __table_args__ = (UniqueConstraint("source_type", "source_id", name="uq_acct_tx_source"),)


class TaxRate(Base):
    """Taux TVA et taxes — comptes 443/445 associés."""
    __tablename__ = "tax_rates"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    rate = Column(Float, default=0)
    account_collected = Column(String, default="443100")
    account_deductible = Column(String, default="445200")
    is_active = Column(Boolean, default=True)


class VatPeriod(Base):
    """Période d'imposition TVA (mensuelle ou trimestrielle)."""
    __tablename__ = "vat_periods"
    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)  # mois 1-12 ou trimestre 1-4
    period_type = Column(String, default="monthly")  # monthly | quarterly
    status = Column(String, default="open")  # open | closed
    closed_at = Column(String, default="")
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=True)


class VatDeclaration(Base):
    """Déclaration TVA — collectée, déductible, nette."""
    __tablename__ = "vat_declarations"
    id = Column(Integer, primary_key=True, index=True)
    vat_period_id = Column(Integer, ForeignKey("vat_periods.id"), index=True)
    collected_amount = Column(Float, default=0)
    deductible_amount = Column(Float, default=0)
    net_amount = Column(Float, default=0)
    position = Column(String, default="due")  # due | credit | zero
    account_due = Column(String, default="444100")
    account_credit = Column(String, default="444900")
    declared_at = Column(String, default="")
    notes = Column(Text, default="")


class StockCategory(Base):
    """Catégories stock OHADA — classes 31 à 37."""
    __tablename__ = "stock_categories"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    label = Column(String, nullable=False)
    account_stock = Column(String, default="311100")
    account_variation = Column(String, default="603100")
    product_type = Column(String, default="MERCHANDISE")
    is_active = Column(Boolean, default=True)


class SupplierInvoiceLine(Base):
    """Lignes facture fournisseur — typologie SYSCOHADA par ligne."""
    __tablename__ = "supplier_invoice_lines"
    id = Column(Integer, primary_key=True, index=True)
    supplier_invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), index=True)
    position = Column(Integer, default=0)
    description = Column(String, default="")
    quantity = Column(Float, default=1)
    unit_price = Column(Float, default=0)
    vat_rate = Column(Float, default=0)
    product_type = Column(String, default="MERCHANDISE")
    line_kind = Column(String, default="product")  # product | transport | customs | insurance | transit | handling
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    account_code = Column(String, default="")
    purchase_account = Column(String, default="")
    purchase_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    stock_account = Column(String, default="")
    stock_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    vat_account = Column(String, default="")
    vat_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)


class PrepaidExpense(Base):
    """Charges constatées d'avance — compte 476."""
    __tablename__ = "prepaid_expenses"
    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)
    account_charge = Column(String, default="626100")
    account_prepaid = Column(String, default="476000")
    total_amount = Column(Float, default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    months = Column(Integer, default=12)
    amortized = Column(Float, default=0)
    status = Column(String, default="active")  # active | completed
    notes = Column(Text, default="")


class Consignment(Base):
    """Emballages consignés — 4094 / 4194 / 7074."""
    __tablename__ = "consignments"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True)
    label = Column(String, nullable=False)
    unit_value = Column(Float, default=0)
    account_supplier = Column(String, default="409400")
    account_client = Column(String, default="419400")
    account_sale = Column(String, default="707400")
    account_purchase = Column(String, default="622400")
    qty_out = Column(Float, default=0)
    qty_returned = Column(Float, default=0)
    is_active = Column(Boolean, default=True)


class ConsignmentMovement(Base):
    __tablename__ = "consignment_returns"
    id = Column(Integer, primary_key=True, index=True)
    consignment_id = Column(Integer, ForeignKey("consignments.id"), index=True)
    date = Column(Date)
    direction = Column(String)  # out | return
    quantity = Column(Float, default=0)
    partner_type = Column(String, default="client")  # client | supplier
    partner_id = Column(Integer, nullable=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    notes = Column(Text, default="")


class CorporateTaxInstallment(Base):
    """Acomptes impôt sur les sociétés — compte 441."""
    __tablename__ = "corporate_tax_installments"
    id = Column(Integer, primary_key=True, index=True)
    fiscal_year = Column(Integer, nullable=False)
    period = Column(Integer, default=1)
    amount = Column(Float, default=0)
    account_code = Column(String, default="441000")
    charge_account = Column(String, default="891000")
    status = Column(String, default="planned")  # planned | paid
    paid_date = Column(Date, nullable=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)


class PaymentRecord(Base):
    """Paiement client ou fournisseur — source des écritures BQ/CA."""
    __tablename__ = "payment_records"
    id = Column(Integer, primary_key=True, index=True)
    direction = Column(String, nullable=False)  # in | out
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True)
    supplier_invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=True, index=True)
    date = Column(Date)
    amount = Column(Float, default=0)
    method = Column(String, default="banque")  # banque | caisse | flooz | mixx | fedapay
    reference = Column(String, default="")
    notes = Column(Text, default="")
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)


class TaxReport(Base):
    """Rapport TVA archivé (PDF / export déclaration)."""
    __tablename__ = "tax_reports"
    id = Column(Integer, primary_key=True, index=True)
    vat_declaration_id = Column(Integer, ForeignKey("vat_declarations.id"), nullable=True)
    year = Column(Integer)
    period = Column(Integer)
    report_type = Column(String, default="vat")  # vat | corporate
    file_path = Column(String, default="")
    generated_at = Column(String, default="")
    data_json = Column(Text, default="{}")


class CreditNoteTypeRef(Base):
    """Référentiel types d'avoirs SYSCOHADA."""
    __tablename__ = "credit_note_types"
    code = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    account_code = Column(String, default="")
    reverse_stock = Column(Boolean, default=False)


class PayrollRun(Base):
    """Paie OHADA — bulletin mensuel."""
    __tablename__ = "payroll_runs"
    id = Column(Integer, primary_key=True, index=True)
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    status = Column(String, default="draft")  # draft | validated | paid
    total_gross = Column(Float, default=0)
    total_net = Column(Float, default=0)
    total_charges = Column(Float, default=0)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    validated_at = Column(String, default="")


class SalaryLine(Base):
    """Ligne de paie par salarié."""
    __tablename__ = "salary_lines"
    id = Column(Integer, primary_key=True, index=True)
    payroll_run_id = Column(Integer, ForeignKey("payroll_runs.id"), index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True)
    gross_salary = Column(Float, default=0)
    net_salary = Column(Float, default=0)
    employee_charges = Column(Float, default=0)
    employer_charges = Column(Float, default=0)
    withholding_tax = Column(Float, default=0)
    account_expense = Column(String, default="661100")
    account_payable = Column(String, default="422000")
    account_social = Column(String, default="431100")


class Grant(Base):
    """Subventions d'exploitation / investissement — 711-718, 881."""
    __tablename__ = "grants"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True)
    label = Column(String, nullable=False)
    grant_type = Column(String, default="exploitation")  # exploitation | investment | equilibrium
    account_product = Column(String, default="711100")
    account_balance = Column(String, default="881000")
    amount = Column(Float, default=0)
    received = Column(Float, default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(String, default="active")
