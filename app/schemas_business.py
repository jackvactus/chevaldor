"""Schémas — extensions métier phases A-F."""
from datetime import date as DateType
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schema_base import PeyaSchema


class ClientTypeIn(PeyaSchema):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    default_discount_pct: float = 0
    default_vat_pct: float = 0
    default_commission_pct: float = 0
    default_withholding_pct: float = 0
    is_archived: bool = False
    notes: str = ""


class ClientTypeOut(ClientTypeIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class DateChangeIn(PeyaSchema):
    entity_type: str
    entity_id: int
    field_name: str
    new_value: DateType
    detail: str = ""


class JournalEntryUpdateIn(PeyaSchema):
    date: Optional[DateType] = None
    value_date: Optional[DateType] = None
    journal: Optional[str] = None
    reference: Optional[str] = None
    label: Optional[str] = None
    fiscal_year: Optional[int] = None
    period: Optional[int] = None
    client_id: Optional[int] = None
    observation: Optional[str] = None
    lines: Optional[List[dict]] = None


class CollectionCaseIn(PeyaSchema):
    client_id: int
    invoice_id: Optional[int] = None
    reference: str = ""
    amount_due: float = 0
    due_date: Optional[DateType] = None
    status: str = "ouvert"
    assigned_to: str = ""
    sales_rep_id: Optional[int] = None
    priority: str = "normale"
    notes: str = ""


class CollectionCaseOut(CollectionCaseIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    amount_collected: float = 0
    delay_days: int = 0


class CollectionPaymentIn(PeyaSchema):
    case_id: Optional[int] = None
    client_id: int
    invoice_id: Optional[int] = None
    collection_date: Optional[DateType] = None
    amount: float = 0
    payment_method: str = "espèces"
    reference: str = ""
    sales_rep_id: Optional[int] = None
    collected_by: str = ""
    notes: str = ""


class CollectionPaymentOut(CollectionPaymentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SalesRepIn(PeyaSchema):
    name: str
    user_id: Optional[int] = None
    employee_id: Optional[int] = None
    email: str = ""
    phone: str = ""
    zone: str = ""
    target_amount: float = 0
    commission_pct: float = 0
    status: str = "actif"
    notes: str = ""


class SalesRepOut(SalesRepIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SalesContractIn(PeyaSchema):
    client_id: int
    reference: str
    title: str
    start_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
    amount: float = 0
    discount_pct: float = 0
    vat_pct: float = 0
    commission_pct: float = 0
    status: str = "brouillon"
    sales_rep_id: Optional[int] = None
    notes: str = ""


class SalesContractOut(SalesContractIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SalesContractAmendmentIn(PeyaSchema):
    reference: str = ""
    amendment_date: Optional[DateType] = None
    description: str = ""
class InvoiceRecurringIn(PeyaSchema):
    client_id: int
    template_invoice_id: Optional[int] = None
    label: str = ""
    frequency: str = "monthly"  # daily, weekly, monthly, quarterly, yearly
    next_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
    amount: float = 0
    active: bool = True
    notes: str = ""


class InvoiceRecurringOut(InvoiceRecurringIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    last_generated_at: str = ""
