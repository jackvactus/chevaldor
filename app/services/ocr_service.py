"""Extraction documentaire — PDF, images, texte + intelligence métier."""
import json
import shutil
from datetime import date as date_cls, datetime, timezone
from io import BytesIO
from pathlib import Path

from sqlalchemy.orm import Session

from app.models_enterprise import OcrExtraction
from app.services.document_intelligence import (
    DOC_LABELS,
    analyze_document_text,
    record_learning,
    validate_extraction,
)


class OcrDependencyError(Exception):
    """Dépendance OCR manquante (Tesseract, Poppler…)."""


def _tesseract_available() -> tuple[bool, str]:
    if not shutil.which("tesseract"):
        return False, "Binaire Tesseract introuvable — installez tesseract-ocr (+ fra, eng)."
    try:
        import pytesseract
        langs = pytesseract.get_languages(config="")
        if not any(l in langs for l in ("fra", "eng")):
            return False, "Langues Tesseract fra/eng manquantes — installez tesseract-ocr-fra."
        return True, ""
    except Exception as e:
        return False, str(e)


def get_ocr_capabilities() -> dict:
  ok, err = _tesseract_available()
  pdf_ocr = False
  try:
      from pdf2image import convert_from_bytes  # noqa: F401
      pdf_ocr = shutil.which("pdftoppm") is not None
  except ImportError:
      pass
  return {
      "tesseract": ok,
      "tesseract_error": err if not ok else "",
      "pdf_text": True,
      "pdf_ocr": pdf_ocr,
      "poppler": shutil.which("pdftoppm") is not None,
      "ready": ok or pdf_ocr,
  }


def extract_text_from_pdf(data: bytes) -> tuple[str, str]:
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        parts = []
        for page in reader.pages[:15]:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)
    except Exception:
        text = ""
    if len(text.strip()) >= 80:
        return text, "pdf_text"
    ok, err = _tesseract_available()
    if not ok:
        return text, "pdf_empty"
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(data, dpi=200, first_page=1, last_page=5)
        ocr_parts = [pytesseract.image_to_string(img, lang="fra+eng") for img in images]
        ocr_text = "\n".join(ocr_parts)
        if len(ocr_text.strip()) >= 20:
            return ocr_text, "pdf_ocr"
    except Exception:
        pass
    return text, "pdf_empty" if not text.strip() else "pdf_text"


def extract_text_from_image(data: bytes) -> tuple[str, str]:
    ok, err = _tesseract_available()
    if not ok:
        raise OcrDependencyError(err)
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(BytesIO(data))
        return pytesseract.image_to_string(img, lang="fra+eng"), "ocr"
    except OcrDependencyError:
        raise
    except Exception as e:
        raise OcrDependencyError(f"Échec OCR image : {e}") from e


