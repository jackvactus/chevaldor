"""
Peya Company ERP - Backend FastAPI
SARL multi-activités — Togo
"""
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel as PydanticBaseModel
from pathlib import Path
import json
import os
import uvicorn
import time

from app.database import engine, get_db, Base, SessionLocal
from app.models import (
    Client, Deal, Quote, Invoice, Project, Task,
    Training, Trainee, StockItem, StockMovement,
    Account, Transaction, ClientLedgerEntry,
    User, ImportBatch, Attachment, DocumentLine, Activity, CompanyProfile,
)
from app.migrate import run_migrations
from app.commercial_service import mark_overdue_invoices, next_document_number, next_quote_number, ensure_unique_document_number
from app import schemas, seed
from app.excel_clientele import detect_clientele_format, analyze_clientele
from app.excel_utils import _excel_str, _excel_float, _excel_int, _excel_date, _json_cell, _sample_rows
from app.import_service import import_clientele_board
from app.bootstrap import ensure_admin_user, ensure_company_profile, ensure_platform_defaults
from app.services.notify import create_app_notification
from app.middleware_auth import auth_middleware
from app.middleware_audit import audit_middleware
from app.auth import require_permission, get_current_user
from app.api_guards import require_action
from app.commercial_guards import (
    assert_invoice_deletable,
    assert_invoice_mutable,
    assert_quote_deletable,
    assert_quote_mutable,
)
from app.tenant_service import get_company_id, filter_by_company, get_entity_or_404, stamp_company, ensure_user_company
from app.services.audit_log import log_audit
import json
from app.routers.auth_users import router as auth_router, users_router, roles_router
from app.routers.imports_attachments import router as data_router
from app.routers.enhanced import router as enhanced_router
from app.routers.erp import router as erp_router
from app.routers.settings_extra import router as settings_extra_router
from app.routers.currencies import router as currencies_router
from app.routers.roles_rbac import router as roles_rbac_router
from app.routers.stock_advanced import router as stock_advanced_router
from app.routers.security_extra import router as security_router
from app.routers.enterprise import router as enterprise_router
from app.routers.demo_data import router as demo_data_router
from app.routers.syscohada import router as syscohada_router
from app.routers.finance_advanced import router as finance_advanced_router
from app.routers.operations_advanced import router as operations_advanced_router
from app.routers.hr_advanced import router as hr_advanced_router
from app.routers.commercial_advanced import router as commercial_advanced_router
from app.routers.logistics_advanced import router as logistics_advanced_router
from app.routers.accounting_advanced import router as accounting_advanced_router
from app.routers.business_suite import router as business_suite_router
from app.routers.recurrence_advanced import router as recurrence_router
from app.routers.platform import router as platform_router, portal_router as client_portal_router
from app.routers.treasury_p1 import router as treasury_p1_router
from app.routers.crm_p2 import router as crm_p2_router
from app.routers.enterprise_suite import router as enterprise_suite_router, supplier_portal_router, esign_portal_router
from app.routers.admin_metrics import router as admin_metrics_router
from app.routers.cms import public_router as cms_public_router, admin_router as cms_admin_router
from app.routers.cms_admin_ext import router as cms_admin_ext_router
from app.services.cms_service import CMS_MEDIA_ROOT, ensure_cms_seeded
from app.http_errors import (
    validation_exception_handler,
    integrity_exception_handler,
    generic_exception_handler,
)
from app.auth import decode_token, is_session_revoked
from app.services.notification_hub import hub

# Run migrations
run_migrations()

# Initialiser le module des récurrences
try:
    from app.migrations.recurrence_migrations import init_recurrence_module
    init_recurrence_module(engine)
except ImportError:
    pass
except Exception as e:
    print(f"[Startup] Erreur initialisation module récurrences: {str(e)}")

# Initialiser le scheduler pour auto-génération des factures récurrentes
try:
    from app.services.recurrence_scheduler import schedule_generation_with_apsched
    scheduler = schedule_generation_with_apsched()
    print("[Startup] RecurrenceScheduler initialisé")
except Exception as e:
    print(f"[Startup] Scheduler récurrences non disponible (APScheduler?): {str(e)}")

from app.auth import validate_jwt_secret_for_env
from app.server_config import docs_enabled, is_production

validate_jwt_secret_for_env()

try:
    from app.services.backup_scheduler import start_backup_scheduler
    start_backup_scheduler()
except Exception:
    pass

_docs_on = docs_enabled()
app = FastAPI(
    title="Peya Company ERP API",
    description="ERP Peya Company — multi-activités Togo (Lomé)",
    version="2.0.0",
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
)

app.middleware("http")(auth_middleware)
app.middleware("http")(audit_middleware)


@app.middleware("http")
async def request_timing_middleware(request: Request, call_next):
    """Mesure simple des temps de réponse (observabilité phase 3)."""
    from app.metrics_collector import record_request

    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    record_request(elapsed_ms=elapsed_ms, path=request.url.path, status=response.status_code)
    if elapsed_ms > 1200:
        print(f"[SLOW] {request.method} {request.url.path} -> {elapsed_ms:.2f}ms")
    path = request.url.path
    if path.startswith("/static/") and (path.endswith(".js") or path.endswith(".css")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path in ("/app", "/login", "/sw.js", "/manifest.webmanifest", "/offline.html"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

# CORS — PEYA_CORS_ORIGINS + hostname / IP serveur (voir app/server_config.py)
from app.server_config import build_cors_origins

_cors_origins = build_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(roles_router)
app.include_router(data_router)
app.include_router(enhanced_router)
app.include_router(erp_router)
app.include_router(settings_extra_router)
app.include_router(currencies_router)
app.include_router(roles_rbac_router)
app.include_router(stock_advanced_router)
app.include_router(security_router)
app.include_router(enterprise_router)
app.include_router(demo_data_router)
app.include_router(cms_public_router)
app.include_router(cms_admin_router)
app.include_router(cms_admin_ext_router)
app.include_router(syscohada_router)
app.include_router(finance_advanced_router)
app.include_router(operations_advanced_router)
app.include_router(hr_advanced_router)
app.include_router(commercial_advanced_router)
app.include_router(logistics_advanced_router)
app.include_router(accounting_advanced_router)
app.include_router(business_suite_router)
app.include_router(recurrence_router)
app.include_router(platform_router)
app.include_router(client_portal_router)
app.include_router(treasury_p1_router)
app.include_router(crm_p2_router)
app.include_router(enterprise_suite_router)
app.include_router(supplier_portal_router)
app.include_router(esign_portal_router)
app.include_router(admin_metrics_router)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.get("/api/public/region")
def public_region():
    """Configuration régionale affichée par le frontend."""
    from app.region_config import REGION
    return REGION


@app.get("/api/public/app-config")
def public_app_config():
    """URL publique, hostname et IP — pour liens frontend (Docker / production)."""
    from app.server_config import app_config_payload
    return app_config_payload()


@app.get("/api/health")
def api_health():
    """Diagnostic rapide (auth non requise si middleware l'autorise)."""
    payload = {"status": "ok"}
    if not is_production():
        from app.database import DB_PATH
        payload["db"] = str(DB_PATH)
        payload["db_exists"] = DB_PATH.is_file()
    return payload


@app.get("/api/status")
def api_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("dashboard", "view")),
):
    """État opérationnel de l'application (authentifié)."""
    return {
        "status": "ok",
        "clients": db.query(Client).count(),
        "invoices": db.query(Invoice).count(),
        "quotes": db.query(Quote).count(),
        "deals": db.query(Deal).count(),
        "projects": db.query(Project).count(),
    }


@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        ensure_admin_user(db)
        ensure_company_profile(db)
        ensure_platform_defaults(db)
        ensure_cms_seeded(db)
        from app.routers.business_suite import ensure_client_types_seeded
        ensure_client_types_seeded(db)
    finally:
        db.close()


@app.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", 0))
    except Exception:
        await websocket.close(code=4401)
        return
    db = SessionLocal()
    try:
        if is_session_revoked(db, payload):
            await websocket.close(code=4401)
            return
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            await websocket.close(code=4401)
            return
    finally:
        db.close()

    await hub.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(user_id, websocket)

# ============================================================
# DASHBOARD / KPI
# ============================================================

