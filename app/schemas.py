"""Schémas Pydantic pour validation API"""
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import date as DateType
from typing import Optional

from app.schema_base import PeyaSchema
from app.field_validators import (
    PercentRate,
    clean_text,
    validate_due_after_invoice,
)
from app.validators import DateFR, MontantXOF, QuantitePos


# ============ CLIENT ============
class ClientIn(PeyaSchema):
    name: str = Field(min_length=1, max_length=180)
    type: str = "Entreprise"
    segment: str = ""
    contact: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    status: str = "prospect"
    credit_limit: float = 0
    payment_terms: int = 30
    account_code: str = Field(default="", max_length=20)
    client_type_id: Optional[int] = None
    default_discount_pct: float = 0
    default_vat_pct: float = 0
    default_commission_pct: float = 0
    default_withholding_pct: float = 0
    notes: str = ""

    @field_validator("name")
    @classmethod
    def _client_name(cls, v: str) -> str:
        return clean_text(v, min_len=1, max_len=180)

class ClientOut(ClientIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ DEAL ============
class DealIn(PeyaSchema):
    title: str
    client_id: Optional[int] = None
    stage: str = "lead"
    amount: float = 0
    probability: int = 20
    owner: str = "Peya Company"
    sales_rep_id: Optional[int] = None
    close_date: Optional[DateType] = None
    pole: str = "Consulting"
    notes: str = ""

class DealOut(DealIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ QUOTE ============
class QuoteIn(PeyaSchema):
    number: str = Field(min_length=1, max_length=40)
    client_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: str = ""
    date: Optional[DateFR] = None
    valid_until: Optional[DateFR] = None
    amount: MontantXOF = 0
    vat_rate: float = 0
    status: str = "brouillon"
    discount_pct: PercentRate = 0
    discount_amount: MontantXOF = 0
    notes: str = Field(default="", max_length=4000)

    @field_validator("number")
    @classmethod
    def _quote_number(cls, v: str) -> str:
        return clean_text(v, min_len=1, max_len=40)

    @model_validator(mode="after")
    def _quote_dates(self):
        validate_due_after_invoice(self.valid_until, self.date)
        return self

class QuoteOut(QuoteIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ INVOICE ============
class InvoiceIn(PeyaSchema):
    number: str = Field(min_length=1, max_length=40)
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    quote_id: Optional[int] = None
    date: Optional[DateFR] = None
    due_date: Optional[DateFR] = None
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    amount: MontantXOF = 0
    vat_rate: PercentRate = 0
    paid: MontantXOF = 0
    status: str = "brouillon"
    doc_type: str = "invoice"  # invoice | credit_note | proforma | deposit
    delivery_date: Optional[DateFR] = None
    discount_pct: PercentRate = 0
    discount_amount: MontantXOF = 0
    commission_pct: PercentRate = 0
    withholding_pct: PercentRate = 0
    notes: str = Field(default="", max_length=4000)
    description: str = Field(default="", max_length=8000)

    @field_validator("number")
    @classmethod
    def _number(cls, v: str) -> str:
        return clean_text(v, min_len=1, max_len=40)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        allowed = {"brouillon", "envoyée", "payée", "en retard", "annulée"}
        if v not in allowed:
            raise ValueError(f"Statut invalide : {v}")
        return v

    @model_validator(mode="after")
    def _dates(self):
        validate_due_after_invoice(self.due_date, self.date)
        return self

class InvoiceOut(InvoiceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    issued_at: Optional[str] = ""
    payment_date: Optional[DateType] = None
    validated_at: Optional[str] = ""
    cancelled_at: Optional[str] = ""
    created_at: Optional[str] = ""
    updated_at: Optional[str] = ""


# ============ PROJECT ============
class ProjectIn(PeyaSchema):
    name: str
    client_id: Optional[int] = None
    pole: str = "Consulting"
    status: str = "planifié"
    progress: int = 0
    budget: float = 0
    billed: float = 0
    start_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
    manager: str = "Peya Company"
    description: str = ""

class ProjectOut(ProjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ TASK ============
class TaskIn(PeyaSchema):
    project_id: int
    label: str
    done: bool = False
    date: Optional[DateType] = None
    assignee: str = "Peya Company"
    kanban_status: str = "todo"

class TaskOut(TaskIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ TRAINING ============
class TrainingIn(PeyaSchema):
    title: str
    client_id: Optional[int] = None
    start_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
    duration: int = 1
    daily_rate: float = 1000
    location: str = ""
    mode: str = "intra"
    status: str = "planifiée"
    qualiopi: bool = False
    funder: str = ""
    notes: str = ""

class TrainingOut(TrainingIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ TRAINEE ============
class TraineeIn(PeyaSchema):
    training_id: int
    firstname: str = ""
    lastname: str = ""
    email: str = ""
    company: str = ""
    attendance: float = 100
    evaluation: float = 0
    certified: bool = False

class TraineeOut(TraineeIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ STOCK ============
class StockItemIn(PeyaSchema):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=240)
    category: str = ""
    unit: str = "unité"
    quantity: float = 0
    min_quantity: float = 0
    unit_cost: float = 0
    unit_price: float = 0
    supplier: str = ""
    location: str = ""

    @field_validator("sku")
    @classmethod
    def _stock_sku(cls, v: str) -> str:
        return clean_text(v, min_len=1, max_len=60).upper()

    @field_validator("name")
    @classmethod
    def _stock_name(cls, v: str) -> str:
        return clean_text(v, min_len=1, max_len=240)

class StockItemOut(StockItemIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: str = ""
    updated_at: str = ""


class StockMovementIn(PeyaSchema):
    item_id: int
    date: Optional[DateType] = None
    type: str  # entrée, sortie
    quantity: float
    reason: str = ""
    project_id: Optional[int] = None
    notes: str = ""

class StockMovementOut(StockMovementIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    logged_at: str = ""
    movement_kind: str = ""
    qty_before: Optional[float] = None
    qty_after: Optional[float] = None
    user_email: str = ""


# ============ ACCOUNTING ============
class AccountIn(PeyaSchema):
    code: str
    label: str
    type: str
    class_code: str = ""
    parent_code: str = ""
    level: int = 2

class AccountOut(AccountIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TransactionIn(PeyaSchema):
    date: Optional[DateType] = None
    label: str
    type: str  # produit, charge
    category: str = ""
    amount: float = 0
    account_code: str = ""
    payment_method: str = "virement"
    reference: str = ""
    notes: str = ""

class TransactionOut(TransactionIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ============ CLIENTÈLE PC ============
class ClientLedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    date: Optional[DateType] = None
    commande: float = 0
    remboursement: float = 0
    solde: float = 0
    source_file: str = ""


class ClienteleSummaryItem(BaseModel):
    client_id: int
    name: str
    phone: str = ""
    email: str = ""
    city: str = ""
    status: str = "actif"
    notes: str = ""
    total_commande: float
    total_remboursement: float
    solde_actuel: float
    nb_mouvements: int


class ClienteleDebitorItem(BaseModel):
    client_id: int
    name: str
    solde_actuel: float
    total_commande: float
    total_remboursement: float = 0
    taux_recouvrement: float = 0


class ClienteleDashboardOut(BaseModel):
    nb_clients: int = 0
    total_commande: float = 0
    total_remboursement: float = 0
    reste_a_payer: float = 0
    credits_client: float = 0
    solde_net: float = 0
    clients_a_relancer: int = 0
    clients_soldes: int = 0
    taux_recouvrement: float = 0
    panier_moyen: float = 0
    nb_mouvements: int = 0
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    top_debiteurs: list[ClienteleDebitorItem] = Field(default_factory=list)


class ClienteleClientIn(PeyaSchema):
    name: str
    phone: str = ""
    email: str = ""
    city: str = ""
    status: str = "actif"
    notes: str = ""


class ClientLedgerIn(PeyaSchema):
    client_id: int
    date: Optional[DateType] = None
    commande: float = 0
    remboursement: float = 0


class ClienteleBoardClient(BaseModel):
    client_id: int
    name: str
    commandes: list[float]
    remboursements: list[float]
    soldes: list[float]
    entry_ids: list[Optional[int]] = Field(default_factory=list)


class LedgerCellUpsert(PeyaSchema):
    client_id: int
    date: Optional[DateType] = None
    commande: Optional[float] = None
    remboursement: Optional[float] = None


class ClienteleBoardOut(BaseModel):
    title: str
    dates: list[str]
    clients: list[ClienteleBoardClient]
    total_dates: int = 0
    truncated: bool = False


# ============ LIGNES DOCUMENTS / CRM ============
class DocumentLineIn(PeyaSchema):
    product_type: str = "SERVICE"
    stock_item_id: Optional[int] = None
    account_code: str = ""
    sale_account: str = ""
    purchase_account: str = ""
    reference: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    unit: str = Field(default="unité", max_length=30)
    quantity: QuantitePos = 1
    unit_price: MontantXOF = 0
    vat_rate: PercentRate = 0
    discount_pct: PercentRate = 0
    discount_amount: MontantXOF = 0
    position: int = 0


class DocumentLineOut(DocumentLineIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    quote_id: Optional[int] = None
    invoice_id: Optional[int] = None


class DocumentLinesReplace(BaseModel):
    lines: list[DocumentLineIn] = Field(default_factory=list)


class DealStagePatch(BaseModel):
    stage: str


class ActivityIn(PeyaSchema):
    client_id: int
    type: str = "note"
    subject: str = ""
    body: str = ""
    date: Optional[DateType] = None
    related_type: str = ""
    related_id: Optional[int] = None


class ActivityOut(ActivityIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_name: str = ""


class CompanyProfileIn(PeyaSchema):
    name: str = "Peya Company"
    legal_form: str = "SARL"
    tagline: str = ""
    description: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    logo_path: str = "/static/logo-peya.png"
    currency: str = "FCFA"


class CompanyProfileOut(CompanyProfileIn):
    model_config = ConfigDict(from_attributes=True)
    id: int = 1


class Client360Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    client: ClientOut
    deals: list[DealOut] = []
    quotes: list[QuoteOut] = []
    invoices: list[InvoiceOut] = []
    projects: list[ProjectOut] = []
    activities: list[ActivityOut] = []
    totals: dict = {}
