"""Fonctionnalités avancées : CRM 360, lignes, PDF, pipeline, relances, avoirs."""
from datetime import date
from typing import List

from pydantic import BaseModel as PydanticBaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Deal, Quote, Invoice, Client, DocumentLine, Activity,
)
from app.models_erp import JournalEntry, JournalLine
from app import schemas
from app.models import User
from app.auth import get_current_user
from app.api_guards import require_action
from app.commercial_service import (
    recalc_document_amount,
    mark_overdue_invoices,
    convert_quote_to_invoice,
    create_credit_note,
    convert_proforma_to_invoice,
    create_deposit_invoice,
    client_360,
)
from app.commercial_guards import (
    assert_invoice_mutable,
    assert_quote_mutable,
)
from app.pdf_docs import render_quote_pdf, render_invoice_pdf, render_journal_entry_pdf
from app.services.audit_log import log_audit
from app.services.reminder_service import send_invoice_reminders
from app.tenant_service import get_company_id, filter_by_company, get_entity_or_404

router = APIRouter(prefix="/api", tags=["enhanced"])


def _audit(request: Request, user: User, db: Session, action: str, module: str, entity_type: str, eid, detail: str):
    log_audit(
        db, action, module, entity_type, eid, detail,
        user.id, user.email,
        request.client.host if request.client else "",
    )


@router.patch("/deals/{deal_id}/stage", response_model=schemas.DealOut)
def patch_deal_stage(
    deal_id: int,
    body: schemas.DealStagePatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("deals", "update")),
):
    obj = get_entity_or_404(db, Deal, deal_id, get_company_id(db, user), "Deal")
    old = obj.stage
    obj.stage = body.stage
    db.commit()
    db.refresh(obj)
    _audit(request, user, db, "update", "deals", "deal", obj.id, f"Étape {old} → {body.stage}")
    return obj


@router.get("/clients/{client_id}/360")
def get_client_360(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "view")),
):
    try:
        return client_360(db, client_id, company_id=get_company_id(db, user))
    except ValueError:
        raise HTTPException(404, "Client introuvable")


@router.get("/activities", response_model=List[schemas.ActivityOut])
def list_activities(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "view")),
):
    get_entity_or_404(db, Client, client_id, get_company_id(db, user), "Client")
    return (
        db.query(Activity)
        .filter(Activity.client_id == client_id)
        .order_by(Activity.date.desc())
        .all()
    )


@router.post("/activities", response_model=schemas.ActivityOut)
def create_activity(
    data: schemas.ActivityIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("clients", "create")),
):
    get_entity_or_404(db, Client, data.client_id, get_company_id(db, user), "Client")
    payload = data.model_dump()
    payload["date"] = data.date or date.today()
    payload["user_name"] = user.full_name or user.email
    obj = Activity(**payload)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    _audit(request, user, db, "create", "clients", "activity", obj.id, obj.subject or obj.type)
    return obj


def _quote_lines(db: Session, quote_id: int):
    return (
        db.query(DocumentLine)
        .filter(DocumentLine.quote_id == quote_id)
        .order_by(DocumentLine.position)
        .all()
    )


@router.get("/quotes/{quote_id}/lines", response_model=List[schemas.DocumentLineOut])
def get_quote_lines(
    quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "view")),
):
    get_entity_or_404(db, Quote, quote_id, get_company_id(db, user), "Devis")
    return _quote_lines(db, quote_id)


@router.put("/quotes/{quote_id}/lines", response_model=List[schemas.DocumentLineOut])
def replace_quote_lines(
    quote_id: int,
    body: schemas.DocumentLinesReplace,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "update")),
):
    q = get_entity_or_404(db, Quote, quote_id, get_company_id(db, user), "Devis")
    assert_quote_mutable(q, user, db)
    db.query(DocumentLine).filter(DocumentLine.quote_id == quote_id).delete()
    for i, ln in enumerate(body.lines):
        row = ln.model_dump()
        row["position"] = i
        db.add(DocumentLine(quote_id=quote_id, **row))
    db.commit()
    recalc_document_amount(db, quote_id=quote_id)
    _audit(request, user, db, "update", "quotes", "quote_lines", quote_id, f"{len(body.lines)} lignes")
    return _quote_lines(db, quote_id)


@router.post("/quotes/{quote_id}/lines/import")
async def import_quote_lines_excel(
    quote_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "update")),
):
    from app.services.document_lines_import import parse_document_lines_excel
    from app.upload_limits import read_bounded, assert_extension, SPREADSHEET_EXT
    from app.fiscal_service import get_default_vat_rate

    q = get_entity_or_404(db, Quote, quote_id, get_company_id(db, user), "Devis")
    assert_quote_mutable(q, user, db)
    assert_extension(file.filename, SPREADSHEET_EXT)
    content = await read_bounded(file)
    parsed = parse_document_lines_excel(content, file.filename or "upload.xlsx", get_default_vat_rate(db))
    if not parsed.get("lines"):
        raise HTTPException(400, parsed.get("message", "Aucune ligne valide"))
    body = schemas.DocumentLinesReplace(lines=[schemas.DocumentLineIn(**ln) for ln in parsed["lines"]])
    return replace_quote_lines(quote_id, body, request, db, user)


def _invoice_lines(db: Session, invoice_id: int):
    return (
        db.query(DocumentLine)
        .filter(DocumentLine.invoice_id == invoice_id)
        .order_by(DocumentLine.position)
        .all()
    )


@router.get("/invoices/{invoice_id}/lines", response_model=List[schemas.DocumentLineOut])
def get_invoice_lines(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "view")),
):
    get_entity_or_404(db, Invoice, invoice_id, get_company_id(db, user), "Facture")
    return _invoice_lines(db, invoice_id)


