"""API entreprise — sociétés, workflows, OCR, signatures, planification, chat, groupes."""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query, Form
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_permission
from app.api_guards import require_action
from app.database import get_db
from app.models import User, StockItem
from app.models_enterprise import (
    Company, UserGroup, UserGroupMember, ApprovalRequest, ApprovalStep,
    ScheduledReport, DocumentSignature, OcrExtraction, ChatMessage,
    NotificationOutbox,
)
from app.services.security_service import (
    setup_totp, enable_totp, list_sessions, revoke_session, get_user_security,
)
from app.services.workflow_service import create_approval, decide_step
from app.services.ocr_service import (
    OcrDependencyError,
    apply_to_bank_statement,
    apply_to_journal_entry,
    apply_to_supplier_invoice,
    get_extraction_payload,
    get_ocr_capabilities,
    process_upload,
    save_corrections,
)
from app.services.channels_service import queue_message
from app.services.pdf_reports import build_pdf_export
from app.services import excel_export
from app.services.accounting_reports import balance_generale
from datetime import datetime, timezone

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])


# ——— Sociétés ———
class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    legal_form: str
    address: str
    phone: str
    email: str
    currency: str
    is_active: bool
    is_default: bool


class CompanyIn(BaseModel):
    code: str
    name: str
    legal_form: str = "SARL"
    address: str = ""
    phone: str = ""
    email: str = ""
    currency: str = "XOF"


def ensure_default_companies(db: Session):
    if db.query(Company).count() > 0:
        return
    from app.region_config import REGION
    db.add(Company(
        code="PEYA", name=REGION["company_name"], legal_form=REGION["legal_form"],
        address=REGION["address_default"], email="contact@peyacompany.com",
        currency=REGION["currency_iso"], is_default=True,
    ))
    db.commit()


