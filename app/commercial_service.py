"""Logique métier commercial (lignes, conversion, relances)."""
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Quote, Invoice, DocumentLine, Client, Deal
from app.tenant_service import filter_by_company, stamp_company
from app.services.document_calc_service import (
    line_ttc,
    line_ht as calc_line_ht,
    compute_document_totals,
    apply_document_amounts,
)


def line_total(line: DocumentLine) -> float:
    return line_ttc(
        line.quantity,
        line.unit_price,
        line.vat_rate,
        getattr(line, "discount_pct", 0) or 0,
        getattr(line, "discount_amount", 0) or 0,
    )


def _line_ht(ln: DocumentLine) -> float:
    return calc_line_ht(
        ln.quantity,
        ln.unit_price,
        getattr(ln, "discount_pct", 0) or 0,
        getattr(ln, "discount_amount", 0) or 0,
    )


def recalc_document_amount(db: Session, quote_id: Optional[int] = None, invoice_id: Optional[int] = None):
    q = db.query(DocumentLine)
    if quote_id:
        lines = q.filter(DocumentLine.quote_id == quote_id).order_by(DocumentLine.position).all()
        doc = db.query(Quote).filter(Quote.id == quote_id).first()
    else:
        lines = q.filter(DocumentLine.invoice_id == invoice_id).order_by(DocumentLine.position).all()
        doc = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not doc:
        return
    if not lines:
        return
    totals = compute_document_totals(
        db,
        lines,
        doc_vat_rate=getattr(doc, "vat_rate", None),
        discount_pct=getattr(doc, "discount_pct", 0) or 0,
        discount_amount=getattr(doc, "discount_amount", 0) or 0,
        commission_pct=(getattr(doc, "commission_pct", 0) or 0) if invoice_id else 0,
        paid=(getattr(doc, "paid", 0) or 0) if invoice_id else 0,
    )
    apply_document_amounts(doc, totals)
    db.commit()


