"""Modèles Enterprise Suite — Phases P3, P4, P5."""
from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, Integer, String, Text

from app.database import Base


# ——— P3 Stock avancé ———
class StockLot(Base):
    __tablename__ = "stock_lots"
    id = Column(Integer, primary_key=True, index=True)
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    lot_number = Column(String, index=True)
    expiry_date = Column(Date, nullable=True)
    quantity = Column(Float, default=0)
    unit_cost = Column(Float, default=0)
    created_at = Column(String, default="")


class StockSerial(Base):
    __tablename__ = "stock_serials"
    id = Column(Integer, primary_key=True, index=True)
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    serial_number = Column(String, unique=True, index=True)
    status = Column(String, default="disponible")  # disponible, vendu, réservé
    location_code = Column(String, default="")


class StockLocation(Base):
    __tablename__ = "stock_locations"
    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), index=True)
    aisle = Column(String, default="")
    rack = Column(String, default="")
    bin_code = Column(String, default="")
    label = Column(String, default="")


class MobileScanLog(Base):
    __tablename__ = "mobile_scan_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    scan_type = Column(String, default="barcode")  # barcode | qrcode
    code = Column(String, index=True)
    stock_item_id = Column(Integer, nullable=True)
    action = Column(String, default="lookup")  # lookup | inventory | transfer
    payload_json = Column(Text, default="{}")
    created_at = Column(String, default="")


# ——— P3 Maintenance ———
class MaintenanceAsset(Base):
    __tablename__ = "maintenance_assets"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, index=True)
    name = Column(String, nullable=False)
    category = Column(String, default="machine")  # machine | véhicule | équipement
    location = Column(String, default="")
    vehicle_id = Column(Integer, nullable=True)
    status = Column(String, default="actif")
    last_service_at = Column(String, default="")
    next_service_at = Column(String, default="")


class MaintenanceOrder(Base):
    __tablename__ = "maintenance_orders"
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("maintenance_assets.id"), index=True)
    order_type = Column(String, default="preventive")  # preventive | corrective
    title = Column(String, default="")
    description = Column(Text, default="")
    status = Column(String, default="planifié")  # planifié, en_cours, terminé
    scheduled_date = Column(Date, nullable=True)
    completed_at = Column(String, default="")
    cost = Column(Float, default=0)
    created_at = Column(String, default="")


class BiometricPunch(Base):
    __tablename__ = "biometric_punches"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True)
    device_id = Column(String, default="")
    punch_type = Column(String, default="in")  # in | out
    punched_at = Column(String, default="")
    source = Column(String, default="api")


# ——— P4 Consolidation & BI ———
class ConsolidationRun(Base):
    __tablename__ = "consolidation_runs"
    id = Column(Integer, primary_key=True, index=True)
    period_label = Column(String, default="")
    fiscal_year = Column(Integer, default=2026)
    status = Column(String, default="draft")
    detail_json = Column(Text, default="{}")
    created_at = Column(String, default="")


class ReportDefinition(Base):
    __tablename__ = "report_definitions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    module = Column(String, default="invoices")
    columns_json = Column(Text, default='["number","date","amount"]')
    filters_json = Column(Text, default="{}")
    chart_type = Column(String, default="table")  # table | bar | line | pie
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_shared = Column(Boolean, default=False)
    created_at = Column(String, default="")


class AiInsight(Base):
    __tablename__ = "ai_insights"
    id = Column(Integer, primary_key=True, index=True)
    insight_type = Column(String, index=True)
    title = Column(String, default="")
    summary = Column(Text, default="")
    payload_json = Column(Text, default="{}")
    created_at = Column(String, default="")


class SecurityAlert(Base):
    __tablename__ = "security_alerts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    alert_type = Column(String, default="suspicious_login")
    ip_address = Column(String, default="")
    detail = Column(Text, default="")
    status = Column(String, default="open")
    created_at = Column(String, default="")


# ——— P5 Écosystème ———
class SupplierPortalAccess(Base):
    __tablename__ = "supplier_portal_access"
    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), index=True)
    token = Column(String, unique=True, index=True)
    expires_at = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default="")


class DocumentFolder(Base):
    __tablename__ = "document_folders"
    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("document_folders.id"), nullable=True)
    name = Column(String, nullable=False)
    entity_type = Column(String, default="")  # client | supplier | invoice | global
    entity_id = Column(Integer, nullable=True)
    created_at = Column(String, default="")


class DocumentFile(Base):
    __tablename__ = "document_files"
    id = Column(Integer, primary_key=True, index=True)
    folder_id = Column(Integer, ForeignKey("document_folders.id"), nullable=True)
    filename = Column(String, default="")
    mime_type = Column(String, default="")
    size_bytes = Column(Integer, default=0)
    storage_path = Column(String, default="")
    ocr_status = Column(String, default="none")
    ocr_result_json = Column(Text, default="")
    tags = Column(String, default="")
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, default="")


class MarketingCampaignRun(Base):
    __tablename__ = "marketing_campaign_runs"
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, nullable=True)
    channel = Column(String, default="email")  # email | sms | whatsapp
    subject = Column(String, default="")
    body = Column(Text, default="")
    recipients_count = Column(Integer, default=0)
    opens = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    status = Column(String, default="draft")
    sent_at = Column(String, default="")


class ApiConnector(Base):
    __tablename__ = "api_connectors"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    connector_type = Column(String, default="rest")  # rest | webhook | mobile_money | bank
    config_json = Column(Text, default="{}")
    is_active = Column(Boolean, default=True)
    last_sync_at = Column(String, default="")


class EsignRequest(Base):
    __tablename__ = "esign_requests"
    id = Column(Integer, primary_key=True, index=True)
    document_type = Column(String, default="quote")
    document_id = Column(Integer)
    signer_email = Column(String, default="")
    signer_name = Column(String, default="")
    status = Column(String, default="pending")  # pending | signed | rejected
    provider = Column(String, default="internal")
    signing_token = Column(String, unique=True, index=True, default="")
    provider_ref = Column(String, default="")
    signing_url = Column(String, default="")
    signed_at = Column(String, default="")
    created_at = Column(String, default="")
