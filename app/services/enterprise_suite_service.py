"""Services Enterprise Suite P3–P5."""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Client, Invoice, StockItem, User
from app.models_erp import Employee, Supplier, SupplierInvoice
from app.models_enterprise import Company
from app.models_enterprise_suite import (
    AiInsight,
    ApiConnector,
    BiometricPunch,
    ConsolidationRun,
    DocumentFile,
    DocumentFolder,
    EsignRequest,
    MaintenanceAsset,
    MaintenanceOrder,
    MarketingCampaignRun,
    MobileScanLog,
    ReportDefinition,
    SecurityAlert,
    StockLocation,
    StockLot,
    StockSerial,
    SupplierPortalAccess,
)
from app.models_prefs import LoginLog
from app.models_stock import Warehouse

I18N_BUNDLES = {
    "fr": {
        "nav.dashboard": "Tableau de bord",
        "nav.clients": "Clients",
        "nav.invoices": "Factures",
        "nav.stock": "Stock",
        "nav.treasury": "Trésorerie",
        "action.save": "Enregistrer",
        "action.cancel": "Annuler",
    },
    "en": {
        "nav.dashboard": "Dashboard",
        "nav.clients": "Clients",
        "nav.invoices": "Invoices",
        "nav.stock": "Inventory",
        "nav.treasury": "Treasury",
        "action.save": "Save",
        "action.cancel": "Cancel",
    },
    "es": {
        "nav.dashboard": "Panel",
        "nav.clients": "Clientes",
        "nav.invoices": "Facturas",
        "nav.stock": "Inventario",
        "nav.treasury": "Tesorería",
        "action.save": "Guardar",
        "action.cancel": "Cancelar",
    },
    "ar": {
        "nav.dashboard": "لوحة القيادة",
        "nav.clients": "العملاء",
        "nav.invoices": "الفواتير",
        "nav.stock": "المخزون",
        "nav.treasury": "الخزينة",
        "action.save": "حفظ",
        "action.cancel": "إلغاء",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ——— P3 Stock ———
def stock_advanced_dashboard(db: Session) -> dict:
    lots = db.query(StockLot).count()
    serials = db.query(StockSerial).count()
    locations = db.query(StockLocation).count()
    expiring = db.query(StockLot).filter(
        StockLot.expiry_date.isnot(None),
        StockLot.expiry_date <= date.today() + timedelta(days=30),
    ).count()
    return {
        "lots": lots,
        "serials": serials,
        "locations": locations,
        "expiring_soon": expiring,
        "warehouses": [
            {"id": w.id, "code": w.code, "name": w.name, "type": w.type}
            for w in db.query(Warehouse).filter(Warehouse.is_active == True).all()  # noqa: E712
        ],
    }


def scan_code(db: Session, code: str, user_id: int | None = None) -> dict:
    code = (code or "").strip()
    item = db.query(StockItem).filter(
        (StockItem.sku == code) | (StockItem.barcode == code)
    ).first()
    serial = db.query(StockSerial).filter(StockSerial.serial_number == code).first()
    db.add(MobileScanLog(
        user_id=user_id, code=code, scan_type="barcode",
        stock_item_id=item.id if item else (serial.stock_item_id if serial else None),
        action="lookup", created_at=_now(),
    ))
    db.commit()
    if serial:
        item = db.query(StockItem).filter(StockItem.id == serial.stock_item_id).first()
    return {
        "found": bool(item or serial),
        "code": code,
        "item": {"id": item.id, "sku": item.sku, "name": item.name, "quantity": item.quantity} if item else None,
        "serial": {"id": serial.id, "number": serial.serial_number, "status": serial.status} if serial else None,
    }


def create_lot(db: Session, data: dict) -> StockLot:
    obj = StockLot(**data, created_at=_now())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def create_serial(db: Session, data: dict) -> StockSerial:
    obj = StockSerial(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ——— P3 Maintenance ———
def maintenance_dashboard(db: Session) -> dict:
    assets = db.query(MaintenanceAsset).all()
    orders = db.query(MaintenanceOrder).all()
    return {
        "assets": len(assets),
        "orders_open": sum(1 for o in orders if o.status in ("planifié", "en_cours")),
        "preventive_due": sum(
            1 for a in assets
            if a.next_service_at and a.next_service_at[:10] <= date.today().isoformat()
        ),
        "items": [
            {
                "id": a.id, "code": a.code, "name": a.name,
                "category": a.category, "status": a.status,
                "next_service_at": a.next_service_at,
            }
            for a in assets[:50]
        ],
        "orders": [
            {
                "id": o.id, "asset_id": o.asset_id, "title": o.title,
                "order_type": o.order_type, "status": o.status,
                "scheduled_date": str(o.scheduled_date) if o.scheduled_date else "",
            }
            for o in orders[:50]
        ],
    }


def record_biometric_punch(db: Session, employee_id: int, device_id: str, punch_type: str) -> dict:
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise ValueError("Employé introuvable")
    db.add(BiometricPunch(
        employee_id=employee_id,
        device_id=device_id,
        punch_type=punch_type,
        punched_at=_now(),
        source="api",
    ))
    db.commit()
    return {"ok": True, "employee": emp.firstname + " " + emp.lastname}


def payroll_cnss_summary(db: Session, year: int, month: int) -> dict:
    from app.models_accounting import PayrollRun, SalaryLine
    run = db.query(PayrollRun).filter(
        PayrollRun.period_year == year, PayrollRun.period_month == month
    ).first()
    if not run:
        return {"year": year, "month": month, "lines": [], "totals": {}}
    lines = db.query(SalaryLine).filter(SalaryLine.payroll_run_id == run.id).all()
    cnss_emp = sum(float(l.employee_charges or 0) for l in lines)
    cnss_er = sum(float(l.employer_charges or 0) for l in lines)
    irpp = sum(float(l.withholding_tax or 0) for l in lines)
    return {
        "year": year, "month": month, "status": run.status,
        "employee_count": len(lines),
        "totals": {
            "gross": run.total_gross,
            "net": run.total_net,
            "cnss_employee": cnss_emp,
            "cnss_employer": cnss_er,
            "irpp": irpp,
            "cnss_total": cnss_emp + cnss_er,
        },
        "lines": [
            {
                "employee_id": l.employee_id,
                "gross": l.gross_salary,
                "net": l.net_salary,
                "cnss_emp": l.employee_charges,
                "cnss_er": l.employer_charges,
                "irpp": l.withholding_tax,
            }
            for l in lines[:100]
        ],
    }


# ——— P4 Consolidation ———
def run_consolidation(db: Session, fiscal_year: int) -> ConsolidationRun:
    companies = db.query(Company).filter(Company.is_active == True).all()  # noqa: E712
    detail: Dict[str, Any] = {"companies": [], "totals": {"revenue": 0, "expenses": 0, "invoices": 0}}
    for co in companies:
        rev = float(
            db.query(func.coalesce(func.sum(Invoice.amount), 0))
            .filter(Invoice.company_id == co.id)
            .scalar() or 0
        )
        exp = float(
            db.query(func.coalesce(func.sum(SupplierInvoice.amount), 0))
            .filter(SupplierInvoice.company_id == co.id)
            .scalar() or 0
        )
        cnt = db.query(Invoice).filter(Invoice.company_id == co.id).count()
        detail["companies"].append({
            "id": co.id, "name": co.name, "revenue": rev, "expenses": exp, "invoices": cnt,
        })
        detail["totals"]["revenue"] += rev
        detail["totals"]["expenses"] += exp
        detail["totals"]["invoices"] += cnt
    obj = ConsolidationRun(
        period_label=f"FY-{fiscal_year}",
        fiscal_year=fiscal_year,
        status="completed",
        detail_json=json.dumps(detail, ensure_ascii=False),
        created_at=_now(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def convert_currency(db: Session, amount: float, from_code: str, to_code: str) -> dict:
    from app.models_currency import Currency
    src = db.query(Currency).filter(Currency.code == from_code.upper()).first()
    dst = db.query(Currency).filter(Currency.code == to_code.upper()).first()
    if not src or not dst:
        raise ValueError("Devise inconnue")
    # rate_to_base = nombre d'unités XOF pour 1 unité de la devise
    amount_base = amount * float(src.rate_to_base or 1)
    converted = round(amount_base / float(dst.rate_to_base or 1), 2)
    return {"from": from_code, "to": to_code, "amount": amount, "converted": converted, "rate": dst.rate_to_base}


def execute_report(db: Session, report_id: int) -> dict:
    rpt = db.query(ReportDefinition).filter(ReportDefinition.id == report_id).first()
    if not rpt:
        raise ValueError("Rapport introuvable")
    cols = json.loads(rpt.columns_json or "[]")
    module = rpt.module or "invoices"
    rows: List[dict] = []
    if module == "invoices":
        for inv in db.query(Invoice).order_by(Invoice.id.desc()).limit(200):
            rows.append({
                "number": inv.number,
                "date": str(inv.date) if inv.date else "",
                "amount": inv.amount,
                "status": inv.status,
                "client_id": inv.client_id,
            })
    elif module == "clients":
        for c in db.query(Client).limit(200):
            rows.append({"name": c.name, "email": c.email, "phone": c.phone})
    return {"name": rpt.name, "columns": cols, "rows": rows, "chart_type": rpt.chart_type}


def generate_ai_insights(db: Session) -> List[AiInsight]:
    insights = []
    today = date.today()
    month_start = today.replace(day=1)
    ca = float(
        db.query(func.coalesce(func.sum(Invoice.amount), 0))
        .filter(Invoice.date >= month_start)
        .scalar() or 0
    )
    overdue = db.query(Invoice).filter(Invoice.status == "en retard").count()
    low = db.query(StockItem).filter(StockItem.quantity <= StockItem.min_quantity).count()
    db.query(AiInsight).delete()
    for itype, title, summary, payload in [
        ("sales", "Tendance ventes", f"CA mois en cours : {ca:,.0f} FCFA", {"ca_month": ca}),
        ("collections", "Recouvrement", f"{overdue} facture(s) en retard", {"overdue": overdue}),
        ("stock", "Stock", f"{low} article(s) sous seuil", {"low_stock": low}),
    ]:
        ins = AiInsight(
            insight_type=itype, title=title, summary=summary,
            payload_json=json.dumps(payload), created_at=_now(),
        )
        db.add(ins)
        insights.append(ins)
    db.commit()
    return insights


def detect_suspicious_logins(db: Session) -> List[SecurityAlert]:
    alerts = []
    logs = db.query(LoginLog).order_by(LoginLog.id.desc()).limit(500).all()
    seen_ips: Dict[int, set] = {}
    for log in logs:
        uid = log.user_id
        if not uid:
            continue
        seen_ips.setdefault(uid, set())
        ip = log.ip_address or ""
        if ip and ip not in seen_ips[uid] and len(seen_ips[uid]) >= 2:
            exists = db.query(SecurityAlert).filter(
                SecurityAlert.user_id == uid,
                SecurityAlert.ip_address == ip,
                SecurityAlert.status == "open",
            ).first()
            if not exists:
                a = SecurityAlert(
                    user_id=uid, alert_type="suspicious_login", ip_address=ip,
                    detail=f"Nouvelle IP : {ip}", created_at=_now(),
                )
                db.add(a)
                alerts.append(a)
        if ip:
            seen_ips[uid].add(ip)
    db.commit()
    return alerts


def get_i18n(locale: str) -> dict:
    return I18N_BUNDLES.get(locale, I18N_BUNDLES["fr"])


# ——— P5 Écosystème ———
def create_supplier_portal_token(db: Session, supplier_id: int, days: int = 90) -> SupplierPortalAccess:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    row = SupplierPortalAccess(
        supplier_id=supplier_id, token=token, expires_at=expires,
        is_active=True, created_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def ged_list_folders(db: Session, entity_type: str = "", entity_id: int | None = None) -> list:
    q = db.query(DocumentFolder)
    if entity_type:
        q = q.filter(DocumentFolder.entity_type == entity_type)
    if entity_id:
        q = q.filter(DocumentFolder.entity_id == entity_id)
    return [
        {"id": f.id, "name": f.name, "entity_type": f.entity_type, "entity_id": f.entity_id}
        for f in q.order_by(DocumentFolder.name).all()
    ]


def ged_create_folder(db: Session, name: str, entity_type: str = "", entity_id: int | None = None) -> DocumentFolder:
    obj = DocumentFolder(name=name, entity_type=entity_type, entity_id=entity_id, created_at=_now())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def create_esign_request(
    db: Session,
    document_type: str,
    document_id: int,
    signer_email: str,
    signer_name: str,
    provider: str = "internal",
) -> EsignRequest:
    from app.services.esign_service import create_esign_with_provider
    return create_esign_with_provider(
        db, document_type, document_id, signer_email, signer_name, provider,
    )


def launch_marketing_campaign(
    db: Session,
    channel: str,
    subject: str,
    body: str,
    recipients: int,
    *,
    recipient_emails: list[str] | None = None,
    recipient_phones: list[str] | None = None,
    client_ids: list[int] | None = None,
) -> dict:
    from app.models import Client
    from app.services.channels_service import queue_message
    from app.services.smtp_service import send_email_via_smtp

    emails: list[str] = list(recipient_emails or [])
    phones: list[str] = list(recipient_phones or [])
    if client_ids:
        for cid in client_ids:
            c = db.query(Client).filter(Client.id == cid).first()
            if c and c.email and c.email not in emails:
                emails.append(c.email)
            if c and c.phone and c.phone not in phones:
                phones.append(c.phone)
    if channel == "email" and not emails:
        for c in db.query(Client).filter(Client.email != "").limit(max(recipients, 50)).all():
            if c.email:
                emails.append(c.email)
    if channel in ("sms", "whatsapp") and not phones:
        for c in db.query(Client).filter(Client.phone != "").limit(max(recipients, 50)).all():
            if c.phone:
                phones.append(c.phone)

    sent = failed = simulated = 0
    errors: list[str] = []
    html_body = f"<div style='font-family:sans-serif'>{body.replace(chr(10), '<br>')}</div>"

    if channel == "email":
        targets = emails[: max(recipients or len(emails), 1)] if recipients else emails
        for em in targets:
            r = send_email_via_smtp(db, to_email=em, subject=subject, body=html_body)
            if r.get("ok"):
                sent += 1
            else:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{em}: {r.get('message', 'erreur')}")
    elif channel in ("sms", "whatsapp"):
        targets = phones[: max(recipients or len(phones), 1)] if recipients else phones
        for ph in targets:
            row = queue_message(db, channel, ph, body)
            if row.status in ("sent", "simulated"):
                sent += 1
                if row.status == "simulated":
                    simulated += 1
            else:
                failed += 1

    status = "sent" if sent and not failed else ("partial" if sent else "failed")
    obj = MarketingCampaignRun(
        channel=channel, subject=subject, body=body,
        recipients_count=sent + failed,
        status=status,
        opens=0, clicks=0, conversions=0, sent_at=_now(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {
        "id": obj.id, "status": status, "sent": sent, "failed": failed,
        "simulated": simulated, "errors": errors, "sent_at": obj.sent_at,
    }


def seed_connectors(db: Session) -> None:
    defaults = [
        ("fedapay", "FedaPay", "mobile_money"),
        ("mixx", "Mixx by Yas", "mobile_money"),
        ("ecobank", "Ecobank API", "bank"),
        ("woocommerce", "WooCommerce", "rest"),
        ("docusign", "DocuSign", "esign"),
        ("yousign", "Yousign", "esign"),
    ]
    for code, name, ctype in defaults:
        if not db.query(ApiConnector).filter(ApiConnector.code == code).first():
            db.add(ApiConnector(code=code, name=name, connector_type=ctype, is_active=True))
    db.commit()


def ged_storage_root():
    from app.paths import uploads_root
    root = uploads_root() / "ged"
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_ged_file(
    db: Session,
    filename: str,
    data: bytes,
    mime_type: str,
    user_id: int | None,
    folder_id: int | None = None,
    tags: str = "",
) -> DocumentFile:
    import uuid
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename)[:180]
    rel = f"{uuid.uuid4().hex}_{safe}"
    path = ged_storage_root() / rel
    path.write_bytes(data)
    obj = DocumentFile(
        folder_id=folder_id,
        filename=filename,
        mime_type=mime_type or "",
        size_bytes=len(data),
        storage_path=rel,
        ocr_status="none",
        tags=tags,
        uploaded_by=user_id,
        created_at=_now(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def run_ged_ocr(db: Session, file_id: int, user_id: int) -> dict:
    from app.services.ocr_service import process_upload, get_extraction_payload
    doc = db.query(DocumentFile).filter(DocumentFile.id == file_id).first()
    if not doc:
        raise ValueError("Fichier introuvable")
    path = ged_storage_root() / doc.storage_path
    if not path.is_file():
        raise ValueError("Fichier physique manquant")
    data = path.read_bytes()
    extraction = process_upload(db, doc.filename, data, user_id)
    payload = get_extraction_payload(extraction)
    doc.ocr_status = "done" if payload.get("validation_ok") else "review"
    doc.ocr_result_json = json.dumps({
        "ocr_id": extraction.id,
        "document_type": payload.get("document_type"),
        "amount": payload.get("amount"),
        "supplier_name": payload.get("supplier_name"),
        "invoice_number": payload.get("invoice_number"),
        "preview": (payload.get("raw_preview") or "")[:500],
    }, ensure_ascii=False)
    # Auto-tags from OCR
    tags = [payload.get("document_type") or "document"]
    if payload.get("supplier_name"):
        tags.append(str(payload["supplier_name"])[:40])
    doc.tags = ",".join(t for t in tags if t)
    db.commit()
    return {"file_id": doc.id, "ocr_status": doc.ocr_status, "extraction": payload}


def sign_esign_request(db: Session, request_id: int) -> EsignRequest:
    obj = db.query(EsignRequest).filter(EsignRequest.id == request_id).first()
    if not obj:
        raise ValueError("Demande introuvable")
    if obj.status == "signed":
        return obj
    obj.status = "signed"
    obj.signed_at = _now()
    db.commit()
    db.refresh(obj)
    return obj


def project_board(db: Session) -> dict:
    from app.models import Project, Task
    projects = db.query(Project).order_by(Project.id.desc()).limit(50).all()
    tasks = db.query(Task).all()
    by_project: Dict[int, list] = {}
    for t in tasks:
        by_project.setdefault(t.project_id or 0, []).append(t)
    kanban: Dict[str, list] = {"todo": [], "in_progress": [], "review": [], "done": []}
    for t in tasks:
        st = (getattr(t, "kanban_status", None) or ("done" if t.done else ("in_progress" if t.date else "todo")))
        if t.done and st not in ("done",):
            st = "done"
        if st not in kanban:
            st = "todo"
        proj = db.query(Project).filter(Project.id == t.project_id).first()
        kanban[st].append({
            "id": t.id, "label": t.label, "project_id": t.project_id,
            "project_name": proj.name if proj else "—",
            "assignee": t.assignee, "date": str(t.date) if t.date else "",
            "done": t.done,
        })
    gantt = []
    for p in projects:
        pts = by_project.get(p.id, [])
        gantt.append({
            "id": p.id, "name": p.name, "status": p.status, "progress": p.progress or 0,
            "start_date": str(p.start_date) if p.start_date else "",
            "end_date": str(p.end_date) if p.end_date else "",
            "budget": p.budget, "billed": p.billed,
            "tasks": [
                {
                    "id": t.id, "label": t.label,
                    "date": str(t.date) if t.date else "",
                    "kanban_status": getattr(t, "kanban_status", "todo"),
                    "done": t.done,
                }
                for t in pts
            ],
        })
    return {"kanban": kanban, "gantt": gantt, "stats": {
        "projects": len(projects),
        "tasks": len(tasks),
        "done": len(kanban["done"]),
    }}


def move_task_kanban(db: Session, task_id: int, status: str) -> dict:
    from app.models import Task
    allowed = {"todo", "in_progress", "review", "done"}
    if status not in allowed:
        raise ValueError("Statut kanban invalide")
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise ValueError("Tâche introuvable")
    t.kanban_status = status
    t.done = status == "done"
    db.commit()
    return {"id": t.id, "kanban_status": t.kanban_status, "done": t.done}


def update_task_schedule(db: Session, task_id: int, task_date: str | None) -> dict:
    from datetime import date as d
    from app.models import Task
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise ValueError("Tâche introuvable")
    if task_date:
        t.date = d.fromisoformat(task_date[:10])
        if t.kanban_status == "todo":
            t.kanban_status = "in_progress"
    db.commit()
    return {"id": t.id, "date": str(t.date) if t.date else "", "kanban_status": t.kanban_status}


def update_project_progress(db: Session, project_id: int, progress: int) -> dict:
    from app.models import Project
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise ValueError("Projet introuvable")
    p.progress = max(0, min(100, int(progress)))
    if p.progress >= 100:
        p.status = "terminé"
    elif p.progress > 0 and p.status == "planifié":
        p.status = "en cours"
    db.commit()
    return {"id": p.id, "progress": p.progress, "status": p.status}


def logistics_summary(db: Session) -> dict:
    try:
        from app.models_enterprise_ops import LogisticsVehicle, LogisticsShipment
        vehicles = db.query(LogisticsVehicle).count()
        active = db.query(LogisticsVehicle).filter(LogisticsVehicle.status == "disponible").count()
        shipments = db.query(LogisticsShipment).count()
        in_progress = db.query(LogisticsShipment).filter(
            LogisticsShipment.status.in_(["en_cours", "chargé", "parti", "en route"])
        ).count()
        return {"vehicles": vehicles, "vehicles_active": active, "shipments": shipments, "shipments_in_progress": in_progress}
    except Exception:
        return {"vehicles": 0, "vehicles_active": 0, "shipments": 0, "shipments_in_progress": 0}


def ensure_default_ged_folder(db: Session) -> None:
    if not db.query(DocumentFolder).filter(DocumentFolder.name == "Documents généraux").first():
        db.add(DocumentFolder(name="Documents généraux", entity_type="global", created_at=_now()))
        db.commit()
