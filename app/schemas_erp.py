from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import date as DateType
from typing import Optional, List

from app.schema_base import PeyaSchema
from app.validators import DateFR, MontantXOF, QuantitePos, clean_text, validate_due_after_invoice


class SupplierIn(PeyaSchema):
    name: str = Field(min_length=1, max_length=180)
    code: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    payment_terms: int = 30
    credit_limit: float = 0
    status: str = "actif"
    notes: str = ""

    @field_validator("name")
    @classmethod
    def _supplier_name(cls, v: str) -> str:
        return clean_text(v, min_len=1, max_len=180)


class SupplierOut(SupplierIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SupplierInvoiceIn(PeyaSchema):
    number: str = Field(min_length=1, max_length=40)
    supplier_id: Optional[int] = None
    date: Optional[DateFR] = None
    due_date: Optional[DateFR] = None
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    amount: MontantXOF = 0
    paid: MontantXOF = 0
    status: str = "brouillon"
    doc_type: str = "invoice"
    related_supplier_invoice_id: Optional[int] = None
    purchase_order_id: Optional[int] = None
    goods_receipt_id: Optional[int] = None
    three_way_status: str = "pending"
    three_way_detail: str = ""
    reference: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=4000)

    @field_validator("number")
    @classmethod
    def _number(cls, v: str) -> str:
        return clean_text(v, min_len=1, max_len=40)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        allowed = {"brouillon", "validée", "payée", "en retard", "annulée"}
        if v not in allowed:
            raise ValueError(f"Statut invalide : {v}")
        return v

    @model_validator(mode="after")
    def _dates(self):
        validate_due_after_invoice(self.due_date, self.date)
        return self


class SupplierInvoiceOut(SupplierInvoiceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: Optional[str] = ""
    updated_at: Optional[str] = ""


class SupplierInvoiceLineIn(PeyaSchema):
    description: str = ""
    quantity: float = 1
    unit_price: float = 0
    vat_rate: float = 0
    product_type: str = "MERCHANDISE"
    line_kind: str = "product"
    stock_item_id: Optional[int] = None
    account_code: str = ""
    purchase_account: str = ""
    stock_account: str = ""
    vat_account: str = ""
    position: int = 0


class SupplierInvoiceLineOut(SupplierInvoiceLineIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_invoice_id: int


class BankAccountIn(PeyaSchema):
    name: str
    bank_name: str = ""
    iban: str = ""
    currency: str = "FCFA"
    balance: float = 0
    account_type: str = "bank"
    is_active: bool = True


class BankAccountOut(BankAccountIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TreasuryMovementIn(PeyaSchema):
    date: Optional[DateType] = None
    type: str
    bank_account_id: Optional[int] = None
    label: str = ""
    amount: float = 0
    category: str = ""
    reference: str = ""
    payment_method: str = ""
    reconciled: bool = False
    notes: str = ""


class TreasuryMovementOut(TreasuryMovementIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class JournalLineIn(PeyaSchema):
    account_code: str
    label: str = ""
    debit: float = 0
    credit: float = 0
    client_id: Optional[int] = None
    cost_center_id: Optional[int] = None


class JournalEntryIn(PeyaSchema):
    date: Optional[DateType] = None
    value_date: Optional[DateType] = None
    journal: str = "OD"
    reference: str = ""
    label: str = ""
    status: str = "brouillon"
    fiscal_year: int = 2026
    period: int = 1
    client_id: Optional[int] = None
    observation: str = ""
    lines: List[JournalLineIn] = []


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    date: Optional[DateType] = None
    journal: str
    reference: str
    label: str
    status: str
    fiscal_year: int
    period: int


class CostCenterIn(PeyaSchema):
    code: str
    name: str
    type: str = "coût"
    budget: float = 0
    is_active: bool = True


class CostCenterOut(CostCenterIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BudgetIn(PeyaSchema):
    name: str
    year: int = 2026
    department: str = ""
    project_id: Optional[int] = None
    amount_planned: float = 0
    amount_actual: float = 0
    status: str = "actif"


class BudgetOut(BudgetIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class EmployeeIn(PeyaSchema):
    matricule: str
    firstname: str = ""
    lastname: str = ""
    email: str = ""
    phone: str = ""
    department: str = ""
    position: str = ""
    hire_date: Optional[DateType] = None
    salary_base: float = 0
    status: str = "actif"
    notes: str = ""
    gender: str = ""
    contract_type: str = "CDI"
    manager_id: Optional[int] = None


class EmployeeOut(EmployeeIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LeaveRequestIn(PeyaSchema):
    employee_id: int
    start_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
    type: str = "congé"
    status: str = "en attente"
    days: float = 0
    notes: str = ""


class LeaveRequestOut(LeaveRequestIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: Optional[DateType] = None
    logged_at: str = ""
    user_id: Optional[int] = None
    user_email: str = ""
    action: str
    module: str = ""
    entity_type: str = ""
    entity_id: Optional[int] = None
    detail: str = ""
    old_value: str = ""
    new_value: str = ""
    ip_address: str = ""


class UiActivityIn(PeyaSchema):
    action: str = "navigate"
    module: str = "ui"
    detail: str = ""


class DashboardWidgetsIn(PeyaSchema):
    widgets: List[str] = []