def extract_raw_text(filename: str, data: bytes) -> tuple[str, str]:
    """Retourne (texte, méthode)."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(data)
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
        try:
            t, method = extract_text_from_image(data)
            return t, method if t.strip() else "image_empty"
        except OcrDependencyError:
            return "", "tesseract_missing"
    return data.decode("utf-8", errors="ignore")[:20000], "text"


def _parse_doc_date(raw: str) -> date_cls | None:
    raw = (raw or "").strip()[:12]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def process_upload(
    db: Session,
    filename: str,
    data: bytes,
    user_id: int,
    *,
    document_type: str | None = None,
) -> OcrExtraction:
    raw, method = extract_raw_text(filename, data)
    analysis = analyze_document_text(raw, db=db, document_type=document_type)
    analysis["extraction_method"] = method
    if method in ("image_empty", "pdf_empty", "tesseract_missing"):
        caps = get_ocr_capabilities()
        analysis.setdefault("validation", []).append({
            "severity": "error" if method == "tesseract_missing" else "warning",
            "field": "raw_text",
            "message": caps.get("tesseract_error") or "Texte non extrait — document scanné ou qualité insuffisante.",
            "code": "OCR_EMPTY",
        })
        analysis["validation_ok"] = False
    row = OcrExtraction(
        filename=filename,
        raw_text=raw[:50000],
        extracted_json=json.dumps(analysis, ensure_ascii=False),
        document_type=analysis.get("document_type", "unknown"),
        amount=analysis.get("amount") or analysis.get("total_ttc") or analysis.get("closing_balance"),
        supplier_name=analysis.get("supplier_name", "") or analysis.get("bank_name", ""),
        invoice_number=analysis.get("invoice_number", "") or analysis.get("order_number", "") or analysis.get("delivery_number", ""),
        invoice_date=analysis.get("invoice_date", "") or analysis.get("order_date", "") or analysis.get("delivery_date", ""),
        confidence_score=float(analysis.get("precision_estimate") or 0),
        validation_json=json.dumps(analysis.get("validation") or [], ensure_ascii=False),
        status="pending",
        user_id=user_id,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_extraction_payload(row: OcrExtraction) -> dict:
    data = json.loads(row.extracted_json or "{}")
    validation = json.loads(row.validation_json or "[]") if row.validation_json else data.get("validation", [])
    corrected = json.loads(row.corrected_json or "{}") if getattr(row, "corrected_json", None) else {}
    merged = {**data, **corrected}
    return {
        "id": row.id,
        "filename": row.filename,
        "document_type": row.document_type or merged.get("document_type"),
        "document_label": DOC_LABELS.get(row.document_type or merged.get("document_type", ""), "Document"),
        "extracted": merged,
        "amount": row.amount,
        "supplier_name": row.supplier_name,
        "invoice_number": row.invoice_number,
        "invoice_date": row.invoice_date,
        "confidence_score": row.confidence_score,
        "status": row.status,
        "validation": validation,
        "validation_ok": merged.get("validation_ok", True),
        "precision_estimate": merged.get("precision_estimate"),
        "extraction_method": merged.get("extraction_method"),
        "raw_preview": (row.raw_text or "")[:1200],
        "raw_text": row.raw_text or "",
        "created_at": row.created_at,
        "applied_entity_type": getattr(row, "applied_entity_type", "") or "",
        "applied_entity_id": getattr(row, "applied_entity_id", None),
    }


def save_corrections(
    db: Session,
    row: OcrExtraction,
    corrections: dict,
    user_id: int,
) -> dict:
    original = json.loads(row.extracted_json or "{}")
    corrected = {**original, **{k: v for k, v in corrections.items() if v is not None}}
    for field_key, new_val in corrections.items():
        old_val = str(original.get(field_key, "") or "")
        record_learning(
            db, row.document_type or original.get("document_type", "unknown"),
            field_key, row.raw_text or "", old_val, str(new_val or ""), user_id,
        )
    row.corrected_json = json.dumps(corrected, ensure_ascii=False)
    row.supplier_name = str(corrected.get("supplier_name") or row.supplier_name or "")
    row.invoice_number = str(
        corrected.get("invoice_number") or corrected.get("order_number") or row.invoice_number or ""
    )
    row.invoice_date = str(corrected.get("invoice_date") or row.invoice_date or "")
    row.amount = corrected.get("amount") or corrected.get("total_ttc") or row.amount
    revalidated = analyze_document_text(row.raw_text or "", db=db, document_type=row.document_type)
    for k, v in corrected.items():
        revalidated[k] = v
    issues = validate_extraction(revalidated, db=db)
    revalidated["validation"] = issues
    revalidated["validation_ok"] = not any(i["severity"] == "error" for i in issues)
    row.validation_json = json.dumps(issues, ensure_ascii=False)
    row.confidence_score = float(revalidated.get("precision_estimate") or row.confidence_score or 0)
    row.status = "corrected"
    db.commit()
    db.refresh(row)
    return get_extraction_payload(row)


def _mark_applied(row: OcrExtraction, entity_type: str, entity_id: int) -> None:
    row.status = "applied"
    row.applied_entity_type = entity_type
    row.applied_entity_id = entity_id


def apply_to_supplier_invoice(db: Session, row: OcrExtraction, user_id: int) -> dict:
    """Crée une facture fournisseur brouillon + lignes depuis l'extraction."""
    from app.models_erp import Supplier, SupplierInvoice
    from app.models_accounting import SupplierInvoiceLine

    payload = get_extraction_payload(row)
    data = payload["extracted"]
    doc_type = data.get("document_type") or row.document_type
    if doc_type not in ("invoice", "purchase_order"):
        raise ValueError("Ce document n'est pas une facture ou un bon de commande")
    issues = payload.get("validation") or []
    if any(i.get("severity") == "error" and i.get("code") == "DUPLICATE_INVOICE" for i in issues):
        raise ValueError("Facture en doublon — corrigez le numéro avant validation")

    sup_id = data.get("suggested_supplier_id")
    sup_name = (data.get("supplier_name") or "").strip()
    if not sup_id and sup_name:
        existing = db.query(Supplier).filter(Supplier.name.ilike(sup_name)).first()
        if existing:
            sup_id = existing.id
        else:
            sup = Supplier(name=sup_name, status="actif")
            db.add(sup)
            db.flush()
            sup_id = sup.id

    inv_num = data.get("invoice_number") or data.get("order_number") or f"OCR-{row.id}"
    if db.query(SupplierInvoice).filter(SupplierInvoice.number == inv_num).first():
        inv_num = f"{inv_num}-{row.id}"

    inv_date = _parse_doc_date(data.get("invoice_date") or data.get("order_date") or "") or date_cls.today()
    line_items = data.get("line_items") or []
    amount = float(data.get("total_ttc") or data.get("amount") or 0)
    if line_items:
        amount = sum(float(l.get("total") or 0) for l in line_items) or amount

    inv = SupplierInvoice(
        number=inv_num[:60],
        supplier_id=sup_id,
        date=inv_date,
        amount=amount,
        status="brouillon",
        reference=f"OCR:{row.filename}"[:120],
        notes=f"Import OCR #{row.id} — {len(line_items)} ligne(s)",
        created_by=user_id,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    db.add(inv)
    db.flush()
    for i, ln in enumerate(line_items):
        qty = float(ln.get("quantity") or 1)
        pu = float(ln.get("unit_price") or ln.get("total") or 0)
        db.add(SupplierInvoiceLine(
            supplier_invoice_id=inv.id,
            position=i + 1,
            description=str(ln.get("description") or f"Ligne {i + 1}")[:200],
            quantity=qty,
            unit_price=pu,
            vat_rate=18,
        ))
    _mark_applied(row, "supplier_invoice", inv.id)
    db.commit()
    return {
        "ok": True,
        "supplier_invoice_id": inv.id,
        "number": inv.number,
        "lines": len(line_items),
        "message": f"Facture fournisseur {inv.number} créée ({len(line_items)} ligne(s))",
    }


def apply_to_bank_statement(db: Session, row: OcrExtraction, bank_account_id: int, user_id: int) -> dict:
    from app.models_erp import BankAccount, BankStatement, BankStatementLine

    payload = get_extraction_payload(row)
    data = payload["extracted"]
    if (data.get("document_type") or row.document_type) != "bank_statement":
        raise ValueError("Ce document n'est pas un relevé bancaire")
    bank = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not bank:
        raise ValueError("Compte bancaire introuvable")

    txns = data.get("transactions") or []
    if not txns:
        raise ValueError("Aucune transaction détectée sur le relevé")

    stmt = BankStatement(
        bank_account_id=bank_account_id,
        filename=row.filename,
        imported_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        status="imported",
    )
    db.add(stmt)
    db.flush()
    dates: list[date_cls] = []
    imported = 0
    for t in txns:
        d = _parse_doc_date(t.get("date") or "") or date_cls.today()
        debit = float(t.get("debit") or 0)
        credit = float(t.get("credit") or 0)
        amt = credit - debit if (credit or debit) else 0
        if not amt:
            continue
        db.add(BankStatementLine(
            statement_id=stmt.id,
            line_date=d,
            label=str(t.get("label") or "")[:200],
            amount=amt,
            reference=str(t.get("reference") or "")[:80],
        ))
        dates.append(d)
        imported += 1
    if dates:
        stmt.period_start = min(dates)
        stmt.period_end = max(dates)
    if imported == 0:
        raise ValueError("Aucune ligne bancaire valide extraite")
    _mark_applied(row, "bank_statement", stmt.id)
    db.commit()
    return {"ok": True, "statement_id": stmt.id, "lines": imported, "message": f"Relevé importé — {imported} mouvement(s)"}


def apply_to_journal_entry(db: Session, row: OcrExtraction, user_id: int) -> dict:
    from app.models_erp import JournalEntry, JournalLine

    payload = get_extraction_payload(row)
    data = payload["extracted"]
    if (data.get("document_type") or row.document_type) != "accounting_entry":
        raise ValueError("Ce document n'est pas une pièce comptable")
    if any(i.get("code") == "LEDGER_UNBALANCED" for i in (payload.get("validation") or [])):
        raise ValueError("Écriture déséquilibrée — corrigez les montants avant intégration")

    entries = data.get("entries") or []
    if not entries:
        raise ValueError("Aucune ligne comptable détectée")

    first_date = _parse_doc_date(entries[0].get("date") or "") or date_cls.today()
    entry = JournalEntry(
        date=first_date,
        journal=str(data.get("journal") or "OD")[:10],
        reference=str(data.get("reference") or f"OCR-{row.id}")[:60],
        label=f"Import OCR {row.filename}"[:120],
        status="brouillon",
        fiscal_year=first_date.year,
        period=first_date.month,
        source_type="ocr_extraction",
        source_id=row.id,
    )
    db.add(entry)
    db.flush()
    for e in entries:
        db.add(JournalLine(
            entry_id=entry.id,
            account_code=str(e.get("account_code") or "471000")[:20],
            label=str(e.get("label") or "")[:200],
            debit=float(e.get("debit") or 0),
            credit=float(e.get("credit") or 0),
        ))
    _mark_applied(row, "journal_entry", entry.id)
    db.commit()
    return {"ok": True, "journal_entry_id": entry.id, "lines": len(entries), "message": f"Écriture brouillon #{entry.id} créée"}