@app.get("/api/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    """KPIs principaux pour le tableau de bord"""
    from sqlalchemy import func
    from app.models_prefs import UserPreferences
    from app.services.currency_targets import build_target_currency_breakdown, pick_target_display

    # CA facturé (factures payées + envoyées)
    ca_total = db.query(func.coalesce(func.sum(Invoice.amount), 0)).scalar() or 0
    ca_paid = db.query(func.coalesce(func.sum(Invoice.paid), 0)).scalar() or 0
    ca_pending = ca_total - ca_paid

    # Clients
    clients_total = db.query(Client).count()
    clients_active = db.query(Client).filter(Client.status == "actif").count()

    # Projets
    projects_active = db.query(Project).filter(Project.status == "en cours").count()
    projects_total = db.query(Project).count()

    # Pipeline commercial
    pipeline = db.query(func.coalesce(func.sum(Deal.amount), 0)).filter(
        Deal.stage.in_(["lead", "qualified", "proposal", "negotiation"])
    ).scalar() or 0

    # Devis en attente
    quotes_pending = db.query(Quote).filter(Quote.status == "envoyé").count()

    # Factures en retard
    invoices_late = db.query(Invoice).filter(Invoice.status == "en retard").count()

    # Formation - jours facturés
    training_days = db.query(func.coalesce(func.sum(Training.duration), 0)).scalar() or 0

    # CA par pôle
    ca_by_pole = {}
    for pole in ["Consulting", "Formation", "Installations", "Développement", "Automatisation"]:
        amount = db.query(func.coalesce(func.sum(Project.billed), 0)).filter(
            Project.pole == pole
        ).scalar() or 0
        ca_by_pole[pole] = float(amount)

    from app.region_config import REGION

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    display_code = (getattr(prefs, "display_currency_code", None) if prefs else None) or "XOF"

    target_year1 = float(REGION.get("year1_ca_target_xof", 100_000_000))
    progress_pct = round((float(ca_total) / target_year1) * 100, 1) if target_year1 else 0
    target_currencies = build_target_currency_breakdown(db, target_year1)
    target_display = pick_target_display(target_currencies, display_code)

    return {
        "ca_total": float(ca_total),
        "ca_paid": float(ca_paid),
        "ca_pending": float(ca_pending),
        "ca_target": target_year1,
        "ca_target_base": target_year1,
        "ca_target_currency": "XOF",
        "ca_target_currencies": target_currencies,
        "ca_target_display": target_display,
        "display_currency_code": display_code,
        "ca_progress": progress_pct,
        "clients_total": clients_total,
        "clients_active": clients_active,
        "projects_active": projects_active,
        "projects_total": projects_total,
        "pipeline": float(pipeline),
        "quotes_pending": quotes_pending,
        "invoices_late": invoices_late,
        "training_days": training_days,
        "training_target": 32,  # cible médiane BP An 1
        "ca_by_pole": ca_by_pole,
    }


@app.get("/api/dashboard/cockpit")
def get_dashboard_cockpit(
    months: int = 12,
    period: str = "month",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    """Centre de pilotage — KPI, tendances, graphiques, activité."""
    from app.services.dashboard_cockpit import build_dashboard_cockpit

    months = max(3, min(24, months))
    return build_dashboard_cockpit(
        db, user_id=user.id, months=months,
        period=period, date_from=date_from, date_to=date_to,
    )


# ============================================================
# CALENDRIER
# ============================================================

@app.get("/api/calendar/events")
def list_calendar_events(
    start: str,
    end: str,
    categories: str = "",
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    from datetime import date as date_cls
    from app.services.calendar_service import CATEGORIES, collect_events

    start_d = date_cls.fromisoformat(start[:10])
    end_d = date_cls.fromisoformat(end[:10])
    cats = [c.strip() for c in categories.split(",") if c.strip()] or None
    events = collect_events(db, start_d, end_d, categories=cats, search=q.strip())
    return {"events": events, "categories": CATEGORIES}


@app.get("/api/calendar/stats")
def calendar_stats_api(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    from datetime import date as date_cls
    from app.services.calendar_service import calendar_stats, collect_events

    start_d = date_cls.fromisoformat(start[:10])
    end_d = date_cls.fromisoformat(end[:10])
    events = collect_events(db, start_d, end_d)
    return calendar_stats(db, events)


@app.post("/api/calendar/events")
def create_calendar_event(
    data: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    from datetime import date as date_cls
    from app.models_calendar import CalendarEvent
    from app.services.calendar_service import _custom_to_event

    start_d = date_cls.fromisoformat(str(data.get("start", ""))[:10])
    end_s = data.get("end") or data.get("start")
    end_d = date_cls.fromisoformat(str(end_s)[:10]) if end_s else start_d
    row = CalendarEvent(
        title=data.get("title", "Nouvel événement"),
        description=data.get("description", ""),
        category=data.get("category", "admin"),
        event_type=data.get("event_type", "meeting"),
        start_date=start_d,
        end_date=end_d,
        start_time=data.get("start_time", "09:00"),
        end_time=data.get("end_time", "10:00"),
        all_day=bool(data.get("all_day", True)),
        priority=data.get("priority", "normal"),
        owner=data.get("owner", user.full_name or user.email),
        status=data.get("status", "planifié"),
        participants_json=json.dumps(data.get("participants", [])),
        attachments_json=json.dumps(data.get("attachments", [])),
        comments_json=json.dumps(data.get("comments", [])),
        user_id=user.id,
        created_at=date_cls.today(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _custom_to_event(row)


@app.patch("/api/calendar/events/{event_id}")
def update_calendar_event(
    event_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    from datetime import date as date_cls
    from app.models_calendar import CalendarEvent
    from app.services.calendar_service import _custom_to_event

    row = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not row:
        raise HTTPException(404, "Événement introuvable")
    if row.user_id and row.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "Modification non autorisée")
    for key in ("title", "description", "category", "event_type", "priority", "owner", "status", "start_time", "end_time"):
        if key in data:
            setattr(row, key, data[key])
    if "start" in data:
        row.start_date = date_cls.fromisoformat(str(data["start"])[:10])
    if "end" in data:
        row.end_date = date_cls.fromisoformat(str(data["end"])[:10])
    if "all_day" in data:
        row.all_day = bool(data["all_day"])
    db.commit()
    db.refresh(row)
    return _custom_to_event(row)


@app.delete("/api/calendar/events/{event_id}")
def delete_calendar_event(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    from app.models_calendar import CalendarEvent

    row = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not row:
        raise HTTPException(404, "Événement introuvable")
    if row.user_id and row.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "Suppression non autorisée")
    db.delete(row)
    db.commit()
    return {"ok": True}


_CALENDAR_SOURCE_MODULE = {
    "invoice": "invoices",
    "deal": "deals",
    "supplier_invoice": "purchases",
    "project": "projects",
    "task": "projects",
    "quote": "quotes",
    "training": "trainings",
}


@app.post("/api/calendar/move")
def move_calendar_event(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.permissions import has_module_action
    from app.services.calendar_service import move_event

    module = _CALENDAR_SOURCE_MODULE.get(str(data.get("source") or ""))
    if module and not has_module_action(user.role, module, "update", db):
        raise HTTPException(403, f"Droits insuffisants ({module}.update)")

    ip = request.client.host if request.client else ""
    return move_event(db, data, user_id=user.id, user_email=user.email, ip=ip)


# ============================================================
# CLIENTS
# ============================================================

@app.get("/api/clients", response_model=List[schemas.ClientOut])
def list_clients(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "view")),
):
    cid = get_company_id(db, user)
    q = db.query(Client).order_by(Client.name)
    q = filter_by_company(q, Client, cid)
    if not include_archived and hasattr(Client, "is_archived"):
        q = q.filter((Client.is_archived == False) | (Client.is_archived.is_(None)))  # noqa: E712
    return q.offset(offset).limit(limit).all()

@app.post("/api/clients", response_model=schemas.ClientOut)
def create_client(
    data: schemas.ClientIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "create")),
):
    from app.services.auxiliary_account_service import ensure_client_auxiliary, set_client_account_code

    cid = get_company_id(db, user)
    requested_code = (data.account_code or "").strip()
    if requested_code and db.query(Client).filter(Client.account_code == requested_code).first():
        raise HTTPException(400, f"Le compte « {requested_code} » est déjà utilisé par un autre client")
    payload = data.model_dump()
    payload["account_code"] = ""  # posé ci-dessous, après création, pour créer l'entrée du plan comptable
    obj = Client(**payload)
    stamp_company(obj, cid)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    if requested_code:
        set_client_account_code(db, obj, requested_code)
    else:
        ensure_client_auxiliary(db, obj)
    db.commit()
    db.refresh(obj)
    create_app_notification(
        db,
        user_id=user.id,
        type_="success",
        title="Nouveau client",
        message=f"Client « {obj.name} » enregistré",
        category="crm",
    )
    db.commit()
    return obj

@app.get("/api/clients/{client_id}", response_model=schemas.ClientOut)
def get_client(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "view")),
):
    cid = get_company_id(db, user)
    return get_entity_or_404(db, Client, client_id, cid, "Client")

@app.put("/api/clients/{client_id}", response_model=schemas.ClientOut)
def update_client(
    client_id: int,
    data: schemas.ClientIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "update")),
):
    from app.services.auxiliary_account_service import ensure_client_auxiliary, set_client_account_code

    cid = get_company_id(db, user)
    obj = get_entity_or_404(db, Client, client_id, cid, "Client")
    old = json.dumps({"name": obj.name, "email": getattr(obj, "email", "")}, ensure_ascii=False)
    payload = data.model_dump()
    requested_code = (payload.pop("account_code", None) or "").strip()
    for k, v in payload.items():
        setattr(obj, k, v)
    if requested_code and requested_code != (obj.account_code or ""):
        if db.query(Client).filter(Client.account_code == requested_code, Client.id != obj.id).first():
            raise HTTPException(400, f"Le compte « {requested_code} » est déjà utilisé par un autre client")
        set_client_account_code(db, obj, requested_code)
    elif not obj.account_code:
        # Champ laissé vide sur un client qui n'a encore aucun compte — pas d'écrasement
        # d'un compte déjà attribué, seulement une attribution automatique de secours.
        ensure_client_auxiliary(db, obj)
    db.commit()
    db.refresh(obj)
    ip = request.client.host if request.client else ""
    log_audit(
        db,
        "update",
        "crm",
        "client",
        obj.id,
        obj.name,
        user.id,
        user.email,
        ip,
        old_value=old,
        new_value=json.dumps(jsonable_encoder(data.model_dump()), ensure_ascii=False)[:500],
    )
    db.commit()
    return obj

class ClientAccountCodeIn(PydanticBaseModel):
    code: str = ""

@app.patch("/api/clients/{client_id}/account-code", response_model=schemas.ClientOut)
def update_client_account_code(
    client_id: int,
    data: ClientAccountCodeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "update")),
):
    """Mise à jour ciblée du compte comptable client — utilisée par le champ « Compte client »
    du formulaire facture (auparavant lecture seule, non modifiable depuis cet écran) pour éviter
    de devoir renvoyer l'intégralité du payload client depuis un formulaire qui n'en a pas besoin."""
    from app.services.auxiliary_account_service import set_client_account_code

    cid = get_company_id(db, user)
    obj = get_entity_or_404(db, Client, client_id, cid, "Client")
    requested_code = (data.code or "").strip()
    if requested_code and requested_code != (obj.account_code or ""):
        if db.query(Client).filter(Client.account_code == requested_code, Client.id != obj.id).first():
            raise HTTPException(400, f"Le compte « {requested_code} » est déjà utilisé par un autre client")
        set_client_account_code(db, obj, requested_code)
        db.commit()
        db.refresh(obj)
    return obj

@app.delete("/api/clients/{client_id}")
def delete_client(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "delete")),
):
    from app.services.client_lifecycle_service import delete_or_archive_client

    ip = request.client.host if request.client else ""
    result = delete_or_archive_client(
        db, client_id, user_id=user.id, user_email=user.email, ip=ip,
        company_id=get_company_id(db, user),
    )
    if result["status"] == "missing":
        raise HTTPException(404, "Client introuvable")
    if result["status"] == "blocked":
        raise HTTPException(400, result["message"])
    db.commit()
    return {
        "ok": True,
        "archived": result["status"] == "archived",
        "deleted": result["status"] == "deleted",
        "analysis": result.get("analysis"),
        "message": result.get("message"),
    }


class BulkClientsAnalyzeIn(PydanticBaseModel):
    ids: List[int]


@app.post("/api/clients/bulk/analyze")
def bulk_clients_analyze(
    body: BulkClientsAnalyzeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "view")),
):
    """Analyse des liens plateforme avant suppression groupée."""
    from app.services.client_lifecycle_service import analyze_clients_bulk

    if not body.ids:
        raise HTTPException(400, "Aucun client sélectionné")
    return analyze_clients_bulk(db, body.ids, company_id=get_company_id(db, user))


class BulkClientsIn(PydanticBaseModel):
    ids: List[int]
    action: str
    status: Optional[str] = None
    segment: Optional[str] = None


@app.post("/api/clients/bulk")
def bulk_clients(
    body: BulkClientsIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "delete")),
):
    """Actions groupées sur les clients (archiver, statut, segment, suppression)."""
    if not body.ids:
        raise HTTPException(400, "Aucun client sélectionné")
    action = (body.action or "").strip().lower()
    valid = ("archive", "activate", "deactivate", "set_status", "set_segment", "delete")
    if action not in valid:
        raise HTTPException(400, "Action invalide")
    if action == "set_status" and body.status not in ("prospect", "actif", "inactif"):
        raise HTTPException(400, "Statut invalide")
    company_id = get_company_id(db, user)
    ip = request.client.host if request.client else ""
    processed = 0
    delete_results: list = []
    blocked: list = []
    for cid in body.ids:
        obj = filter_by_company(db.query(Client).filter(Client.id == cid), Client, company_id).first()
        if not obj:
            continue
        if action == "archive":
            if hasattr(obj, "is_archived"):
                obj.is_archived = True
            obj.status = "inactif"
            log_audit(db, "archive", "crm", "client", cid, obj.name, user.id, user.email, ip)
            processed += 1
        elif action == "activate":
            if hasattr(obj, "is_archived"):
                obj.is_archived = False
            obj.status = "actif"
            processed += 1
        elif action == "deactivate":
            obj.status = "inactif"
            processed += 1
        elif action == "set_status":
            obj.status = body.status
            processed += 1
        elif action == "set_segment":
            obj.segment = (body.segment or "").strip()
            processed += 1
        elif action == "delete":
            from app.services.client_lifecycle_service import delete_or_archive_client

            result = delete_or_archive_client(
                db, cid, user_id=user.id, user_email=user.email, ip=ip,
                company_id=company_id,
            )
            if result["status"] == "missing":
                continue
            if result["status"] == "blocked":
                blocked.append(result)
                continue
            delete_results.append(result)
            processed += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            400,
            "Suppression impossible : des données liées n'ont pas pu être détachées. "
            "Utilisez « Archiver » pour les clients avec historique commercial.",
        )
    if action == "delete":
        from app.services.client_lifecycle_service import format_bulk_delete_message

        msg = format_bulk_delete_message(delete_results)
        if blocked:
            msg += f" · {len(blocked)} bloqué(s)"
        return {
            "ok": True,
            "processed": processed,
            "deleted": sum(1 for r in delete_results if r.get("status") == "deleted"),
            "archived": sum(1 for r in delete_results if r.get("status") == "archived"),
            "blocked": blocked,
            "details": delete_results,
            "message": msg,
        }
    return {"ok": True, "processed": processed, "message": f"{processed} client(s) traité(s)"}


# ============================================================
# DEALS (Pipeline commercial)
# ============================================================

@app.get("/api/deals", response_model=List[schemas.DealOut])
def list_deals(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("deals", "view")),
):
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(Deal), Deal, cid).order_by(Deal.close_date)
    return q.offset(offset).limit(limit).all()

@app.post("/api/deals", response_model=schemas.DealOut)
def create_deal(
    data: schemas.DealIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("deals", "create")),
):
    cid = get_company_id(db, user)
    obj = Deal(**data.model_dump())
    stamp_company(obj, cid)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@app.put("/api/deals/{deal_id}", response_model=schemas.DealOut)
def update_deal(
    deal_id: int,
    data: schemas.DealIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("deals", "update")),
):
    cid = get_company_id(db, user)
    obj = get_entity_or_404(db, Deal, deal_id, cid, "Affaire")
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj

@app.delete("/api/deals/{deal_id}")
def delete_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("deals", "delete")),
):
    cid = get_company_id(db, user)
    obj = get_entity_or_404(db, Deal, deal_id, cid, "Affaire")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ============================================================
# QUOTES (Devis)
# ============================================================

@app.get("/api/quotes", response_model=List[schemas.QuoteOut])
def list_quotes(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "view")),
):
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(Quote), Quote, cid).order_by(Quote.date.desc())
    return q.offset(offset).limit(limit).all()

@app.get("/api/quotes/next-number")
def get_next_quote_number(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "create")),
):
    """Numéro de devis suggéré — le frontend l'appelle pour pré-remplir le formulaire au lieu de
    deviner à partir de la longueur du cache (source de doublons, voir §M2/§M6 CLAUDE.md)."""
    return {"number": next_quote_number(db, get_company_id(db, user))}

@app.post("/api/quotes", response_model=schemas.QuoteOut)
def create_quote(
    data: schemas.QuoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "create")),
):
    cid = get_company_id(db, user)
    cols = {c.key for c in Quote.__table__.columns}
    obj = Quote(**{k: v for k, v in data.model_dump().items() if k in cols})
    # Filet de sécurité anti-doublon : si le numéro fourni (pré-rempli côté client) est déjà pris
    # — cache périmé, création concurrente — on recalcule plutôt que de planter sur la contrainte
    # d'unicité (bug signalé par l'utilisateur le 2026-07-28, voir CLAUDE.md §M2).
    obj.number = ensure_unique_document_number(db, Quote, "Q", obj.number, cid)
    stamp_company(obj, cid)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    create_app_notification(
        db,
        user_id=user.id,
        type_="info",
        title=f"Devis {obj.number}",
        message="Nouveau devis créé",
        category="billing",
    )
    db.commit()
    return obj

@app.put("/api/quotes/{quote_id}", response_model=schemas.QuoteOut)
def update_quote(
    quote_id: int,
    data: schemas.QuoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "update")),
):
    obj = get_entity_or_404(db, Quote, quote_id, get_company_id(db, user), "Devis")
    assert_quote_mutable(obj, user, db)
    cols = {c.key for c in Quote.__table__.columns}
    for k, v in data.model_dump().items():
        if k in cols:
            setattr(obj, k, v)
    db.commit(); db.refresh(obj)
    return obj

@app.delete("/api/quotes/{quote_id}")
def delete_quote(
    quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "delete")),
):
    obj = get_entity_or_404(db, Quote, quote_id, get_company_id(db, user), "Devis")
    assert_quote_deletable(obj)
    db.query(DocumentLine).filter(DocumentLine.quote_id == quote_id).delete()
    db.delete(obj)
    db.commit()
    return {"ok": True}


class BulkQuotesIn(PydanticBaseModel):
    ids: List[int]
    action: str


@app.post("/api/quotes/bulk")
def bulk_quotes(
    body: BulkQuotesIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "delete")),
):
    if not body.ids:
        raise HTTPException(400, "Aucun devis sélectionné")
    action = (body.action or "").strip().lower()
    if action != "delete":
        raise HTTPException(400, "Action invalide")
    company_id = get_company_id(db, user)
    ip = request.client.host if request.client else ""
    processed = 0
    errors: List[str] = []
    for qid in body.ids:
        obj = filter_by_company(db.query(Quote).filter(Quote.id == qid), Quote, company_id).first()
        if not obj:
            errors.append(f"Devis #{qid} introuvable")
            continue
        try:
            assert_quote_deletable(obj)
            db.query(DocumentLine).filter(DocumentLine.quote_id == qid).delete()
            log_audit(db, "delete", "ventes", "quote", qid, obj.number or "", user.id, user.email, ip)
            db.delete(obj)
            processed += 1
        except HTTPException as e:
            errors.append(f"{obj.number or qid}: {e.detail}")
    db.commit()
    msg = f"{processed} devis supprimé(s)"
    if errors:
        msg += f" — {len(errors)} ignoré(s)"
    return {"ok": True, "processed": processed, "errors": errors, "message": msg}


# ============================================================
# INVOICES (Factures)
# ============================================================

@app.get("/api/invoices", response_model=List[schemas.InvoiceOut])
def list_invoices(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "view")),
):
    mark_overdue_invoices(db)
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(Invoice), Invoice, cid).order_by(Invoice.date.desc())
    if hasattr(Invoice, "is_archived"):
        q = q.filter((Invoice.is_archived == False) | (Invoice.is_archived.is_(None)))  # noqa: E712
    return q.offset(offset).limit(limit).all()

@app.get("/api/invoices/next-number")
def get_next_invoice_number(
    prefix: str = Query("F"),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    """Numéro de facture suggéré (même filet anti-doublon que /api/quotes/next-number)."""
    return {"number": next_document_number(db, Invoice, prefix, get_company_id(db, user))}

@app.post("/api/invoices", response_model=schemas.InvoiceOut)
def create_invoice(
    data: schemas.InvoiceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    from app.date_service import apply_invoice_dates, compute_due_date, stamp_create

    cid = get_company_id(db, user)
    payload = data.model_dump()
    _num_prefix = {"proforma": "PF", "deposit": "AC", "credit_note": "A"}.get(payload.get("doc_type") or "invoice", "F")
    payload["number"] = ensure_unique_document_number(db, Invoice, _num_prefix, payload.get("number"), cid)
    if payload.get("client_id") and not payload.get("vat_rate"):
        from app.services.smart_context_service import resolve_client_defaults
        defaults = resolve_client_defaults(db, payload["client_id"])
        if defaults.get("vat_pct") is not None:
            payload["vat_rate"] = defaults["vat_pct"]
        if defaults.get("commission_pct") is not None and not payload.get("commission_pct"):
            payload["commission_pct"] = defaults["commission_pct"]
    if payload.get("date") and not payload.get("due_date"):
        payload["due_date"] = compute_due_date(payload["date"], payload.get("payment_terms_days", 30))
    obj = Invoice(**payload)
    stamp_company(obj, cid)
    stamp_create(obj, user)
    apply_invoice_dates(obj, payload, is_create=True)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    create_app_notification(
        db,
        user_id=user.id,
        type_="info",
        title=f"Facture {obj.number}",
        message=f"Montant {obj.amount or 0}",
        category="billing",
    )
    db.commit()
    if obj.status in ("envoyée", "payée", "en retard"):
        from app.services.accounting_hooks import dispatch_invoice_posting
        dispatch_invoice_posting(db, obj)
    return obj

@app.put("/api/invoices/{invoice_id}", response_model=schemas.InvoiceOut)
def update_invoice(
    invoice_id: int,
    data: schemas.InvoiceIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "update")),
):
    obj = get_entity_or_404(db, Invoice, invoice_id, get_company_id(db, user), "Facture")
    assert_invoice_mutable(obj, user, db)
    old_status = obj.status
    old = json.dumps({"number": obj.number, "status": obj.status, "amount": obj.amount}, ensure_ascii=False)
    payload = data.model_dump()
    if payload.get("date") and not payload.get("due_date"):
        from app.date_service import compute_due_date
        payload["due_date"] = compute_due_date(payload["date"], payload.get("payment_terms_days", 30))
    for k, v in payload.items():
        setattr(obj, k, v)
    from app.date_service import apply_invoice_dates, stamp_update
    stamp_update(obj, user)
    apply_invoice_dates(obj, payload)
    db.commit()
    db.refresh(obj)
    if obj.status in ("envoyée", "payée", "en retard") and (
        old_status == "brouillon" or not getattr(obj, "journal_entry_id", None)
    ):
        from app.services.accounting_hooks import dispatch_invoice_posting
        dispatch_invoice_posting(db, obj)
    ip = request.client.host if request.client else ""
    log_audit(
        db,
        "update",
        "ventes",
        "invoice",
        obj.id,
        obj.number or "",
        user.id,
        user.email,
        ip,
        old_value=old,
        new_value=json.dumps(jsonable_encoder(data.model_dump()), ensure_ascii=False)[:500],
    )
    return obj

@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "delete")),
):
    obj = get_entity_or_404(db, Invoice, invoice_id, get_company_id(db, user), "Facture")
    assert_invoice_deletable(obj)
    from app.services.accounting_hooks import unpost_source
    unpost_source(db, "invoice", invoice_id)
    db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice_id).delete()
    ip = request.client.host if request.client else ""
    log_audit(db, "delete", "ventes", "invoice", invoice_id, obj.number or "", user.id, user.email, ip)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@app.post("/api/invoices/{invoice_id}/duplicate", response_model=schemas.InvoiceOut)
def duplicate_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    from datetime import date as _date
    from app.commercial_service import _next_invoice_number
    from app.date_service import stamp_create

    src = get_entity_or_404(db, Invoice, invoice_id, get_company_id(db, user), "Facture")
    prefix = {"proforma": "PF", "deposit": "AC"}.get(getattr(src, "doc_type", "invoice") or "invoice", "F")
    obj = Invoice(
        number=_next_invoice_number(db, prefix),
        client_id=src.client_id,
        project_id=src.project_id,
        date=_date.today(),
        due_date=src.due_date,
        amount=src.amount,
        vat_rate=src.vat_rate,
        paid=0,
        status="brouillon",
        doc_type=getattr(src, "doc_type", "invoice") or "invoice",
        delivery_date=getattr(src, "delivery_date", None),
        discount_pct=getattr(src, "discount_pct", 0) or 0,
        commission_pct=getattr(src, "commission_pct", 0) or 0,
        withholding_pct=getattr(src, "withholding_pct", 0) or 0,
        notes=f"Copie de {src.number}",
        description=getattr(src, "description", "") or "",
        company_id=src.company_id,
    )
    stamp_create(obj, user)
    db.add(obj)
    db.flush()
    for ln in db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice_id).all():
        db.add(DocumentLine(
            invoice_id=obj.id,
            position=ln.position,
            description=ln.description,
            quantity=ln.quantity,
            unit_price=ln.unit_price,
            vat_rate=ln.vat_rate,
            discount_pct=getattr(ln, "discount_pct", 0) or 0,
            product_type=getattr(ln, "product_type", "SERVICE"),
            stock_item_id=ln.stock_item_id,
            account_id=ln.account_id,
        ))
    db.commit()
    db.refresh(obj)
    return obj


class BulkInvoicesIn(PydanticBaseModel):
    ids: List[int]
    action: str


@app.post("/api/invoices/bulk")
def bulk_invoices(
    body: BulkInvoicesIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "delete")),
):
    if not body.ids:
        raise HTTPException(400, "Aucune facture sélectionnée")
    action = (body.action or "").strip().lower()
    if action not in ("delete", "cancel"):
        raise HTTPException(400, "Action invalide")
    company_id = get_company_id(db, user)
    ip = request.client.host if request.client else ""
    processed = 0
    errors: List[str] = []
    for iid in body.ids:
        obj = filter_by_company(db.query(Invoice).filter(Invoice.id == iid), Invoice, company_id).first()
        if not obj:
            errors.append(f"Facture #{iid} introuvable")
            continue
        try:
            if action == "delete":
                assert_invoice_deletable(obj)
                from app.services.accounting_hooks import unpost_source
                unpost_source(db, "invoice", iid)
                db.query(DocumentLine).filter(DocumentLine.invoice_id == iid).delete()
                log_audit(db, "delete", "ventes", "invoice", iid, obj.number or "", user.id, user.email, ip)
                db.delete(obj)
            elif action == "cancel":
                if obj.status == "brouillon":
                    errors.append(f"{obj.number or iid}: en brouillon — utilisez Supprimer")
                    continue
                obj.status = "annulée"
                log_audit(db, "cancel", "ventes", "invoice", iid, obj.number or "", user.id, user.email, ip)
            processed += 1
        except HTTPException as e:
            errors.append(f"{obj.number or iid}: {e.detail}")
    db.commit()
    labels = {"delete": "supprimée(s)", "cancel": "annulée(s)"}
    msg = f"{processed} facture(s) {labels.get(action, 'traitée(s)')}"
    if errors:
        msg += f" — {len(errors)} ignorée(s)"
    return {"ok": True, "processed": processed, "errors": errors, "message": msg}


# ============================================================
# PROJECTS
# ============================================================

@app.get("/api/projects", response_model=List[schemas.ProjectOut])
def list_projects(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("projects", "view")),
):
    cid = get_company_id(db, user)
    q = filter_by_company(db.query(Project), Project, cid).order_by(Project.start_date.desc())
    return q.offset(offset).limit(limit).all()

@app.post("/api/projects", response_model=schemas.ProjectOut)
def create_project(
    data: schemas.ProjectIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("projects", "create")),
):
    cid = get_company_id(db, user)
    obj = Project(**data.model_dump())
    stamp_company(obj, cid)
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.put("/api/projects/{project_id}", response_model=schemas.ProjectOut)
def update_project(
    project_id: int,
    data: schemas.ProjectIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "update")),
):
    obj = db.query(Project).filter(Project.id == project_id).first()
    if not obj: raise HTTPException(404)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj)
    return obj

@app.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "delete")),
):
    obj = db.query(Project).filter(Project.id == project_id).first()
    if not obj: raise HTTPException(404)
    db.query(Task).filter(Task.project_id == project_id).delete()
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ============================================================
# TASKS
# ============================================================

@app.get("/api/tasks", response_model=List[schemas.TaskOut])
def list_tasks(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "view")),
):
    q = db.query(Task)
    if project_id:
        q = q.filter(Task.project_id == project_id)
    return q.order_by(Task.date).all()

@app.post("/api/tasks", response_model=schemas.TaskOut)
def create_task(
    data: schemas.TaskIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "create")),
):
    obj = Task(**data.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.put("/api/tasks/{task_id}", response_model=schemas.TaskOut)
def update_task(
    task_id: int,
    data: schemas.TaskIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "update")),
):
    obj = db.query(Task).filter(Task.id == task_id).first()
    if not obj: raise HTTPException(404)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj)
    return obj

@app.delete("/api/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("projects", "delete")),
):
    obj = db.query(Task).filter(Task.id == task_id).first()
    if not obj: raise HTTPException(404)
    db.delete(obj); db.commit()
    return {"ok": True}


# ============================================================
# TRAININGS (Formations)
# ============================================================

@app.get("/api/trainings", response_model=List[schemas.TrainingOut])
def list_trainings(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "view")),
):
    return db.query(Training).order_by(Training.start_date.desc()).all()

@app.post("/api/trainings", response_model=schemas.TrainingOut)
def create_training(
    data: schemas.TrainingIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "create")),
):
    obj = Training(**data.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.put("/api/trainings/{tid}", response_model=schemas.TrainingOut)
def update_training(
    tid: int,
    data: schemas.TrainingIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "update")),
):
    obj = db.query(Training).filter(Training.id == tid).first()
    if not obj: raise HTTPException(404)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj)
    return obj

@app.delete("/api/trainings/{tid}")
def delete_training(
    tid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "delete")),
):
    obj = db.query(Training).filter(Training.id == tid).first()
    if not obj: raise HTTPException(404)
    db.delete(obj); db.commit()
    return {"ok": True}


# ============================================================
# TRAINEES (Stagiaires)
# ============================================================

@app.get("/api/trainees", response_model=List[schemas.TraineeOut])
def list_trainees(
    training_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "view")),
):
    q = db.query(Trainee)
    if training_id:
        q = q.filter(Trainee.training_id == training_id)
    return q.all()

@app.post("/api/trainees", response_model=schemas.TraineeOut)
def create_trainee(
    data: schemas.TraineeIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "create")),
):
    obj = Trainee(**data.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.put("/api/trainees/{tid}", response_model=schemas.TraineeOut)
def update_trainee(
    tid: int,
    data: schemas.TraineeIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "update")),
):
    obj = db.query(Trainee).filter(Trainee.id == tid).first()
    if not obj: raise HTTPException(404)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj)
    return obj

@app.delete("/api/trainees/{tid}")
def delete_trainee(
    tid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("trainings", "delete")),
):
    obj = db.query(Trainee).filter(Trainee.id == tid).first()
    if not obj: raise HTTPException(404)
    db.delete(obj); db.commit()
    return {"ok": True}


# ============================================================
# STOCK
# ============================================================

@app.get("/api/stock", response_model=List[schemas.StockItemOut])
def list_stock(
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("stock", "view")),
):
    return db.query(StockItem).order_by(StockItem.name).offset(offset).limit(limit).all()

@app.post("/api/stock", response_model=schemas.StockItemOut)
def create_stock(
    data: schemas.StockItemIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("stock", "create")),
):
    from app.services.stock_service import stamp_item_created
    obj = StockItem(**data.model_dump())
    stamp_item_created(obj)
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.put("/api/stock/{sid}", response_model=schemas.StockItemOut)
def update_stock(
    sid: int,
    data: schemas.StockItemIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("stock", "update")),
):
    from app.services.stock_service import stamp_item_updated
    obj = db.query(StockItem).filter(StockItem.id == sid).first()
    if not obj: raise HTTPException(404)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    stamp_item_updated(obj)
    db.commit(); db.refresh(obj)
    return obj

@app.delete("/api/stock/{sid}")
def delete_stock(
    sid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "delete")),
):
    from app.services.stock_service import delete_stock_item

    try:
        result = delete_stock_item(db, sid, user_id=user.id, user_email=user.email)
    except ValueError as e:
        raise HTTPException(404, str(e))
    db.commit()
    return result


@app.get("/api/stock-movements", response_model=List[schemas.StockMovementOut])
def list_movements(
    item_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("stock", "view")),
):
    q = db.query(StockMovement)
    if item_id:
        q = q.filter(StockMovement.item_id == item_id)
    return q.order_by(StockMovement.date.desc()).all()

@app.post("/api/stock-movements", response_model=schemas.StockMovementOut)
def create_movement(
    data: schemas.StockMovementIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "update")),
):
    from app.services.stock_service import apply_movement
    try:
        mov = apply_movement(
            db,
            item_id=data.item_id,
            movement_type=data.type,
            quantity=data.quantity,
            reason=data.reason,
            project_id=data.project_id,
            notes=data.notes,
            user_id=user.id,
            user_email=user.email,
            movement_kind=data.reason or data.type,
        )
        db.commit()
        db.refresh(mov)
        return mov
    except ValueError as e:
        raise HTTPException(400, str(e))


# ============================================================
# ACCOUNTING (Comptabilité simplifiée)
# ============================================================

@app.get("/api/accounts", response_model=List[schemas.AccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("accounting", "view")),
):
    return db.query(Account).order_by(Account.code).all()

@app.post("/api/accounts", response_model=schemas.AccountOut)
def create_account(
    data: schemas.AccountIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("accounting", "create")),
):
    obj = Account(**data.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj


@app.get("/api/transactions", response_model=List[schemas.TransactionOut])
def list_transactions(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    return db.query(Transaction).order_by(Transaction.date.desc()).all()

@app.post("/api/transactions", response_model=schemas.TransactionOut)
def create_transaction(
    data: schemas.TransactionIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    obj = Transaction(**data.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.put("/api/transactions/{tid}", response_model=schemas.TransactionOut)
def update_transaction(
    tid: int,
    data: schemas.TransactionIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "update")),
):
    obj = db.query(Transaction).filter(Transaction.id == tid).first()
    if not obj: raise HTTPException(404)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj)
    return obj

@app.delete("/api/transactions/{tid}")
def delete_transaction(
    tid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "delete")),
):
    obj = db.query(Transaction).filter(Transaction.id == tid).first()
    if not obj: raise HTTPException(404)
    db.delete(obj); db.commit()
    return {"ok": True}


@app.get("/api/accounting/summary")
def accounting_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("accounting", "view")),
):
    """Synthèse comptable — journal SYSCOHADA + ventilation par catégories pour graphiques."""
    from collections import defaultdict

    from app.models_erp import JournalEntry, JournalLine
    from app.services.accounting_reports import compte_de_resultat

    cr = compte_de_resultat(db)
    produits = charges = 0.0
    for ln in cr.get("lines", []):
        label = (ln.get("label") or "").lower()
        amt = float(ln.get("amount", 0) or 0)
        if "produit" in label:
            produits = amt
        elif "charge" in label and "constatée" not in label:
            charges = amt

    je_count = db.query(JournalEntry).filter(JournalEntry.status == "validée").count()
    source = "journal" if je_count > 0 else "transactions"
    result = float(produits - charges) if je_count > 0 else float(cr.get("net_result", 0) or 0)

    # Ventilation classes 6/7 pour histogrammes Comptabilité
    prod_by: dict[str, float] = defaultdict(float)
    chg_by: dict[str, float] = defaultdict(float)
    CLASS_LABELS = {
        "60": "Achats", "61": "Services extérieurs", "62": "Autres services",
        "63": "Impôts & taxes", "64": "Charges de personnel", "65": "Autres charges",
        "66": "Charges financières", "67": "Charges HAO", "68": "Dotations",
        "70": "Ventes", "71": "Production immobilisée", "72": "Production stockée",
        "75": "Autres produits", "76": "Produits financiers", "77": "Produits HAO",
        "78": "Reprises",
    }
    lines = (
        db.query(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(JournalEntry.status == "validée")
        .all()
    )
    for jl, _je in lines:
        code = (jl.account_code or "").strip()
        if not code:
            continue
        prefix2 = code[:2]
        label = CLASS_LABELS.get(prefix2) or (f"Classe {code[0]}" if code else "Autre")
        if code.startswith("7"):
            amt = float(jl.credit or 0) - float(jl.debit or 0)
            if amt > 0:
                prod_by[label] += amt
        elif code.startswith("6"):
            amt = float(jl.debit or 0) - float(jl.credit or 0)
            if amt > 0:
                chg_by[label] += amt

    # Repli transactions si journal vide
    if not prod_by and not chg_by:
        for t in db.query(Transaction).all():
            cat = (t.category or "Autre").strip() or "Autre"
            if t.type == "produit":
                prod_by[cat] += float(t.amount or 0)
            elif t.type == "charge":
                chg_by[cat] += float(t.amount or 0)

    products_by_category = sorted(
        [{"cat": k, "amount": round(v, 2)} for k, v in prod_by.items()],
        key=lambda x: -x["amount"],
    )[:12]
    charges_by_category = sorted(
        [{"cat": k, "amount": round(v, 2)} for k, v in chg_by.items()],
        key=lambda x: -x["amount"],
    )[:12]

    # Taux togolais réel de l'IS (Code Général des Impôts, art. 1151/1157) : 27% du
    # bénéfice imposable, taux unique — pas de barème progressif.
    is_tax = 0.0 if result <= 0 else result * 0.27
    net = result - is_tax
    return {
        "products": produits,
        "produits": produits,
        "charges": charges,
        "result_before_tax": result,
        "resultat": result,
        "corporate_tax": is_tax,
        "net_result": net,
        "resultat_net": net,
        "margin": round((result / produits * 100) if produits else 0, 1),
        "source": source,
        "journal_entries": je_count,
        "products_by_category": products_by_category,
        "charges_by_category": charges_by_category,
    }


# ============================================================
# SEED / RESET
# ============================================================

from pydantic import BaseModel as PydanticBaseModel


CLIENTELE_SEGMENT = "Clientèle PC"
DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_CLIENTELE_FILE = DATA_DIR / "clientele_pc.xlsx"


# ============================================================
# CLIENTÈLE PC
# ============================================================

def _get_clientele_client(db: Session, client_id: int) -> Client:
    obj = db.query(Client).filter(
        Client.id == client_id,
        Client.segment == CLIENTELE_SEGMENT,
    ).first()
    if not obj:
        raise HTTPException(404, "Client clientèle introuvable")
    return obj


def _recalc_client_soldes(db: Session, client_id: int):
    """Recalcule les soldes cumulés après modification des mouvements."""
    entries = db.query(ClientLedgerEntry).filter(
        ClientLedgerEntry.client_id == client_id
    ).order_by(ClientLedgerEntry.date, ClientLedgerEntry.id).all()
    prev = 0.0
    for entry in entries:
        prev = prev + entry.commande - entry.remboursement
        entry.solde = prev


def _clientele_summary_item(client: Client, entries: list) -> schemas.ClienteleSummaryItem:
    last_solde = entries[-1].solde if entries else 0.0
    return schemas.ClienteleSummaryItem(
        client_id=client.id,
        name=client.name,
        phone=client.phone or "",
        email=client.email or "",
        city=client.city or "",
        status=client.status or "actif",
        notes=client.notes or "",
        total_commande=sum(e.commande for e in entries),
        total_remboursement=sum(e.remboursement for e in entries),
        solde_actuel=last_solde,
        nb_mouvements=sum(
            1 for e in entries if (e.commande or 0) > 0.01 or (e.remboursement or 0) > 0.01
        ),
    )


@app.get("/api/clientele/summary", response_model=List[schemas.ClienteleSummaryItem])
def clientele_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "view")),
):
    """Synthèse par client (totaux et solde actuel)."""
    clients = db.query(Client).filter(
        Client.segment == CLIENTELE_SEGMENT, Client.is_archived.isnot(True)
    ).order_by(Client.name).all()
    if not clients:
        return []

    client_ids = [c.id for c in clients]
    all_entries = db.query(ClientLedgerEntry).filter(
        ClientLedgerEntry.client_id.in_(client_ids)
    ).order_by(ClientLedgerEntry.date, ClientLedgerEntry.id).all()

    entries_by_client: dict[int, list] = {cid: [] for cid in client_ids}
    for entry in all_entries:
        entries_by_client[entry.client_id].append(entry)

    return [_clientele_summary_item(c, entries_by_client.get(c.id, [])) for c in clients]


@app.get("/api/clientele/dashboard", response_model=schemas.ClienteleDashboardOut)
def clientele_dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "view")),
):
    """Indicateurs agrégés Clientèle PC (soldes, reste à payer, recouvrement)."""
    clients = db.query(Client).filter(
        Client.segment == CLIENTELE_SEGMENT, Client.is_archived.isnot(True)
    ).order_by(Client.name).all()
    if not clients:
        return schemas.ClienteleDashboardOut()

    client_ids = [c.id for c in clients]
    all_entries = db.query(ClientLedgerEntry).filter(
        ClientLedgerEntry.client_id.in_(client_ids)
    ).order_by(ClientLedgerEntry.date, ClientLedgerEntry.id).all()

    entries_by_client: dict[int, list] = {cid: [] for cid in client_ids}
    for entry in all_entries:
        entries_by_client[entry.client_id].append(entry)

    summaries = [_clientele_summary_item(c, entries_by_client.get(c.id, [])) for c in clients]
    total_commande = sum(s.total_commande for s in summaries)
    total_remb = sum(s.total_remboursement for s in summaries)
    solde_net = sum(s.solde_actuel for s in summaries)
    reste_a_payer = sum(max(0.0, s.solde_actuel) for s in summaries)
    credits_client = sum(abs(min(0.0, s.solde_actuel)) for s in summaries)
    clients_a_relancer = sum(1 for s in summaries if s.solde_actuel > 0.01)
    clients_soldes = sum(1 for s in summaries if abs(s.solde_actuel) <= 0.01)

    dates = sorted({e.date for e in all_entries if e.date})
    top = sorted(
        [s for s in summaries if s.solde_actuel > 0.01],
        key=lambda x: x.solde_actuel,
        reverse=True,
    )[:8]

    return schemas.ClienteleDashboardOut(
        nb_clients=len(summaries),
        total_commande=round(total_commande, 2),
        total_remboursement=round(total_remb, 2),
        reste_a_payer=round(reste_a_payer, 2),
        credits_client=round(credits_client, 2),
        solde_net=round(solde_net, 2),
        clients_a_relancer=clients_a_relancer,
        clients_soldes=clients_soldes,
        taux_recouvrement=round((total_remb / total_commande * 100) if total_commande else 0, 1),
        panier_moyen=round(total_commande / len(summaries), 2) if summaries else 0,
        nb_mouvements=sum(s.nb_mouvements for s in summaries),
        date_min=dates[0].isoformat() if dates else None,
        date_max=dates[-1].isoformat() if dates else None,
        top_debiteurs=[
            schemas.ClienteleDebitorItem(
                client_id=s.client_id,
                name=s.name,
                solde_actuel=round(s.solde_actuel, 2),
                total_commande=round(s.total_commande, 2),
                total_remboursement=round(s.total_remboursement, 2),
                taux_recouvrement=round(
                    (s.total_remboursement / s.total_commande * 100) if s.total_commande else 0, 1
                ),
            )
            for s in top
        ],
    )


@app.get("/api/clientele/clients/{client_id}", response_model=schemas.ClienteleSummaryItem)
def get_clientele_client(
    client_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "view")),
):
    client = _get_clientele_client(db, client_id)
    entries = db.query(ClientLedgerEntry).filter(
        ClientLedgerEntry.client_id == client_id
    ).order_by(ClientLedgerEntry.date, ClientLedgerEntry.id).all()
    return _clientele_summary_item(client, entries)


@app.post("/api/clientele/clients", response_model=schemas.ClienteleSummaryItem)
def create_clientele_client(
    data: schemas.ClienteleClientIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "create")),
):
    if not data.name.strip():
        raise HTTPException(400, "Nom requis")
    parts = data.name.strip().split(" ", 1)
    client = Client(
        name=data.name.strip(),
        type="Particulier",
        segment=CLIENTELE_SEGMENT,
        contact=parts[0],
        phone=data.phone,
        email=data.email,
        city=data.city,
        status=data.status,
        notes=data.notes,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return _clientele_summary_item(client, [])


@app.put("/api/clientele/clients/{client_id}", response_model=schemas.ClienteleSummaryItem)
def update_clientele_client(
    client_id: int,
    data: schemas.ClienteleClientIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "update")),
):
    client = _get_clientele_client(db, client_id)
    if not data.name.strip():
        raise HTTPException(400, "Nom requis")
    parts = data.name.strip().split(" ", 1)
    client.name = data.name.strip()
    client.contact = parts[0]
    client.phone = data.phone
    client.email = data.email
    client.city = data.city
    client.status = data.status
    client.notes = data.notes
    db.commit()
    db.refresh(client)
    entries = db.query(ClientLedgerEntry).filter(ClientLedgerEntry.client_id == client_id).all()
    return _clientele_summary_item(client, entries)


@app.delete("/api/clientele/clients/{client_id}")
def delete_clientele_client(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clientele", "delete")),
):
    from app.services.client_lifecycle_service import delete_or_archive_client
    client = _get_clientele_client(db, client_id)
    ip = request.client.host if request.client else ""
    result = delete_or_archive_client(
        db, client_id, user_id=user.id, user_email=user.email, ip=ip, allow_archive=True
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            400,
            f"Suppression impossible : {result.get('message', 'des données liées bloquent la suppression')}",
        )
    return {"ok": True, **result}


@app.post("/api/clientele/ledger", response_model=schemas.ClientLedgerOut)
def create_ledger_entry(
    data: schemas.ClientLedgerIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "update")),
):
    _get_clientele_client(db, data.client_id)
    entry = ClientLedgerEntry(
        client_id=data.client_id,
        date=data.date or date.today(),
        commande=data.commande,
        remboursement=data.remboursement,
        solde=0,
        source_file="manuel",
    )
    db.add(entry)
    db.flush()
    _recalc_client_soldes(db, data.client_id)
    db.commit()
    db.refresh(entry)
    return entry


@app.put("/api/clientele/ledger/{entry_id}", response_model=schemas.ClientLedgerOut)
def update_ledger_entry(
    entry_id: int,
    data: schemas.ClientLedgerIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "update")),
):
    entry = db.query(ClientLedgerEntry).filter(ClientLedgerEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Mouvement introuvable")
    _get_clientele_client(db, entry.client_id)
    entry.date = data.date or entry.date
    entry.commande = data.commande
    entry.remboursement = data.remboursement
    _recalc_client_soldes(db, entry.client_id)
    db.commit()
    db.refresh(entry)
    return entry


@app.patch("/api/clientele/ledger/cell")
def upsert_ledger_cell(
    data: schemas.LedgerCellUpsert,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "update")),
):
    """Met à jour ou crée une cellule du tableau (date × client)."""
    if not data.date:
        raise HTTPException(400, "Date requise")
    _get_clientele_client(db, data.client_id)
    entry = db.query(ClientLedgerEntry).filter(
        ClientLedgerEntry.client_id == data.client_id,
        ClientLedgerEntry.date == data.date,
    ).first()
    cmd = data.commande if data.commande is not None else 0.0
    remb = data.remboursement if data.remboursement is not None else 0.0
    if entry:
        if data.commande is not None:
            entry.commande = cmd
        if data.remboursement is not None:
            entry.remboursement = remb
    else:
        if cmd == 0 and remb == 0:
            return {"ok": True, "skipped": True}
        entry = ClientLedgerEntry(
            client_id=data.client_id,
            date=data.date,
            commande=cmd,
            remboursement=remb,
            solde=0,
            source_file="manuel",
        )
        db.add(entry)
    db.flush()
    _recalc_client_soldes(db, data.client_id)
    db.commit()
    db.refresh(entry)
    return {"ok": True, "entry_id": entry.id, "solde": entry.solde}


@app.delete("/api/clientele/ledger/{entry_id}")
def delete_ledger_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "delete")),
):
    entry = db.query(ClientLedgerEntry).filter(ClientLedgerEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Mouvement introuvable")
    client_id = entry.client_id
    db.delete(entry)
    db.flush()
    _recalc_client_soldes(db, client_id)
    db.commit()
    return {"ok": True}


@app.delete("/api/clientele/import")
def clear_clientele_import_data(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "delete")),
):
    """Efface toutes les données Clientèle PC importées pour permettre un nouvel import."""
    from app.import_service import clear_clientele_import

    return clear_clientele_import(db)


@app.get("/api/clientele/board", response_model=schemas.ClienteleBoardOut)
def clientele_board(
    limit: Optional[int] = 60,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "view")),
):
    """Tableau matriciel (dates × clients), limité par défaut aux 60 dernières dates."""
    clients = db.query(Client).filter(
        Client.segment == CLIENTELE_SEGMENT, Client.is_archived.isnot(True)
    ).order_by(Client.name).all()
    if not clients:
        return schemas.ClienteleBoardOut(
            title="Tableau de board clientèle PC", dates=[], clients=[], total_dates=0, truncated=False,
        )

    client_ids = [c.id for c in clients]
    all_entries = db.query(ClientLedgerEntry).filter(
        ClientLedgerEntry.client_id.in_(client_ids)
    ).all()

    all_dates = sorted({e.date for e in all_entries if e.date})
    total_dates = len(all_dates)
    truncated = False
    if limit and limit > 0 and len(all_dates) > limit:
        all_dates = all_dates[-limit:]
        truncated = True

    entries_by_client: dict[int, dict] = {cid: {} for cid in client_ids}
    for entry in all_entries:
        if entry.date in all_dates:
            entries_by_client[entry.client_id][entry.date] = entry

    board_clients = []
    for c in clients:
        by_date = entries_by_client[c.id]
        board_clients.append(schemas.ClienteleBoardClient(
            client_id=c.id,
            name=c.name,
            commandes=[by_date[d].commande if d in by_date else 0.0 for d in all_dates],
            remboursements=[by_date[d].remboursement if d in by_date else 0.0 for d in all_dates],
            soldes=[by_date[d].solde if d in by_date else 0.0 for d in all_dates],
            entry_ids=[by_date[d].id if d in by_date else None for d in all_dates],
        ))

    return schemas.ClienteleBoardOut(
        title="Tableau de board de la clientèle PC",
        dates=[d.isoformat() for d in all_dates],
        clients=board_clients,
        total_dates=total_dates,
        truncated=truncated,
    )


@app.get("/api/clientele/ledger/{client_id}", response_model=List[schemas.ClientLedgerOut])
def clientele_ledger(
    client_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("clientele", "view")),
):
    """Historique détaillé d'un client."""
    return db.query(ClientLedgerEntry).filter(
        ClientLedgerEntry.client_id == client_id
    ).order_by(ClientLedgerEntry.date).all()


@app.post("/api/import/clientele-default")
def import_default_clientele(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("imports", "create")),
):
    """Importe le fichier Excel clientèle par défaut (data/clientele_pc.xlsx)."""
    if not DEFAULT_CLIENTELE_FILE.exists():
        raise HTTPException(404, f"Fichier introuvable : {DEFAULT_CLIENTELE_FILE.name}")
    contents = DEFAULT_CLIENTELE_FILE.read_bytes()
    return import_clientele_board(db, contents, DEFAULT_CLIENTELE_FILE.name)