def next_document_number(db: Session, model, prefix: str, company_id: int | None = None) -> str:
    """Numéro incrémental basé sur le MAX du suffixe numérique déjà utilisé pour ce préfixe+année
    (jamais un COUNT) : un COUNT redevient invalide et génère des collisions (violation de la
    contrainte `unique=True` sur `number`) dès qu'un devis/facture a été supprimé — le compteur
    diminue alors que les numéros déjà attribués, eux, restent en place. Confirmé en base réelle
    le 2026-07-28 : 40 devis existants mais numéro max Q2026-042 (2 devis supprimés depuis) — un
    COUNT+1 aurait recalculé "Q2026-041", qui existe déjà, provoquant un échec de création.
    """
    year = date.today().year
    stub = f"{prefix}{year}-"
    q = db.query(model.number).filter(model.number.like(f"{stub}%"))
    if company_id is not None:
        q = filter_by_company(q, model, company_id)
    max_n = 0
    for (num,) in q.all():
        suffix = (num or "")[len(stub):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return f"{stub}{max_n + 1:03d}"


def _next_invoice_number(db: Session, prefix: str = "F", company_id: int | None = None) -> str:
    return next_document_number(db, Invoice, prefix, company_id)


def next_quote_number(db: Session, company_id: int | None = None) -> str:
    return next_document_number(db, Quote, "Q", company_id)


def ensure_unique_document_number(db: Session, model, prefix: str, requested: str, company_id: int | None = None) -> str:
    """Filet de sécurité : si le numéro fourni (typiquement pré-rempli côté frontend) est déjà
    pris — cache client périmé/tronqué, création concurrente, etc. — recalcule un numéro libre
    au lieu de laisser planter la création sur une violation de contrainte d'unicité."""
    if not requested:
        return next_document_number(db, model, prefix, company_id)
    exists = db.query(model.id).filter(model.number == requested).first()
    if not exists:
        return requested
    return next_document_number(db, model, prefix, company_id)


def _get_scoped(db: Session, model, entity_id: int, company_id: int | None):
    """Récupère une entité, filtrée par société si `company_id` est fourni."""
    q = db.query(model).filter(model.id == entity_id)
    if company_id is not None:
        q = filter_by_company(q, model, company_id)
    return q.first()


def create_credit_note(
    db: Session,
    invoice_id: int,
    amount: float | None = None,
    notes: str = "",
    credit_note_type: str = "RETURN",
    company_id: int | None = None,
) -> Invoice:
    """Crée un avoir lié à une facture (montant positif en base, type credit_note)."""
    src = _get_scoped(db, Invoice, invoice_id, company_id)
    if not src:
        raise ValueError("Facture source introuvable")
    if getattr(src, "doc_type", "invoice") == "credit_note":
        raise ValueError("Impossible de créer un avoir depuis un avoir")
    amt = amount if amount is not None else (src.amount or 0)
    if amt <= 0:
        raise ValueError("Montant d'avoir invalide")
    cn = Invoice(
        number=_next_invoice_number(db, "A", company_id),
        client_id=src.client_id,
        project_id=src.project_id,
        date=date.today(),
        due_date=date.today(),
        amount=amt,
        vat_rate=src.vat_rate or 0,
        paid=0,
        status="envoyée",
        doc_type="credit_note",
        credit_note_type=credit_note_type or "RETURN",
        related_invoice_id=src.id,
        notes=notes or f"Avoir sur facture {src.number}",
    )
    stamp_company(cn, src.company_id)
    db.add(cn)
    db.flush()
    for ln in db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice_id).all():
        db.add(DocumentLine(
            invoice_id=cn.id,
            position=ln.position,
            description=f"Avoir — {ln.description}",
            quantity=ln.quantity,
            unit_price=ln.unit_price,
            vat_rate=ln.vat_rate,
            product_type=getattr(ln, "product_type", None) or "SERVICE",
            stock_item_id=ln.stock_item_id,
        ))
    db.commit()
    db.refresh(cn)
    recalc_document_amount(db, invoice_id=cn.id)
    from app.services.accounting_hooks import dispatch_invoice_posting
    dispatch_invoice_posting(db, cn)
    return cn


def convert_proforma_to_invoice(db: Session, invoice_id: int, company_id: int | None = None) -> Invoice:
    """Transforme une proforma en facture définitive (nouveau numéro F)."""
    src = _get_scoped(db, Invoice, invoice_id, company_id)
    if not src:
        raise ValueError("Document introuvable")
    if getattr(src, "doc_type", "invoice") != "proforma":
        raise ValueError("Seule une proforma peut être convertie en facture")
    src.doc_type = "invoice"
    src.number = _next_invoice_number(db, "F", company_id)
    if not src.status or src.status == "brouillon":
        src.status = "brouillon"
    db.commit()
    db.refresh(src)
    return src


