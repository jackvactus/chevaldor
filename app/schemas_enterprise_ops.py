"""Schémas Pydantic — modules enterprise RH / CRM / Logistique."""
from datetime import date
from typing import Optional

from pydantic import ConfigDict

from app.schema_base import PeyaSchema


class HrDepartmentIn(PeyaSchema):
    code: str = ""
    name: str
    parent_id: Optional[int] = None
    manager_name: str = ""
    budget: float = 0
    headcount_target: int = 0
    status: str = "actif"


class HrDepartmentOut(HrDepartmentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class HrContractIn(PeyaSchema):
    employee_id: Optional[int] = None
    employee_name: str = ""
    contract_type: str = "CDI"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    salary: float = 0
    status: str = "actif"
    notes: str = ""


class HrContractOut(HrContractIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class HrBonusIn(PeyaSchema):
    employee_id: Optional[int] = None
    employee_name: str = ""
    label: str = "Prime"
    amount: float = 0
    period_month: int = 1
    period_year: int = 2026
    status: str = "prévu"


class HrBonusOut(HrBonusIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class HrRecruitmentIn(PeyaSchema):
    title: str
    department: str = ""
    status: str = "ouvert"
    candidates_count: int = 0
    opened_at: Optional[date] = None
    salary_min: float = 0
    salary_max: float = 0
    notes: str = ""


class HrRecruitmentOut(HrRecruitmentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class HrEvaluationIn(PeyaSchema):
    employee_id: Optional[int] = None
    employee_name: str = ""
    period: str = ""
    score: float = 0
    reviewer: str = ""
    status: str = "brouillon"
    goals: str = ""
    notes: str = ""


class HrEvaluationOut(HrEvaluationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class HrTrainingPlanIn(PeyaSchema):
    title: str
    trainer: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    participants: int = 0
    budget: float = 0
    status: str = "planifié"


class HrTrainingPlanOut(HrTrainingPlanIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CrmLeadIn(PeyaSchema):
    name: str
    company: str = ""
    email: str = ""
    phone: str = ""
    source: str = ""
    stage: str = "nouveau"
    amount: float = 0
    owner: str = ""
    sales_rep_id: Optional[int] = None
    status: str = "actif"
    notes: str = ""


class CrmLeadOut(CrmLeadIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CrmActivityIn(PeyaSchema):
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    deal_id: Optional[int] = None
    activity_type: str = "appel"
    subject: str = ""
    due_date: Optional[date] = None
    status: str = "à faire"
    notes: str = ""


class CrmActivityOut(CrmActivityIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CrmCampaignIn(PeyaSchema):
    name: str
    channel: str = ""
    budget: float = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    leads_count: int = 0
    status: str = "active"


class CrmCampaignOut(CrmCampaignIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LogisticsVehicleIn(PeyaSchema):
    plate: str
    brand: str = ""
    model: str = ""
    year: int = 0
    capacity_kg: float = 0
    fuel_type: str = "diesel"
    status: str = "disponible"
    mileage: float = 0
    cost_per_km: float = 0


class LogisticsVehicleOut(LogisticsVehicleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LogisticsDriverIn(PeyaSchema):
    name: str
    phone: str = ""
    license_number: str = ""
    status: str = "actif"
    vehicle_id: Optional[int] = None


class LogisticsDriverOut(LogisticsDriverIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LogisticsCarrierIn(PeyaSchema):
    name: str
    contact: str = ""
    phone: str = ""
    email: str = ""
    rating: float = 0
    status: str = "actif"


class LogisticsCarrierOut(LogisticsCarrierIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LogisticsShipmentIn(PeyaSchema):
    reference: str
    origin: str = ""
    destination: str = ""
    vehicle_id: Optional[int] = None
    driver_id: Optional[int] = None
    carrier_id: Optional[int] = None
    status: str = "planifié"
    weight_kg: float = 0
    cost: float = 0
    scheduled_date: Optional[date] = None
    delivered_date: Optional[date] = None


class LogisticsShipmentOut(LogisticsShipmentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LogisticsRouteIn(PeyaSchema):
    name: str
    zone: str = ""
    distance_km: float = 0
    vehicle_id: Optional[int] = None
    stops_count: int = 0
    status: str = "active"
    avg_duration_hours: float = 0


class LogisticsRouteOut(LogisticsRouteIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