# ============================================================
# EXCEL IMPORT
# ============================================================

from fastapi import UploadFile, File, Form
import pandas as pd
from datetime import date
from io import BytesIO


@app.post("/api/import/excel")
async def import_excel(
    file: UploadFile = File(...),
    sheet_type: str = Form("clients"),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("imports", "create")),
):
    """Importe des données depuis un fichier Excel"""
    from app.upload_limits import SPREADSHEET_EXT, assert_extension, read_bounded

    try:
        assert_extension(file.filename, SPREADSHEET_EXT)
        contents = await read_bounded(file)

        if sheet_type == "clientele_pc":
            return import_clientele_board(db, contents, file.filename or "import.xlsx")

        df = pd.read_excel(BytesIO(contents))
        
        imported_count = 0
        errors = []
        
        if sheet_type == "clients":
            for idx, row in df.iterrows():
                try:
                    if pd.isna(row.get('name')):
                        errors.append(f"Ligne {idx+2}: nom manquant")
                        continue
                    client = Client(
                        name=_excel_str(row['name']),
                        type=_excel_str(row.get('type'), 'Entreprise'),
                        segment=_excel_str(row.get('segment')),
                        contact=_excel_str(row.get('contact')),
                        email=_excel_str(row.get('email')),
                        phone=_excel_str(row.get('phone')),
                        city=_excel_str(row.get('city')),
                        status=_excel_str(row.get('status'), 'prospect'),
                        notes=_excel_str(row.get('notes')),
                    )
                    db.add(client)
                    imported_count += 1
                except Exception as e:
                    errors.append(f"Ligne {idx+2}: {str(e)}")
        
        elif sheet_type == "invoices":
            for idx, row in df.iterrows():
                try:
                    if pd.isna(row.get('number')):
                        errors.append(f"Ligne {idx+2}: numéro manquant")
                        continue
                    invoice = Invoice(
                        number=_excel_str(row['number']),
                        client_id=_excel_int(row['client_id']) if pd.notna(row.get('client_id')) else None,
                        date=_excel_date(row.get('date')),
                        due_date=_excel_date(row.get('due_date')),
                        amount=_excel_float(row.get('amount')),
                        paid=_excel_float(row.get('paid')),
                        status=_excel_str(row.get('status'), 'brouillon'),
                        notes=_excel_str(row.get('notes')),
                    )
                    db.add(invoice)
                    imported_count += 1
                except Exception as e:
                    errors.append(f"Ligne {idx+2}: {str(e)}")
        
        elif sheet_type == "projects":
            for idx, row in df.iterrows():
                try:
                    if pd.isna(row.get('name')):
                        errors.append(f"Ligne {idx+2}: nom manquant")
                        continue
                    project = Project(
                        name=_excel_str(row['name']),
                        client_id=_excel_int(row['client_id']) if pd.notna(row.get('client_id')) else None,
                        pole=_excel_str(row.get('pole'), 'Consulting'),
                        status=_excel_str(row.get('status'), 'planifié'),
                        progress=_excel_int(row.get('progress')),
                        budget=_excel_float(row.get('budget')),
                        billed=_excel_float(row.get('billed')),
                        start_date=_excel_date(row.get('start_date')),
                        end_date=_excel_date(row.get('end_date')),
                        description=_excel_str(row.get('description')),
                    )
                    db.add(project)
                    imported_count += 1
                except Exception as e:
                    errors.append(f"Ligne {idx+2}: {str(e)}")
        
        elif sheet_type == "transactions":
            for idx, row in df.iterrows():
                try:
                    if pd.isna(row.get('label')):
                        errors.append(f"Ligne {idx+2}: libellé manquant")
                        continue
                    transaction = Transaction(
                        date=_excel_date(row.get('date')),
                        label=_excel_str(row['label']),
                        type=_excel_str(row.get('type'), 'produit'),
                        category=_excel_str(row.get('category')),
                        amount=_excel_float(row.get('amount')),
                        account_code=_excel_str(row.get('account_code')),
                        payment_method=_excel_str(row.get('payment_method'), 'virement'),
                        reference=_excel_str(row.get('reference')),
                        notes=_excel_str(row.get('notes')),
                    )
                    db.add(transaction)
                    imported_count += 1
                except Exception as e:
                    errors.append(f"Ligne {idx+2}: {str(e)}")

        elif sheet_type == "clientele_pc":
            return import_clientele_board(db, contents, file.filename or "import.xlsx")

        else:
            return {"ok": False, "message": f"Type d'import inconnu : {sheet_type}"}

        db.commit()

        return {
            "ok": True,
            "imported": imported_count,
            "total": len(df),
            "errors": errors,
            "message": f"{imported_count}/{len(df)} lignes importées",
        }

    except Exception as e:
        db.rollback()
        return {"ok": False, "message": f"Erreur lors du traitement : {str(e)}"}