def create_deposit_invoice(db: Session, invoice_id: int, pct: float = 30, company_id: int | None = None) -> Invoice:
    """Crée une facture d'acompte liée (% du montant source)."""
    src = _get_scoped(db, Invoice, invoice_id, company_id)
    if not src:
        raise ValueError("Facture source introuvable")
    doc = getattr(src, "doc_type", "invoice") or "invoice"
    if doc in ("credit_note", "deposit"):
        raise ValueError("Impossible de créer un acompte depuis ce type de document")
    pct = max(1.0, min(100.0, float(pct or 30)))
    lines_src = db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice_id).order_by(DocumentLine.position).all()
    base = float(src.amount or 0)
    if not base and lines_src:
        base = float(sum(line_total(ln) for ln in lines_src))
    dep = Invoice(
        number=_next_invoice_number(db, "AC", company_id),
        client_id=src.client_id,
        project_id=src.project_id,
        date=date.today(),
        due_date=src.due_date or date.today(),
        amount=round(base * pct / 100),
        vat_rate=src.vat_rate or 0,
        discount_pct=getattr(src, "discount_pct", 0) or 0,
        paid=0,
        status="brouillon",
        doc_type="deposit",
        related_invoice_id=src.id,
        notes=f"Acompte {pct:g}% sur facture {src.number}",
    )
    stamp_company(dep, src.company_id)
    db.add(dep)
    db.flush()
    if lines_src:
        for ln in lines_src:
            up = round(float(ln.unit_price or 0) * pct / 100)
            db.add(DocumentLine(
                invoice_id=dep.id,
                position=ln.position,
                description=f"Acompte {pct:g}% — {ln.description}",
                quantity=ln.quantity,
                unit_price=up,
                vat_rate=ln.vat_rate,
                discount_pct=getattr(ln, "discount_pct", 0) or 0,
                product_type=getattr(ln, "product_type", None) or "SERVICE",
                stock_item_id=ln.stock_item_id,
                account_code=getattr(ln, "account_code", "") or "",
            ))
    db.commit()
    db.refresh(dep)
    recalc_document_amount(db, invoice_id=dep.id)
    return dep


def mark_overdue_invoices(db: Session) -> int:
    today = date.today()
    count = 0
    for inv in db.query(Invoice).filter(
        Invoice.doc_type != "credit_note",
        Invoice.status.in_(["envoyée", "en retard"]),
        Invoice.due_date.isnot(None),
    ):
        balance = (inv.amount or 0) - (inv.paid or 0)
        if balance > 0 and inv.due_date < today and inv.status != "en retard":
            inv.status = "en retard"
            count += 1
        elif balance <= 0 and inv.status == "en retard":
            inv.status = "payée"
            count += 1
    if count:
        db.commit()
    return count


def convert_quote_to_invoice(db: Session, quote_id: int, company_id: int | None = None) -> Invoice:
    quote = _get_scoped(db, Quote, quote_id, company_id)
    if not quote:
        raise ValueError("Devis introuvable")
    inv = Invoice(
        number=_next_invoice_number(db, "F", company_id),
        client_id=quote.client_id,
        quote_id=quote.id,
        date=date.today(),
        due_date=quote.valid_until,
        amount=quote.amount,
        vat_rate=quote.vat_rate or 0,
        paid=0,
        status="brouillon",
        discount_pct=getattr(quote, "discount_pct", 0) or 0,
        discount_amount=getattr(quote, "discount_amount", 0) or 0,
        notes=f"Converti depuis devis {quote.number}",
    )
    stamp_company(inv, quote.company_id)
    db.add(inv)
    db.flush()
    for ln in db.query(DocumentLine).filter(DocumentLine.quote_id == quote_id).all():
        db.add(DocumentLine(
            invoice_id=inv.id,
            position=ln.position,
            reference=getattr(ln, "reference", "") or "",
            description=ln.description,
            unit=getattr(ln, "unit", "unité") or "unité",
            quantity=ln.quantity,
            unit_price=ln.unit_price,
            vat_rate=ln.vat_rate,
            discount_pct=getattr(ln, "discount_pct", 0) or 0,
            discount_amount=getattr(ln, "discount_amount", 0) or 0,
            product_type=getattr(ln, "product_type", "SERVICE") or "SERVICE",
            stock_item_id=getattr(ln, "stock_item_id", None),
            account_code=getattr(ln, "account_code", "") or "",
            sale_account=getattr(ln, "sale_account", "") or "",
            purchase_account=getattr(ln, "purchase_account", "") or "",
        ))
    quote.status = "accepté"
    db.commit()
    db.refresh(inv)
    recalc_document_amount(db, invoice_id=inv.id)
    return inv


def client_360(db: Session, client_id: int, company_id: int | None = None) -> dict:
    from app.services.crm_360_service import build_client_360

    if company_id is not None and not _get_scoped(db, Client, client_id, company_id):
        raise ValueError("Client introuvable")
    return build_client_360(db, client_id)
