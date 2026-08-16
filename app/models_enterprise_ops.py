"""Modèles enterprise — RH étendu, CRM commercial, logistique transport."""
from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, Text

from app.database import Base


class HrDepartment(Base):
    __tablename__ = "hr_departments"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, default="")
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("hr_departments.id"), nullable=True)
    manager_name = Column(String, default="")
    budget = Column(Float, default=0)
    headcount_target = Column(Integer, default=0)
    status = Column(String, default="actif")


class HrContract(Base):
    __tablename__ = "hr_contracts"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    employee_name = Column(String, default="")
    contract_type = Column(String, default="CDI")
    start_date = Column(Date)
    end_date = Column(Date)
    salary = Column(Float, default=0)
    status = Column(String, default="actif")
    notes = Column(Text, default="")


class HrBonus(Base):
    __tablename__ = "hr_bonuses"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    employee_name = Column(String, default="")
    label = Column(String, default="Prime")
    amount = Column(Float, default=0)
    period_month = Column(Integer, default=1)
    period_year = Column(Integer, default=2026)
    status = Column(String, default="prévu")


class HrRecruitment(Base):
    __tablename__ = "hr_recruitments"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    department = Column(String, default="")
    status = Column(String, default="ouvert")
    candidates_count = Column(Integer, default=0)
    opened_at = Column(Date)
    salary_min = Column(Float, default=0)
    salary_max = Column(Float, default=0)
    notes = Column(Text, default="")


class HrEvaluation(Base):
    __tablename__ = "hr_evaluations"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    employee_name = Column(String, default="")
    period = Column(String, default="")
    score = Column(Float, default=0)
    reviewer = Column(String, default="")
    status = Column(String, default="brouillon")
    goals = Column(Text, default="")
    notes = Column(Text, default="")


class HrTrainingPlan(Base):
    __tablename__ = "hr_training_plans"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    trainer = Column(String, default="")
    start_date = Column(Date)
    end_date = Column(Date)
    participants = Column(Integer, default=0)
    budget = Column(Float, default=0)
    status = Column(String, default="planifié")


class CrmLead(Base):
    __tablename__ = "crm_leads"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    company = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    source = Column(String, default="")
    stage = Column(String, default="nouveau")
    amount = Column(Float, default=0)
    owner = Column(String, default="")
    sales_rep_id = Column(Integer, nullable=True)
    status = Column(String, default="actif")
    notes = Column(Text, default="")


class CrmActivity(Base):
    __tablename__ = "crm_activities"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    lead_id = Column(Integer, ForeignKey("crm_leads.id"), nullable=True)
    client_id = Column(Integer, nullable=True)
    deal_id = Column(Integer, nullable=True)
    activity_type = Column(String, default="appel")
    subject = Column(String, default="")
    due_date = Column(Date)
    status = Column(String, default="à faire")
    notes = Column(Text, default="")


class CrmCampaign(Base):
    __tablename__ = "crm_campaigns"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    channel = Column(String, default="")
    budget = Column(Float, default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    leads_count = Column(Integer, default=0)
    status = Column(String, default="active")


class LogisticsVehicle(Base):
    __tablename__ = "logistics_vehicles"
    id = Column(Integer, primary_key=True, index=True)
    plate = Column(String, unique=True)
    brand = Column(String, default="")
    model = Column(String, default="")
    year = Column(Integer, default=0)
    capacity_kg = Column(Float, default=0)
    fuel_type = Column(String, default="diesel")
    status = Column(String, default="disponible")
    mileage = Column(Float, default=0)
    cost_per_km = Column(Float, default=0)


class LogisticsDriver(Base):
    __tablename__ = "logistics_drivers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, default="")
    license_number = Column(String, default="")
    status = Column(String, default="actif")
    vehicle_id = Column(Integer, ForeignKey("logistics_vehicles.id"), nullable=True)


class LogisticsCarrier(Base):
    __tablename__ = "logistics_carriers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    contact = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    rating = Column(Float, default=0)
    status = Column(String, default="actif")


class LogisticsShipment(Base):
    __tablename__ = "logistics_shipments"
    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String, unique=True)
    origin = Column(String, default="")
    destination = Column(String, default="")
    vehicle_id = Column(Integer, ForeignKey("logistics_vehicles.id"), nullable=True)
    driver_id = Column(Integer, ForeignKey("logistics_drivers.id"), nullable=True)
    carrier_id = Column(Integer, ForeignKey("logistics_carriers.id"), nullable=True)
    status = Column(String, default="planifié")
    weight_kg = Column(Float, default=0)
    cost = Column(Float, default=0)
    scheduled_date = Column(Date)
    delivered_date = Column(Date)


class LogisticsRoute(Base):
    __tablename__ = "logistics_routes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    zone = Column(String, default="")
    distance_km = Column(Float, default=0)
    vehicle_id = Column(Integer, ForeignKey("logistics_vehicles.id"), nullable=True)
    stops_count = Column(Integer, default=0)
    status = Column(String, default="active")
    avg_duration_hours = Column(Float, default=0)