@app.post("/api/import/analyze")
async def analyze_excel(
    file: UploadFile = File(...),
    _: User = Depends(require_action("imports", "view")),
):
    """Analyse la structure d'un fichier Excel et retourne les colonnes disponibles"""
    from app.upload_limits import SPREADSHEET_EXT, assert_extension, read_bounded

    try:
        assert_extension(file.filename, SPREADSHEET_EXT)
        contents = await read_bounded(file)
        excel_file = BytesIO(contents)

        xls = pd.ExcelFile(excel_file)
        sheets = xls.sheet_names
        sheet = sheets[0] if sheets else 0

        raw = pd.read_excel(BytesIO(contents), sheet_name=sheet, header=None)
        if detect_clientele_format(raw):
            return analyze_clientele(contents, sheet)

        analysis = {
            "ok": True,
            "format": "standard",
            "sheets": sheets,
            "current_sheet": sheets[0] if sheets else None,
            "columns": [],
            "sample_rows": [],
            "total_rows": 0,
        }

        if sheets:
            df = xls.parse(sheets[0])
            analysis["columns"] = [_excel_str(col) for col in df.columns]
            analysis["total_rows"] = len(df)
            analysis["sample_rows"] = _sample_rows(df)

        return analysis

    except Exception as e:
        return {"ok": False, "message": f"Erreur lors de l'analyse : {str(e)}"}


