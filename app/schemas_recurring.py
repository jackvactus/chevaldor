"""
Schémas Pydantic pour le module des paiements récurrents.
Validation stricte des données d'entrée/sortie.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List
from datetime import date, datetime
from enum import Enum


class FrequencyType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUALLY = "semiannually"
    ANNUALLY = "annually"
    CUSTOM = "custom"


class RecurrenceStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    CANCELLED = "cancelled"


class PaymentRecurrenceIn(BaseModel):
    """Création/modification d'une récurrence."""
    
    # Informations générales
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = ""
    client_id: int
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    category: Optional[str] = ""
    recurrence_type: Optional[str] = "invoice"  # invoice, payment, expense
    
    # Informations financières
    amount: float = Field(..., gt=0)
    currency_code: str = "XOF"
    vat_rate: float = Field(default=0, ge=0, le=100)
    discount_pct: float = Field(default=0, ge=0, le=100)
    balance: float = 0
    
    # Fréquence
    frequency_code: FrequencyType = "monthly"
    custom_interval_days: Optional[int] = None
    weekdays: Optional[str] = ""  # "1,3,5" pour lun/mer/ven
    month_day: Optional[int] = None  # 15, -1 pour dernier jour
    
    # Dates
    start_date: date
    end_date: Optional[date] = None
    
    # Options
    auto_generate: bool = True
    auto_notify: bool = True
    auto_followup: bool = False
    auto_invoice: bool = False
    draft_days_before: int = Field(default=3, ge=0, le=30)
    
    @field_validator('end_date')
    @classmethod
    def end_date_after_start(cls, v: Optional[date], info):
        if v and info.data.get('start_date') and v <= info.data.get('start_date'):
            raise ValueError('end_date must be after start_date')
        return v
    
    @field_validator('month_day')
    @classmethod
    def valid_month_day(cls, v: Optional[int]):
        if v and not (-1 <= v <= 31):
            raise ValueError('month_day must be 1-31 or -1 (last day)')
        return v


class PaymentRecurrenceUpdate(BaseModel):
    """Mise à jour partielle d'une récurrence."""
    name: Optional[str] = None
    description: Optional[str] = None
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    category: Optional[str] = None
    recurrence_type: Optional[str] = None
    amount: Optional[float] = None
    currency_code: Optional[str] = None
    vat_rate: Optional[float] = None
    discount_pct: Optional[float] = None
    balance: Optional[float] = None
    frequency_code: Optional[FrequencyType] = None
    custom_interval_days: Optional[int] = None
    weekdays: Optional[str] = None
    month_day: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[RecurrenceStatus] = None
    auto_generate: Optional[bool] = None
    auto_notify: Optional[bool] = None
    auto_followup: Optional[bool] = None
    auto_invoice: Optional[bool] = None
    draft_days_before: Optional[int] = None


class PaymentRecurrenceOut(BaseModel):
    """Sérialisation complète d'une récurrence."""
    id: int
    name: str
    description: Optional[str] = None
    client_id: int
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    category: Optional[str] = None
    recurrence_type: Optional[str] = None
    amount: float
    currency_code: str
    vat_rate: float
    discount_pct: float
    balance: float
    frequency_code: str
    custom_interval_days: Optional[int] = None
    weekdays: Optional[str] = None
    month_day: Optional[int] = None
    start_date: date
    end_date: Optional[date]
    next_due_date: date
    status: str
    is_active: bool
    auto_generate: bool
    auto_notify: bool
    auto_followup: bool
    auto_invoice: bool
    draft_days_before: int
    last_generated_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ClientFinancialSummaryOut(BaseModel):
    client_id: int
    client_name: str
    total_due: float
    total_paid: float
    remaining: float
    progress_rate: float
    overdue_count: int
    active_recurrences: int
    last_payment_date: Optional[date] = None


class CollectionPaymentDetailIn(BaseModel):
    """Entrée d'un paiement dans une collecte."""
    client_id: int
    recurrence_id: Optional[int] = None
    payment_amount: float = Field(..., gt=0)
    expected_amount: Optional[float] = None
    payment_date: date
    payment_method: str = "cash"  # cash, mobile_money, bank, check
    payment_reference: Optional[str] = ""
    agent_id: Optional[int] = None
    notes: Optional[str] = ""


class CollectionPaymentDetailOut(BaseModel):
    """Sérialisation d'un paiement dans une collecte."""
    id: int
    collection_id: int
    client_id: int
    payment_amount: float
    expected_amount: float
    payment_date: date
    status: str
    is_partial: bool
    is_anticipate: bool
    created_at: datetime


class PaymentCollectionIn(BaseModel):
    """Création d'une fiche de collecte."""
    collection_date: date
    agent_id: Optional[int] = None
    notes: Optional[str] = ""
    payments: List[CollectionPaymentDetailIn] = []


class PaymentCollectionOut(BaseModel):
    """Sérialisation d'une fiche de collecte."""
    id: int
    collection_date: date
    agent_id: Optional[int]
    total_amount: float
    expected_amount: float
    balance_amount: float
    status: str
    created_at: datetime
    payments: List[CollectionPaymentDetailOut] = []


class CollectionImportMapping(BaseModel):
    """Mapping des colonnes lors de l'import Excel."""
    name_col: int  # numéro colonne Nom
    amount_col: int  # numéro colonne Montant
    date_cols: List[int]  # numéros colonnes Dates
    skip_rows: int = 1  # nombre lignes à ignorer (en-têtes)


class CollectionImportPreview(BaseModel):
    """Prévisualisation avant import."""
    total_rows: int
    clients: List[str]  # noms identifiés
    dates: List[str]  # dates identifiées (ISO)
    data_sample: List[dict]  # 3-5 premières lignes


class CollectionImportValidation(BaseModel):
    """Résultats de validation avant import."""
    is_valid: bool
    total_payments: int
    new_clients: int
    errors: List[str] = []
    warnings: List[str] = []


class RecurrenceGenerationIn(BaseModel):
    """Déclenchement manuel de génération."""
    recurrence_id: int
    generation_date: Optional[date] = None  # date de génération si différente d'aujourd'hui


class PaymentCollectionHistoryIn(BaseModel):
    """Enregistrement d'une modification de paiement."""
    payment_detail_id: int
    new_amount: Optional[float] = None
    new_status: Optional[str] = None
    new_method: Optional[str] = None
    modification_reason: str