@router.put("/invoices/{invoice_id}/lines", response_model=List[schemas.DocumentLineOut])
def replace_invoice_lines(
    invoice_id: int,
    body: schemas.DocumentLinesReplace,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "update")),
):
    inv = get_entity_or_404(db, Invoice, invoice_id, get_company_id(db, user), "Facture")
    assert_invoice_mutable(inv, user, db)
    db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice_id).delete()
    for i, ln in enumerate(body.lines):
        row = ln.model_dump()
        row["position"] = i
        db.add(DocumentLine(invoice_id=invoice_id, **row))
    db.commit()
    recalc_document_amount(db, invoice_id=invoice_id)
    _audit(request, user, db, "update", "invoices", "invoice_lines", invoice_id, f"{len(body.lines)} lignes")
    return _invoice_lines(db, invoice_id)


@router.post("/invoices/{invoice_id}/lines/import")
async def import_invoice_lines_excel(
    invoice_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "update")),
):
    from app.services.document_lines_import import parse_document_lines_excel
    from app.upload_limits import read_bounded, assert_extension, SPREADSHEET_EXT
    from app.fiscal_service import get_default_vat_rate

    inv = get_entity_or_404(db, Invoice, invoice_id, get_company_id(db, user), "Facture")
    assert_invoice_mutable(inv, user, db)
    assert_extension(file.filename, SPREADSHEET_EXT)
    content = await read_bounded(file)
    parsed = parse_document_lines_excel(content, file.filename or "upload.xlsx", get_default_vat_rate(db))
    if not parsed.get("lines"):
        raise HTTPException(400, parsed.get("message", "Aucune ligne valide"))
    body = schemas.DocumentLinesReplace(lines=[schemas.DocumentLineIn(**ln) for ln in parsed["lines"]])
    return replace_invoice_lines(invoice_id, body, request, db, user)


@router.post("/quotes/{quote_id}/convert-to-invoice", response_model=schemas.InvoiceOut)
def api_convert_quote(
    quote_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    try:
        inv = convert_quote_to_invoice(db, quote_id, company_id=get_company_id(db, user))
    except ValueError as e:
        raise HTTPException(404, str(e))
    _audit(request, user, db, "create", "invoices", "invoice", inv.id, f"Depuis devis {quote_id}")
    return inv


@router.post("/invoices/{invoice_id}/credit-note", response_model=schemas.InvoiceOut)
def api_credit_note(
    invoice_id: int,
    request: Request,
    amount: float | None = None,
    credit_note_type: str = "RETURN",
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    try:
        cn = create_credit_note(
            db, invoice_id, amount=amount, credit_note_type=credit_note_type,
            company_id=get_company_id(db, user),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(request, user, db, "create", "invoices", "credit_note", cn.id, f"Sur facture {invoice_id}")
    return cn


@router.post("/invoices/{invoice_id}/finalize-proforma", response_model=schemas.InvoiceOut)
def api_finalize_proforma(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "update")),
):
    try:
        inv = convert_proforma_to_invoice(db, invoice_id, company_id=get_company_id(db, user))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(request, user, db, "update", "invoices", "invoice", inv.id, "Proforma → facture")
    return inv


class DepositInvoiceIn(PydanticBaseModel):
    pct: float = 30


@router.post("/invoices/{invoice_id}/deposit", response_model=schemas.InvoiceOut)
def api_deposit_invoice(
    invoice_id: int,
    body: DepositInvoiceIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "create")),
):
    try:
        dep = create_deposit_invoice(db, invoice_id, pct=body.pct, company_id=get_company_id(db, user))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(request, user, db, "create", "invoices", "invoice", dep.id, f"Acompte {body.pct}% sur {invoice_id}")
    return dep


@router.post("/invoices/send-reminders")
def api_send_reminders(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "approve")),
):
    from app.services.reminder_service import send_invoice_reminders
    return send_invoice_reminders(db)


@router.get("/quotes/{quote_id}/pdf")
def quote_pdf(
    quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("quotes", "view")),
):
    quote = get_entity_or_404(db, Quote, quote_id, get_company_id(db, user), "Devis")
    client = db.query(Client).filter(Client.id == quote.client_id).first() if quote.client_id else None
    lines = db.query(DocumentLine).filter(DocumentLine.quote_id == quote_id).all()
    from app.services.pdf_branding import pdf_branding_context
    with pdf_branding_context(db):
        pdf = render_quote_pdf(quote, client, lines)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{quote.number}.pdf"'})


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("invoices", "view")),
):
    mark_overdue_invoices(db)
    inv = get_entity_or_404(db, Invoice, invoice_id, get_company_id(db, user), "Facture")
    client = db.query(Client).filter(Client.id == inv.client_id).first() if inv.client_id else None
    lines = db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice_id).all()
    from app.services.pdf_branding import pdf_branding_context
    with pdf_branding_context(db):
        pdf = render_invoice_pdf(inv, client, lines)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{inv.number}.pdf"'})


@router.get("/journal-entries/{entry_id}/pdf")
def journal_entry_pdf(
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "view")),
):
    entry = db.query(JournalEntry).filter(JournalEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404)
    lines = db.query(JournalLine).filter(JournalLine.entry_id == entry_id).order_by(JournalLine.id).all()
    pdf = render_journal_entry_pdf(entry, lines)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{entry.reference or entry_id}.pdf"'})


@router.post("/invoices/sync-overdue")
def sync_overdue(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "view")),
):
    n = mark_overdue_invoices(db)
    return {"updated": n}