# ============================================================
# FRONTEND - servir les fichiers statiques
# ============================================================

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

@app.get("/api/company", response_model=schemas.CompanyProfileOut)
def get_company(db: Session = Depends(get_db)):
    row = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not row:
        raise HTTPException(404, "Profil société non initialisé")
    return row


@app.put("/api/company", response_model=schemas.CompanyProfileOut)
def update_company(
    data: schemas.CompanyProfileIn,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("users.manage")),
):
    row = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not row:
        row = CompanyProfile(id=1)
        db.add(row)
    for k, v in data.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@app.get("/api/public/company")
def public_company(db: Session = Depends(get_db)):
    """Infos société pour la page d'accueil (sans authentification)."""
    row = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not row:
        return {
            "name": "Peya Company",
            "legal_form": "SARL",
            "tagline": "Votre entreprise, pilotée en un seul endroit",
            "description": "",
            "logo_path": "/static/logo-peya.png",
        }
    return {
        "name": row.name,
        "legal_form": row.legal_form,
        "tagline": row.tagline,
        "description": row.description,
        "address": row.address,
        "phone": row.phone,
        "email": row.email,
        "logo_path": row.logo_path,
        "currency": row.currency,
    }


if FRONTEND_DIR.exists():
    @app.get("/favicon.ico", include_in_schema=False)
    def serve_favicon():
        """Icône onglet navigateur — logo officiel Peya Company (PNG)."""
        logo = FRONTEND_DIR / "logo-peya.png"
        if logo.is_file():
            return FileResponse(logo, media_type="image/png")
        ico = FRONTEND_DIR / "favicon.ico"
        if ico.is_file():
            return FileResponse(ico, media_type="image/x-icon")
        raise HTTPException(404, "Placez logo-peya.png dans le dossier frontend/")

    @app.get("/portal-client.html")
    def serve_portal_client():
        return FileResponse(FRONTEND_DIR / "portal-client.html")

    @app.get("/portal-supplier.html")
    def serve_portal_supplier():
        return FileResponse(FRONTEND_DIR / "portal-supplier.html")

    @app.get("/mobile-scan.html")
    def serve_mobile_scan():
        return FileResponse(FRONTEND_DIR / "mobile-scan.html")

    @app.get("/esign-sign.html")
    def serve_esign_sign():
        return FileResponse(FRONTEND_DIR / "esign-sign.html")

    @app.get("/manifest.webmanifest")
    def serve_manifest():
        return FileResponse(
            FRONTEND_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    @app.get("/sw.js")
    def serve_sw():
        return FileResponse(
            FRONTEND_DIR / "sw.js",
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache, must-revalidate",
                "Service-Worker-Allowed": "/",
            },
        )

    @app.get("/offline.html")
    def serve_offline():
        return FileResponse(
            FRONTEND_DIR / "offline.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    @app.get("/app")
    def serve_app():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/login")
    def serve_login():
        return FileResponse(FRONTEND_DIR / "login.html")

    @app.get("/")
    def serve_welcome():
        return FileResponse(FRONTEND_DIR / "welcome.html")

    @app.get("/site/{slug}")
    def serve_site_page(slug: str):
        return FileResponse(FRONTEND_DIR / "site.html")

    if CMS_MEDIA_ROOT.exists():
        app.mount("/media/cms", StaticFiles(directory=str(CMS_MEDIA_ROOT)), name="cms_media")

    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    from app.server_config import app_config_payload, public_base_url
    from app.database import DB_PATH

    cfg = app_config_payload()
    host_bind = os.environ.get("PEYA_HOST", "127.0.0.1")
    port_bind = int(os.environ.get("PEYA_PORT", "8001"))
    reload = os.environ.get("PEYA_RELOAD", "1").strip().lower() in ("1", "true", "yes")

    print("\n" + "=" * 60)
    print("  PEYA COMPANY ERP - Démarrage")
    print("=" * 60)
    print(f"  URL publique : {cfg['public_url']}")
    print(f"  Connexion    : {cfg['login_url']}")
    print(f"  ERP          : {cfg['app_url']}")
    print(f"  Serveur      : {cfg['hostname']} ({cfg['server_ip']})")
    print(f"  Écoute       : {host_bind}:{port_bind}")
    print(f"  Base         : {DB_PATH}")
    if DEFAULT_CLIENTELE_FILE.exists():
        print(f"  Excel PC     : {DEFAULT_CLIENTELE_FILE.name}")
    print("=" * 60 + "\n")
    uvicorn.run("main:app", host=host_bind, port=port_bind, reload=reload)
