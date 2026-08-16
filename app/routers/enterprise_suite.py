"""API Enterprise Suite — Phases P3, P4, P5."""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.models_enterprise_suite import (
    ApiConnector,
    DocumentFile,
    MaintenanceAsset,
    MaintenanceOrder,
    ReportDefinition,
    SecurityAlert,
    StockLocation,
    StockLot,
    StockSerial,
)
from app.services import enterprise_suite_service as svc
from app.upload_limits import read_bounded

router = APIRouter(prefix="/api/erp/suite", tags=["enterprise-suite"])
supplier_portal_router = APIRouter(prefix="/api/portal/supplier", tags=["portal-supplier"])


# ——— Schemas ———
class LotIn(BaseModel):
    stock_item_id: int
    warehouse_id: Optional[int] = None
    lot_number: str
    expiry_date: Optional[str] = None
    quantity: float = 0
    unit_cost: float = 0


class SerialIn(BaseModel):
    stock_item_id: int
    warehouse_id: Optional[int] = None
    serial_number: str
    status: str = "disponible"
    location_code: str = ""


class ScanIn(BaseModel):
    code: str


class MaintenanceAssetIn(BaseModel):
    code: str
    name: str
    category: str = "machine"
    location: str = ""
    next_service_at: str = ""


class MaintenanceOrderIn(BaseModel):
    asset_id: int
    order_type: str = "preventive"
    title: str = ""
    description: str = ""
    scheduled_date: Optional[str] = None


class BiometricIn(BaseModel):
    employee_id: int
    device_id: str = ""
    punch_type: str = "in"


class ReportDefIn(BaseModel):
    name: str
    module: str = "invoices"
    columns_json: str = '["number","date","amount"]'
    filters_json: str = "{}"
    chart_type: str = "table"


class CurrencyConvertIn(BaseModel):
    amount: float
    from_code: str = "XOF"
    to_code: str = "EUR"


class SupplierTokenIn(BaseModel):
    supplier_id: int
    days: int = 90


class FolderIn(BaseModel):
    name: str
    entity_type: str = ""
    entity_id: Optional[int] = None


class CampaignIn(BaseModel):
    channel: str = "email"
    subject: str = ""
    body: str = ""
    recipients: int = 0
    recipient_emails: Optional[List[str]] = None
    recipient_phones: Optional[List[str]] = None
    client_ids: Optional[List[int]] = None


class EsignIn(BaseModel):
    document_type: str = "quote"
    document_id: int
    signer_email: str = ""
    signer_name: str = ""
    provider: str = "internal"


class TaskScheduleIn(BaseModel):
    date: Optional[str] = None


class ProjectProgressIn(BaseModel):
    progress: int


class KanbanMoveIn(BaseModel):
    status: str


GED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".doc", ".docx", ".xlsx", ".csv"}


class ConnectorIn(BaseModel):
    code: str
    name: str
    connector_type: str = "rest"
    config_json: str = "{}"