@router.get("/companies", response_model=List[CompanyOut])
def list_companies(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    ensure_default_companies(db)
    return db.query(Company).filter(Company.is_active == True).order_by(Company.name).all()


@router.post("/companies", response_model=CompanyOut)
def create_company(data: CompanyIn, db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    code = data.code.strip().upper()
    if db.query(Company).filter(Company.code == code).first():
        raise HTTPException(400, "Code société déjà utilisé")
    c = Company(code=code, **data.model_dump(exclude={"code"}))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.put("/companies/{cid}/switch")
def switch_company(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.query(Company).filter(Company.id == cid).first():
        raise HTTPException(404)
    sec = get_user_security(db, user.id)
    sec.company_id = cid
    db.commit()
    return {"ok": True, "company_id": cid}


# ——— Sécurité 2FA & sessions ———
@router.get("/security/2fa/setup")
def totp_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return setup_totp(db, user)


@router.post("/security/2fa/enable")
def totp_enable(code: str = Query(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not enable_totp(db, user, code):
        raise HTTPException(400, "Code invalide")
    return {"ok": True}


@router.post("/security/2fa/disable")
def totp_disable(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sec = get_user_security(db, user.id)
    sec.totp_enabled = False
    sec.totp_secret = ""
    db.commit()
    return {"ok": True}


@router.get("/security/sessions")
def my_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [
        {"id": s.id, "ip_address": s.ip_address, "user_agent": s.user_agent,
         "created_at": s.created_at, "last_seen_at": s.last_seen_at}
        for s in list_sessions(db, user.id)
    ]


@router.delete("/security/sessions/{sid}")
def revoke_my_session(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    revoke_session(db, sid, user.id)
    return {"ok": True}


@router.get("/security/settings")
def my_security_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sec = get_user_security(db, user.id)
    return {
        "totp_enabled": sec.totp_enabled,
        "preferred_language": sec.preferred_language or "fr",
        "company_id": sec.company_id,
        "failed_attempts": sec.failed_login_attempts,
        "locked_until": sec.locked_until or "",
    }


@router.put("/security/language")
def set_language(lang: str = Query(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sec = get_user_security(db, user.id)
    sec.preferred_language = lang if lang in ("fr", "en") else "fr"
    db.commit()
    return {"ok": True, "language": sec.preferred_language}


# ——— Groupes utilisateurs ———
class GroupIn(BaseModel):
    code: str
    name: str
    description: str = ""
    group_type: str = "permission"  # permission | mail
    permissions: List[str] = []
    extra_emails: List[str] = []
    parent_group_id: Optional[int] = None


class GroupMembersIn(BaseModel):
    user_ids: List[int] = []
    employee_ids: List[int] = []


class MailGroupSendIn(BaseModel):
    subject: str
    body: str


def _group_detail(db: Session, g: UserGroup) -> dict:
    from app.models import User
    from app.models_erp import Employee
    from app.services.mail_groups import group_recipient_emails, parse_extra_emails

    members = db.query(UserGroupMember).filter(UserGroupMember.group_id == g.id).all()
    perms = json.loads(g.permissions_json or "[]")
    if g.parent_group_id:
        parent = db.query(UserGroup).filter(UserGroup.id == g.parent_group_id).first()
        if parent:
            parent_perms = json.loads(parent.permissions_json or "[]")
            perms = list(set(parent_perms + perms))
    member_users = []
    member_employees = []
    for m in members:
        if m.user_id:
            u = db.query(User).filter(User.id == m.user_id).first()
            if u:
                member_users.append({
                    "user_id": u.id, "email": u.email, "name": u.full_name or u.email,
                })
        if m.employee_id:
            emp = db.query(Employee).filter(Employee.id == m.employee_id).first()
            if emp:
                member_employees.append({
                    "employee_id": emp.id,
                    "email": emp.email,
                    "name": f"{emp.firstname} {emp.lastname}".strip(),
                    "department": emp.department,
                })
    emails = group_recipient_emails(db, g) if (g.group_type or "permission") == "mail" else []
    return {
        "id": g.id,
        "code": g.code,
        "name": g.name,
        "description": g.description,
        "group_type": g.group_type or "permission",
        "permissions": perms,
        "extra_emails": parse_extra_emails(g.extra_emails or ""),
        "members_count": len(members),
        "parent_group_id": g.parent_group_id,
        "member_users": member_users,
        "member_employees": member_employees,
        "recipient_emails": emails,
    }


@router.get("/groups")
def list_groups(db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    groups = db.query(UserGroup).filter(UserGroup.is_active == True).order_by(UserGroup.name).all()
    return [_group_detail(db, g) for g in groups]


@router.post("/groups")
def create_group(data: GroupIn, db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    gtype = (data.group_type or "permission").strip().lower()
    if gtype not in ("permission", "mail"):
        raise HTTPException(400, "group_type doit être permission ou mail")
    g = UserGroup(
        code=data.code.strip().lower(),
        name=data.name,
        description=data.description,
        group_type=gtype,
        permissions_json=json.dumps(data.permissions),
        extra_emails=json.dumps(data.extra_emails or []),
        parent_group_id=data.parent_group_id,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"ok": True, "id": g.id, "group": _group_detail(db, g)}


class BulkGroupsIn(BaseModel):
    ids: List[int]
    action: str = "archive"


@router.post("/groups/bulk")
def bulk_groups(
    body: BulkGroupsIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    """Actions groupées sur les groupes — doit être déclaré avant /groups/{gid}."""
    if not body.ids:
        raise HTTPException(400, "Aucun groupe sélectionné")
    action = (body.action or "archive").strip().lower()
    if action != "archive":
        raise HTTPException(400, "Action invalide — utilisez archive")
    count = 0
    for gid in body.ids:
        g = db.query(UserGroup).filter(UserGroup.id == gid, UserGroup.is_active == True).first()
        if g:
            g.is_active = False
            count += 1
    db.commit()
    return {"ok": True, "processed": count, "message": f"{count} groupe(s) archivé(s)"}


@router.get("/groups/{gid}")
def get_group(gid: int, db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    g = db.query(UserGroup).filter(UserGroup.id == gid, UserGroup.is_active == True).first()
    if not g:
        raise HTTPException(404, "Groupe introuvable")
    return _group_detail(db, g)


@router.put("/groups/{gid}")
def update_group(
    gid: int,
    data: GroupIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    g = db.query(UserGroup).filter(UserGroup.id == gid).first()
    if not g:
        raise HTTPException(404, "Groupe introuvable")
    if data.name:
        g.name = data.name
    if data.description is not None:
        g.description = data.description
    if data.group_type:
        g.group_type = data.group_type.strip().lower()
    if data.permissions is not None:
        g.permissions_json = json.dumps(data.permissions)
    if data.extra_emails is not None:
        g.extra_emails = json.dumps(data.extra_emails)
    db.commit()
    return {"ok": True, "group": _group_detail(db, g)}


@router.put("/groups/{gid}/members")
def set_group_members(
    gid: int,
    data: GroupMembersIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    g = db.query(UserGroup).filter(UserGroup.id == gid).first()
    if not g:
        raise HTTPException(404, "Groupe introuvable")
    db.query(UserGroupMember).filter(UserGroupMember.group_id == gid).delete()
    for uid in data.user_ids or []:
        db.add(UserGroupMember(group_id=gid, user_id=uid))
    for eid in data.employee_ids or []:
        db.add(UserGroupMember(group_id=gid, employee_id=eid))
    db.commit()
    return {"ok": True, "group": _group_detail(db, g)}


@router.post("/groups/{gid}/members/{uid}")
def add_group_member(gid: int, uid: int, db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    if db.query(UserGroupMember).filter(UserGroupMember.group_id == gid, UserGroupMember.user_id == uid).first():
        return {"ok": True}
    db.add(UserGroupMember(group_id=gid, user_id=uid))
    db.commit()
    return {"ok": True}


@router.post("/groups/{gid}/members/employee/{eid}")
def add_group_employee_member(
    gid: int, eid: int, db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage")),
):
    if db.query(UserGroupMember).filter(
        UserGroupMember.group_id == gid, UserGroupMember.employee_id == eid,
    ).first():
        return {"ok": True}
    db.add(UserGroupMember(group_id=gid, employee_id=eid))
    db.commit()
    return {"ok": True}


@router.delete("/groups/{gid}")
def archive_group(
    gid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    """Archive un groupe (soft delete — is_active=False)."""
    g = db.query(UserGroup).filter(UserGroup.id == gid, UserGroup.is_active == True).first()
    if not g:
        raise HTTPException(404, "Groupe introuvable")
    g.is_active = False
    db.commit()
    return {"ok": True, "message": f"Groupe « {g.name} » archivé"}


@router.post("/groups/{gid}/send-email")
def send_mail_group(
    gid: int,
    data: MailGroupSendIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("users.manage")),
):
    from app.services.mail_groups import group_recipient_emails
    from app.services.smtp_service import send_email_via_smtp

    g = db.query(UserGroup).filter(UserGroup.id == gid, UserGroup.is_active == True).first()
    if not g:
        raise HTTPException(404, "Groupe introuvable")
    if (g.group_type or "permission") != "mail":
        raise HTTPException(400, "Ce groupe n'est pas un groupe de messagerie")
    recipients = group_recipient_emails(db, g)
    if not recipients:
        raise HTTPException(400, "Aucun destinataire e-mail dans ce groupe")
    body_html = "<p>" + (data.body or "").replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    sent, errors = 0, []
    for email in recipients:
        r = send_email_via_smtp(db, to_email=email, subject=data.subject, body=body_html)
        if r.get("ok"):
            sent += 1
        else:
            errors.append(f"{email}: {r.get('message', 'erreur')}")
    return {"ok": sent > 0, "sent": sent, "total": len(recipients), "errors": errors}


# ——— Workflows ———
class ApprovalIn(BaseModel):
    module: str
    title: str
    amount: float = 0
    entity_type: str = ""
    entity_id: Optional[int] = None
    max_levels: int = 2
    notes: str = ""


@router.get("/approvals")
def list_approvals(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ApprovalRequest).order_by(ApprovalRequest.id.desc())
    if status:
        q = q.filter(ApprovalRequest.status == status)
    reqs = q.limit(100).all()
    users = {u.id: u.full_name or u.email for u in db.query(User).all()}
    return [
        {
            "id": r.id, "module": r.module, "title": r.title, "amount": r.amount,
            "status": r.status, "current_level": r.current_level, "max_levels": r.max_levels,
            "requested_by_name": users.get(r.requested_by, ""),
            "created_at": r.created_at,
        }
        for r in reqs
    ]


@router.post("/approvals")
def post_approval(data: ApprovalIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sec = get_user_security(db, user.id)
    req = create_approval(
        db, user, data.module, data.title, data.amount,
        data.entity_type, data.entity_id, data.max_levels, data.notes, sec.company_id,
    )
    return {"ok": True, "id": req.id}


@router.post("/approvals/{rid}/decide")
def approval_decide(
    rid: int,
    approve: bool = Query(...),
    comment: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        req = decide_step(db, rid, user, approve, comment)
        return {"ok": True, "status": req.status}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ——— OCR / Intelligence documentaire ———
@router.get("/ocr/health")
def ocr_health(_: User = Depends(require_action("imports", "view"))):
    return get_ocr_capabilities()


@router.post("/ocr/analyze")
async def ocr_analyze(
    file: UploadFile = File(...),
    document_type: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "create")),
):
    data = await file.read()
    if len(data) > 15_000_000:
        raise HTTPException(400, "Fichier trop volumineux (15 Mo max)")
    row = process_upload(db, file.filename or "upload.pdf", data, user.id, document_type=document_type)
    payload = get_extraction_payload(row)
    if payload.get("extraction_method") == "tesseract_missing":
        raise HTTPException(503, get_ocr_capabilities().get("tesseract_error") or "Tesseract requis pour les images.")
    return payload


@router.post("/ocr/analyze/batch")
async def ocr_analyze_batch(
    files: List[UploadFile] = File(...),
    document_type: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "create")),
):
    if len(files) > 25:
        raise HTTPException(400, "Maximum 25 fichiers par lot")
    results = []
    errors = []
    for f in files:
        try:
            data = await f.read()
            if len(data) > 15_000_000:
                errors.append({"filename": f.filename, "error": "Fichier > 15 Mo"})
                continue
            row = process_upload(db, f.filename or "upload", data, user.id, document_type=document_type)
            results.append(get_extraction_payload(row))
        except OcrDependencyError as e:
            errors.append({"filename": f.filename, "error": str(e)})
        except Exception as e:
            errors.append({"filename": f.filename, "error": str(e)})
    return {"ok": len(errors) == 0, "results": results, "errors": errors, "imported": len(results)}


@router.post("/ocr/invoice")
async def ocr_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "create")),
):
    """Alias rétrocompatibilité."""
    data = await file.read()
    if len(data) > 15_000_000:
        raise HTTPException(400, "Fichier trop volumineux (15 Mo max)")
    row = process_upload(db, file.filename or "upload.pdf", data, user.id)
    return get_extraction_payload(row)


@router.get("/ocr/history")
def ocr_history(
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "view")),
):
    q = db.query(OcrExtraction).order_by(OcrExtraction.id.desc())
    if user.role != "admin" and "admin" not in (user.permissions or []):
        q = q.filter(OcrExtraction.user_id == user.id)
    rows = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "document_type": r.document_type,
            "amount": r.amount,
            "supplier_name": r.supplier_name,
            "invoice_number": r.invoice_number,
            "confidence_score": r.confidence_score,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/ocr/{eid}")
def ocr_get(
    eid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "view")),
):
    row = db.query(OcrExtraction).filter(OcrExtraction.id == eid).first()
    if not row:
        raise HTTPException(404)
    if user.role != "admin" and "admin" not in (user.permissions or []) and row.user_id != user.id:
        raise HTTPException(403)
    return get_extraction_payload(row)


class OcrCorrectIn(BaseModel):
    corrections: dict


@router.put("/ocr/{eid}/correct")
def ocr_correct(
    eid: int,
    body: OcrCorrectIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "update")),
):
    row = db.query(OcrExtraction).filter(OcrExtraction.id == eid).first()
    if not row:
        raise HTTPException(404)
    return save_corrections(db, row, body.corrections or {}, user.id)


class OcrApplyBankIn(BaseModel):
    bank_account_id: int


@router.post("/ocr/{eid}/apply-bank")
def ocr_apply_bank(
    eid: int,
    body: OcrApplyBankIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "create")),
):
    row = db.query(OcrExtraction).filter(OcrExtraction.id == eid).first()
    if not row:
        raise HTTPException(404)
    try:
        return apply_to_bank_statement(db, row, body.bank_account_id, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/ocr/{eid}/apply-ledger")
def ocr_apply_ledger(
    eid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "create")),
):
    row = db.query(OcrExtraction).filter(OcrExtraction.id == eid).first()
    if not row:
        raise HTTPException(404)
    try:
        return apply_to_journal_entry(db, row, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/ocr/{eid}/apply")
def ocr_apply(
    eid: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("imports", "create")),
):
    row = db.query(OcrExtraction).filter(OcrExtraction.id == eid).first()
    if not row:
        raise HTTPException(404)
    try:
        return apply_to_supplier_invoice(db, row, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ——— Signature électronique ———
class SignIn(BaseModel):
    document_type: str
    document_id: int
    signer_name: str
    signature_png: str


@router.post("/signatures")
def sign_document(data: SignIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ip = request.client.host if request.client else ""
    row = DocumentSignature(
        document_type=data.document_type,
        document_id=data.document_id,
        signed_by=user.id,
        signer_name=data.signer_name or user.full_name,
        signature_png=data.signature_png[:500000],
        signed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        ip_address=ip,
    )
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id}


@router.get("/signatures/{doc_type}/{doc_id}")
def get_signatures(doc_type: str, doc_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(DocumentSignature).filter(
        DocumentSignature.document_type == doc_type,
        DocumentSignature.document_id == doc_id,
    ).all()
    return [{"id": r.id, "signer_name": r.signer_name, "signed_at": r.signed_at} for r in rows]


# ——— Rapports planifiés ———
class ScheduledIn(BaseModel):
    name: str
    report_type: str = "balance"
    format: str = "xlsx"
    cron_label: str = "weekly"
    email_to: str = ""


@router.get("/scheduled-reports")
def list_scheduled(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ScheduledReport).filter(
        (ScheduledReport.user_id == user.id) | (ScheduledReport.user_id == None)
    ).order_by(ScheduledReport.id.desc()).all()


@router.post("/scheduled-reports")
def create_scheduled(data: ScheduledIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sec = get_user_security(db, user.id)
    row = ScheduledReport(
        name=data.name, report_type=data.report_type, format=data.format,
        cron_label=data.cron_label, email_to=data.email_to, user_id=user.id,
        company_id=sec.company_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/scheduled-reports/{rid}/run")
def run_scheduled(rid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(ScheduledReport).filter(ScheduledReport.id == rid).first()
    if not row:
        raise HTTPException(404)
    row.last_run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.commit()
    if row.format == "pdf":
        try:
            data = build_pdf_export(db, row.report_type or "bi")
            return Response(
                data,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="rapport_{row.report_type or "bi"}_{rid}.pdf"'},
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
    exporters = {
        "balance": excel_export.export_balance,
        "invoices": excel_export.export_invoices,
        "stock": excel_export.export_stock,
    }
    fn = exporters.get(row.report_type, excel_export.export_balance)
    data = fn(db)
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="rapport_{rid}.xlsx"'},
    )


# ——— PDF rapports (BI + comptabilité) ———
def _pdf_response(data: bytes, filename: str, *, inline: bool = False) -> Response:
    disp = "inline" if inline else "attachment"
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disp}; filename="{filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


def _export_pdf(
    db: Session,
    user: User,
    report_type: str,
    filename: str,
    fiscal_year: Optional[int] = None,
    *,
    inline: bool = False,
) -> Response:
    data = build_pdf_export(
        db, report_type, fiscal_year,
        user_id=user.id, user_email=user.email or "",
    )
    return _pdf_response(data, filename, inline=inline)


@router.get("/reports/bi.pdf")
def export_bi_pdf(
    fiscal_year: Optional[int] = None,
    preview: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    return _export_pdf(db, user, "bi", "business_intelligence_peya.pdf", fiscal_year, inline=preview)


@router.get("/reports/overview.pdf")
def export_overview_pdf(
    fiscal_year: Optional[int] = None,
    preview: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("dashboard", "view")),
):
    return _export_pdf(db, user, "overview", "vue_ensemble_peya.pdf", fiscal_year, inline=preview)


@router.get("/reports/balance.pdf")
def export_balance_pdf(
    fiscal_year: Optional[int] = None,
    preview: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("comptarep", "view")),
):
    return _export_pdf(db, user, "balance", "balance_peya.pdf", fiscal_year, inline=preview)


@router.get("/reports/compte-resultat.pdf")
def export_cr_pdf(
    fiscal_year: Optional[int] = None,
    preview: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("comptarep", "view")),
):
    return _export_pdf(db, user, "compte_resultat", "compte_resultat_peya.pdf", fiscal_year, inline=preview)


@router.get("/reports/flux-tresorerie.pdf")
def export_flux_pdf(
    preview: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("comptarep", "view")),
):
    return _export_pdf(db, user, "flux_tresorerie", "flux_tresorerie_peya.pdf", inline=preview)


@router.get("/reports/grand-livre.pdf")
def export_gl_pdf(
    preview: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("comptarep", "view")),
):
    return _export_pdf(db, user, "grand_livre", "grand_livre_peya.pdf", inline=preview)


@router.get("/reports/bilan.pdf")
def export_bilan_pdf(
    fiscal_year: Optional[int] = None,
    preview: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("comptarep", "view")),
):
    return _export_pdf(db, user, "bilan", "bilan_peya.pdf", fiscal_year, inline=preview)


# ——— SMS / WhatsApp ———
class ChannelMsgIn(BaseModel):
    channel: str
    recipient: str
    body: str


@router.post("/channels/send")
def send_channel(data: ChannelMsgIn, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    if data.channel not in ("sms", "whatsapp"):
        raise HTTPException(400, "Canal sms ou whatsapp")
    row = queue_message(db, data.channel, data.recipient, data.body)
    return {"ok": True, "status": row.status, "id": row.id}


@router.get("/channels/outbox")
def channel_outbox(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    rows = db.query(NotificationOutbox).order_by(NotificationOutbox.id.desc()).limit(limit).all()
    return [{"id": r.id, "channel": r.channel, "recipient": r.recipient, "status": r.status, "created_at": r.created_at} for r in rows]


# ——— Chat interne ———
class ChatIn(BaseModel):
    message: str


@router.get("/chat/messages")
def chat_messages(limit: int = 80, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit).all()
    return list(reversed([
        {"id": m.id, "user_name": m.user_name, "message": m.message, "created_at": m.created_at}
        for m in rows
    ]))


@router.post("/chat/messages")
def chat_post(data: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    msg = (data.message or "").strip()
    if not msg:
        raise HTTPException(400, "Message vide")
    row = ChatMessage(
        user_id=user.id,
        user_name=user.full_name or user.email,
        message=msg[:2000],
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id}


# ——— QR Code produit ———
@router.get("/stock/{item_id}/qrcode")
def stock_qrcode(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(404)
    try:
        import qrcode
        from io import BytesIO
        qr = qrcode.make(f"PEYA:SKU:{item.sku}:ID:{item.id}")
        buf = BytesIO()
        qr.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(500, f"QR indisponible: {e}")