# ——— P3 Stock ———
@router.get("/stock/dashboard")
def stock_dashboard(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return svc.stock_advanced_dashboard(db)


@router.post("/stock/scan")
def stock_scan(body: ScanIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.scan_code(db, body.code, user.id)


@router.get("/stock/lots")
def list_lots(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    rows = db.query(StockLot).order_by(StockLot.id.desc()).limit(200).all()
    return [
        {
            "id": r.id, "stock_item_id": r.stock_item_id, "lot_number": r.lot_number,
            "quantity": r.quantity, "expiry_date": str(r.expiry_date) if r.expiry_date else "",
        }
        for r in rows
    ]


@router.post("/stock/lots")
def create_lot(body: LotIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    from datetime import date as d
    exp = d.fromisoformat(body.expiry_date) if body.expiry_date else None
    obj = svc.create_lot(db, {
        "stock_item_id": body.stock_item_id, "warehouse_id": body.warehouse_id,
        "lot_number": body.lot_number, "expiry_date": exp,
        "quantity": body.quantity, "unit_cost": body.unit_cost,
    })
    return {"id": obj.id, "lot_number": obj.lot_number}


@router.get("/stock/serials")
def list_serials(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    rows = db.query(StockSerial).order_by(StockSerial.id.desc()).limit(200).all()
    return [{"id": r.id, "serial_number": r.serial_number, "status": r.status, "stock_item_id": r.stock_item_id} for r in rows]


@router.post("/stock/serials")
def create_serial(body: SerialIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    obj = svc.create_serial(db, body.model_dump())
    return {"id": obj.id, "serial_number": obj.serial_number}


@router.get("/stock/locations")
def list_locations(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    rows = db.query(StockLocation).all()
    return [{"id": r.id, "warehouse_id": r.warehouse_id, "label": r.label, "bin_code": r.bin_code} for r in rows]


# ——— P3 Maintenance & RH ———
@router.get("/maintenance/dashboard")
def maintenance_dashboard(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return svc.maintenance_dashboard(db)


@router.post("/maintenance/assets")
def create_asset(body: MaintenanceAssetIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    obj = MaintenanceAsset(**body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id}


@router.post("/maintenance/orders")
def create_order(body: MaintenanceOrderIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    from datetime import date as d
    sched = d.fromisoformat(body.scheduled_date) if body.scheduled_date else None
    obj = MaintenanceOrder(
        asset_id=body.asset_id, order_type=body.order_type, title=body.title,
        description=body.description, scheduled_date=sched,
    )
    from app.services.enterprise_suite_service import _now
    obj.created_at = _now()
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id}


@router.post("/hr/biometric/punch")
def biometric_punch(body: BiometricIn, db: Session = Depends(get_db)):
    """Webhook pointeuse — auth optionnelle pour intégration terrain."""
    try:
        return svc.record_biometric_punch(db, body.employee_id, body.device_id, body.punch_type)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/hr/payroll/cnss")
def payroll_cnss(
    year: int = Query(...), month: int = Query(...),
    db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view")),
):
    return svc.payroll_cnss_summary(db, year, month)


# ——— P4 Consolidation, BI, IA ———
@router.post("/consolidation/run")
def consolidation_run(
    fiscal_year: int = Query(2026),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("comptarep", "view")),
):
    run = svc.run_consolidation(db, fiscal_year)
    import json
    return {"id": run.id, "status": run.status, "detail": json.loads(run.detail_json or "{}")}


@router.get("/consolidation/history")
def consolidation_history(db: Session = Depends(get_db), _: User = Depends(require_action("comptarep", "view"))):
    from app.models_enterprise_suite import ConsolidationRun
    import json
    rows = db.query(ConsolidationRun).order_by(ConsolidationRun.id.desc()).limit(20).all()
    return [{"id": r.id, "period": r.period_label, "status": r.status, "detail": json.loads(r.detail_json or "{}")} for r in rows]


@router.post("/currency/convert")
def currency_convert(body: CurrencyConvertIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    try:
        return svc.convert_currency(db, body.amount, body.from_code, body.to_code)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/i18n/{locale}")
def i18n_bundle(locale: str):
    return svc.get_i18n(locale)


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(ReportDefinition).order_by(ReportDefinition.id.desc()).all()
    return [{"id": r.id, "name": r.name, "module": r.module, "chart_type": r.chart_type} for r in rows]


@router.post("/reports")
def create_report(body: ReportDefIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.enterprise_suite_service import _now
    obj = ReportDefinition(**body.model_dump(), created_by=user.id, created_at=_now())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id}


@router.get("/reports/{rid}/execute")
def execute_report(rid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    try:
        return svc.execute_report(db, rid)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/ai/insights/refresh")
def refresh_ai(db: Session = Depends(get_db), _: User = Depends(require_action("dashboard", "view"))):
    insights = svc.generate_ai_insights(db)
    return [{"id": i.id, "type": i.insight_type, "title": i.title, "summary": i.summary} for i in insights]


@router.get("/ai/insights")
def list_ai(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from app.models_enterprise_suite import AiInsight
    rows = db.query(AiInsight).order_by(AiInsight.id.desc()).limit(20).all()
    return [{"id": r.id, "type": r.insight_type, "title": r.title, "summary": r.summary} for r in rows]


@router.post("/security/scan-logins")
def scan_logins(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    alerts = svc.detect_suspicious_logins(db)
    return {"new_alerts": len(alerts)}


@router.get("/security/alerts")
def security_alerts(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(SecurityAlert).order_by(SecurityAlert.id.desc()).limit(100).all()
    return [{"id": r.id, "type": r.alert_type, "ip": r.ip_address, "detail": r.detail, "status": r.status} for r in rows]


# ——— P5 Écosystème ———
@router.post("/supplier-portal/tokens")
def supplier_portal_token(body: SupplierTokenIn, db: Session = Depends(get_db), _: User = Depends(require_action("suppliers", "create"))):
    row = svc.create_supplier_portal_token(db, body.supplier_id, body.days)
    return {"token": row.token, "url": f"/portal-supplier.html?token={row.token}", "expires_at": row.expires_at}


@router.get("/ged/folders")
def ged_folders(
    entity_type: str = "", entity_id: Optional[int] = None,
    db: Session = Depends(get_db), _: User = Depends(get_current_user),
):
    return svc.ged_list_folders(db, entity_type, entity_id)


@router.post("/ged/folders")
def ged_create_folder(body: FolderIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    obj = svc.ged_create_folder(db, body.name, body.entity_type, body.entity_id)
    return {"id": obj.id, "name": obj.name}


@router.get("/ged/files")
def ged_files(folder_id: Optional[int] = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    import json
    q = db.query(DocumentFile)
    if folder_id:
        q = q.filter(DocumentFile.folder_id == folder_id)
    rows = q.order_by(DocumentFile.id.desc()).limit(200).all()
    out = []
    for r in rows:
        preview = ""
        if r.ocr_result_json:
            try:
                preview = json.loads(r.ocr_result_json).get("preview", "")
            except Exception:
                pass
        out.append({
            "id": r.id, "filename": r.filename, "folder_id": r.folder_id,
            "tags": r.tags, "ocr_status": r.ocr_status, "size_bytes": r.size_bytes,
            "preview": preview,
        })
    return out


@router.post("/ged/upload")
async def ged_upload(
    file: UploadFile = File(...),
    folder_id: Optional[int] = Query(None),
    tags: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in GED_EXT:
        raise HTTPException(400, f"Type non autorisé ({ext or 'sans extension'})")
    data = await read_bounded(file)
    obj = svc.upload_ged_file(
        db, file.filename or "document", data, file.content_type or "", user.id, folder_id, tags,
    )
    return {"id": obj.id, "filename": obj.filename, "size_bytes": obj.size_bytes}


@router.post("/ged/files/{fid}/ocr")
def ged_run_ocr(fid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return svc.run_ged_ocr(db, fid, user.id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/ged/files/{fid}/download")
def ged_download(fid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    doc = db.query(DocumentFile).filter(DocumentFile.id == fid).first()
    if not doc:
        raise HTTPException(404, "Fichier introuvable")
    path = svc.ged_storage_root() / doc.storage_path
    if not path.is_file():
        raise HTTPException(404, "Fichier physique manquant")
    return FileResponse(path, filename=doc.filename, media_type=doc.mime_type or "application/octet-stream")


@router.get("/projects/board")
def projects_board(db: Session = Depends(get_db), _: User = Depends(require_action("projects", "view"))):
    return svc.project_board(db)


@router.patch("/projects/tasks/{tid}/kanban")
def move_task_kanban(
    tid: int, body: KanbanMoveIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "update")),
):
    try:
        return svc.move_task_kanban(db, tid, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.patch("/projects/tasks/{tid}/schedule")
def schedule_task(
    tid: int, body: TaskScheduleIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "update")),
):
    try:
        return svc.update_task_schedule(db, tid, body.date)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.patch("/projects/{pid}/progress")
def project_progress(
    pid: int, body: ProjectProgressIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "update")),
):
    try:
        return svc.update_project_progress(db, pid, body.progress)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/logistics/summary")
def logistics_summary(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return svc.logistics_summary(db)


@router.get("/marketing/clients-preview")
def marketing_clients_preview(db: Session = Depends(get_db), _: User = Depends(require_action("clients", "view"))):
    from app.models import Client
    rows = db.query(Client).filter(Client.email != "").limit(100).all()
    return [{"id": c.id, "name": c.name, "email": c.email, "phone": c.phone or ""} for c in rows]


@router.post("/marketing/campaigns")
def launch_campaign(body: CampaignIn, db: Session = Depends(get_db), _: User = Depends(require_action("clients", "create"))):
    return svc.launch_marketing_campaign(
        db, body.channel, body.subject, body.body, body.recipients,
        recipient_emails=body.recipient_emails,
        recipient_phones=body.recipient_phones,
        client_ids=body.client_ids,
    )


@router.get("/marketing/campaigns")
def list_campaigns(db: Session = Depends(get_db), _: User = Depends(require_action("clients", "view"))):
    from app.models_enterprise_suite import MarketingCampaignRun
    rows = db.query(MarketingCampaignRun).order_by(MarketingCampaignRun.id.desc()).limit(50).all()
    return [{"id": r.id, "channel": r.channel, "subject": r.subject, "recipients": r.recipients_count, "status": r.status} for r in rows]


@router.get("/connectors")
def list_connectors(db: Session = Depends(get_db), _: User = Depends(require_action("settings", "view"))):
    svc.seed_connectors(db)
    rows = db.query(ApiConnector).all()
    return [{"id": r.id, "code": r.code, "name": r.name, "type": r.connector_type, "active": r.is_active} for r in rows]


@router.post("/connectors")
def create_connector(body: ConnectorIn, db: Session = Depends(get_db), _: User = Depends(require_action("settings", "create"))):
    if db.query(ApiConnector).filter(ApiConnector.code == body.code).first():
        raise HTTPException(400, "Code déjà utilisé")
    obj = ApiConnector(**body.model_dump(), is_active=True)
    db.add(obj)
    db.commit()
    return {"id": obj.id}


@router.get("/esign/providers")
def esign_providers(_: User = Depends(get_current_user)):
    from app.services.esign_service import PROVIDERS
    return [{"code": k, "label": v["label"]} for k, v in PROVIDERS.items()]


@router.post("/esign/requests")
def esign_request(body: EsignIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    obj = svc.create_esign_request(
        db, body.document_type, body.document_id,
        body.signer_email, body.signer_name, body.provider,
    )
    return {
        "id": obj.id, "status": obj.status, "provider": obj.provider,
        "signing_url": obj.signing_url, "signing_token": obj.signing_token,
    }


@router.get("/esign/requests")
def list_esign(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from app.models_enterprise_suite import EsignRequest
    rows = db.query(EsignRequest).order_by(EsignRequest.id.desc()).limit(50).all()
    return [
        {
            "id": r.id, "document_type": r.document_type, "document_id": r.document_id,
            "status": r.status, "signer": r.signer_name, "signed_at": r.signed_at,
            "provider": r.provider, "signing_url": r.signing_url,
        }
        for r in rows
    ]


@router.post("/esign/requests/{rid}/sign")
def esign_sign(rid: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    try:
        obj = svc.sign_esign_request(db, rid)
        return {"id": obj.id, "status": obj.status, "signed_at": obj.signed_at}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# ——— Portail fournisseur (public) ———
def _portal_supplier(db: Session, token: str):
    from app.models_enterprise_suite import SupplierPortalAccess
    from datetime import datetime, timezone
    row = db.query(SupplierPortalAccess).filter(
        SupplierPortalAccess.token == token,
        SupplierPortalAccess.is_active == True,  # noqa: E712
    ).first()
    if not row:
        raise HTTPException(401, "Token invalide")
    if row.expires_at and row.expires_at < datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"):
        raise HTTPException(401, "Token expiré")
    return row


@supplier_portal_router.get("/dashboard")
def supplier_dashboard(token: str = Query(...), db: Session = Depends(get_db)):
    from app.models_erp import Supplier, SupplierInvoice
    access = _portal_supplier(db, token)
    sup = db.query(Supplier).filter(Supplier.id == access.supplier_id).first()
    if not sup:
        raise HTTPException(404, "Fournisseur introuvable")
    invoices = db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == sup.id).order_by(SupplierInvoice.id.desc()).limit(50).all()
    total = sum(float(i.amount or 0) for i in invoices)
    paid = sum(float(i.paid or 0) for i in invoices)
    return {
        "supplier": {"id": sup.id, "name": sup.name, "email": sup.email},
        "invoices": [
            {
                "id": i.id, "number": i.number,
                "date": str(i.date) if i.date else "",
                "amount": i.amount, "paid": i.paid,
                "balance": round(float(i.amount or 0) - float(i.paid or 0), 2),
                "status": i.status,
            }
            for i in invoices
        ],
        "total_invoiced": total,
        "balance_due": round(total - paid, 2),
    }


# ——— Portail signature (public) ———
esign_portal_router = APIRouter(prefix="/api/portal/esign", tags=["portal-esign"])


@esign_portal_router.get("/status")
def esign_portal_status(token: str = Query(...), db: Session = Depends(get_db)):
    from app.services.esign_service import get_esign_by_token
    try:
        row = get_esign_by_token(db, token)
    except ValueError as e:
        raise HTTPException(401, str(e)) from e
    return {
        "id": row.id, "document_type": row.document_type, "document_id": row.document_id,
        "signer_name": row.signer_name, "signer_email": row.signer_email,
        "status": row.status, "provider": row.provider, "signed_at": row.signed_at,
    }


class PortalSignIn(BaseModel):
    token: str
    signer_name: str = ""


@esign_portal_router.post("/sign")
def esign_portal_sign(body: PortalSignIn, db: Session = Depends(get_db)):
    from app.services.esign_service import sign_by_token
    try:
        row = sign_by_token(db, body.token, body.signer_name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "status": row.status, "signed_at": row.signed_at}


class EsignWebhookIn(BaseModel):
    provider_ref: str
    status: str


@esign_portal_router.post("/webhook/{provider}")
def esign_webhook(provider: str, body: EsignWebhookIn, db: Session = Depends(get_db)):
    from app.services.esign_service import webhook_provider_update
    row = webhook_provider_update(db, provider, body.provider_ref, body.status)
    if not row:
        raise HTTPException(404, "Demande introuvable")
    return {"ok": True, "status": row.status}
