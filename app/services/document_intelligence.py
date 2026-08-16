"""Moteur d'intelligence documentaire — détection, extraction, validation, apprentissage."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

# ——— Types de documents ———
DOC_INVOICE = "invoice"
DOC_BANK = "bank_statement"
DOC_PO = "purchase_order"
DOC_DELIVERY = "delivery_note"
DOC_LEDGER = "accounting_entry"
DOC_UNKNOWN = "unknown"

DOC_LABELS = {
    DOC_INVOICE: "Facture",
    DOC_BANK: "Relevé bancaire",
    DOC_PO: "Bon de commande",
    DOC_DELIVERY: "Bon de livraison",
    DOC_LEDGER: "Pièce comptable",
    DOC_UNKNOWN: "Document non classé",
}

_AMOUNT_RE = r"([\d\s]+(?:[.,]\d{1,2})?)"
_DATE_RE = r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _parse_amount(raw: str | None) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).replace("\u00a0", " ").replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _first_match(text: str, patterns: list[str], group: int = 1) -> str:
    for pat in patterns:
        m = re.search(pat, text, re.I | re.M)
        if m:
            return (m.group(group) or "").strip()[:200]
    return ""


def _first_amount(text: str, patterns: list[str]) -> Optional[float]:
    for pat in patterns:
        m = re.search(pat, text, re.I | re.M)
        if m:
            v = _parse_amount(m.group(1))
            if v is not None:
                return v
    return None


def detect_document_type(text: str) -> tuple[str, float]:
    """Retourne (type, score confiance 0-1)."""
    t = _norm(text)
    scores: dict[str, float] = {DOC_INVOICE: 0, DOC_BANK: 0, DOC_PO: 0, DOC_DELIVERY: 0, DOC_LEDGER: 0}
    if re.search(r"\b(facture|invoice|avoir|fact\.?)\b", t):
        scores[DOC_INVOICE] += 0.45
    if re.search(r"\b(tva|ttc|ht|montant total|total général)\b", t):
        scores[DOC_INVOICE] += 0.25
    if re.search(r"\b(relevé|releve|solde initial|solde final|débit|debit|crédit|credit)\b", t):
        scores[DOC_BANK] += 0.5
    if re.search(r"\b(compte bancaire|iban|rib|n° compte)\b", t):
        scores[DOC_BANK] += 0.2
    if re.search(r"\b(bon de commande|commande n|purchase order)\b", t):
        scores[DOC_PO] += 0.55
    if re.search(r"\b(bon de livraison|livraison n|delivery note)\b", t):
        scores[DOC_DELIVERY] += 0.55
    if re.search(r"\b(journal|écriture|ecriture|compte général|compte general|pièce comptable)\b", t):
        scores[DOC_LEDGER] += 0.4
    if re.search(r"\b\d{3,8}\b.*\b(débit|debit|crédit|credit)\b", t):
        scores[DOC_LEDGER] += 0.2
    best = max(scores, key=scores.get)
    score = scores[best]
    if score < 0.35:
        return DOC_UNKNOWN, 0.2
    return best, min(0.98, score + 0.15)


def _extract_party(text: str, role: str) -> dict[str, str]:
    """Extrait fournisseur ou client avec heuristiques contextuelles."""
    patterns_name = {
        "supplier": [
            r"(?:fournisseur|supplier|vendeur|émetteur|emetteur)\s*[:\s]+(.{3,80})",
            r"(?:de la part de|société|societe)\s*[:\s]+(.{3,80})",
        ],
        "client": [
            r"(?:client|customer|destinataire|facturé à|facture a)\s*[:\s]+(.{3,80})",
            r"(?:à l'attention|a l'attention)\s*[:\s]+(.{3,80})",
        ],
    }
    name = _first_match(text, patterns_name.get(role, []))
    if not name:
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 3]
        if lines and role == "supplier":
            name = lines[0][:80]
    return {
        f"{role}_name": name,
        f"{role}_address": _first_match(text, [rf"(?:adresse|address)\s*[:\s]+(.{{5,120}})"]),
        f"{role}_phone": _first_match(text, [r"(?:tél|tel|téléphone|telephone|phone)\s*[:\s]*([+\d\s./-]{8,20})"]),
        f"{role}_email": _first_match(text, [r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"]),
    }


def _extract_line_items(text: str) -> list[dict[str, Any]]:
    """Détecte les lignes tabulaires (description + qté + PU + total)."""
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = line.strip()
        if len(raw) < 8 or re.match(r"^(total|sous-total|tva|ht|ttc)", raw, re.I):
            continue
        # description ... qty unit_price total
        m = re.match(
            rf"^(.{{4,60}}?)\s+(\d+(?:[.,]\d+)?)\s+{_AMOUNT_RE}\s+{_AMOUNT_RE}\s*$",
            raw,
        )
        if m:
            desc, qty, pu, tot = m.groups()
            items.append({
                "description": desc.strip(),
                "quantity": _parse_amount(qty),
                "unit_price": _parse_amount(pu),
                "total": _parse_amount(tot),
                "discount": None,
            })
            continue
        # description ... amount only
        m2 = re.match(rf"^(.{4,70}?)\s+{_AMOUNT_RE}\s*$", raw)
        if m2 and _parse_amount(m2.group(2)):
            items.append({
                "description": m2.group(1).strip(),
                "quantity": 1,
                "unit_price": _parse_amount(m2.group(2)),
                "total": _parse_amount(m2.group(2)),
                "discount": None,
            })
    return items[:50]


def extract_invoice(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "document_type": DOC_INVOICE,
        "invoice_number": _first_match(text, [
            r"(?:facture|invoice|n°|no|numéro|numero)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/]{2,30})",
        ]),
        "invoice_date": _first_match(text, [
            rf"(?:date\s*(?:facture|invoice)?|date)\s*[:\s]*{_DATE_RE}",
            rf"(?:émise? le|emise le)\s*{_DATE_RE}",
        ]),
        "due_date": _first_match(text, [
            rf"(?:échéance|echeance|due date|à payer le|a payer le)\s*[:\s]*{_DATE_RE}",
        ]),
        "currency": _first_match(text, [r"\b(FCFA|XOF|EUR|USD|€|\$)\b"]) or "FCFA",
        "nif": _first_match(text, [r"(?:nif|n\.i\.f)\s*[:\s]*([A-Z0-9\-/]+)"]),
        "rccm": _first_match(text, [r"(?:rccm|r\.c\.c\.m)\s*[:\s]*([A-Z0-9\-/]+)"]),
    }
    data.update(_extract_party(text, "supplier"))
    data.update(_extract_party(text, "client"))
    data["total_ht"] = _first_amount(text, [
        rf"(?:total\s*ht|montant\s*ht|h\.t\.?)\s*[:\s]*{_AMOUNT_RE}",
    ])
    data["total_vat"] = _first_amount(text, [
        rf"(?:tva|vat)\s*(?:\d+%)?\s*[:\s]*{_AMOUNT_RE}",
    ])
    data["total_ttc"] = _first_amount(text, [
        rf"(?:total\s*ttc|montant\s*ttc|t\.t\.c\.?|net\s*à\s*payer|net a payer|total\s*général|total general)\s*[:\s]*{_AMOUNT_RE}",
        rf"(?:total|montant)\s*[:\s]*{_AMOUNT_RE}\s*(?:FCFA|XOF|EUR)",
    ])
    data["amount"] = data["total_ttc"]
    data["line_items"] = _extract_line_items(text)
    return data


def extract_bank_statement(text: str) -> dict[str, Any]:
    return {
        "document_type": DOC_BANK,
        "bank_name": _first_match(text, [r"(?:banque|bank)\s*[:\s]+(.{3,60})"]),
        "account_number": _first_match(text, [
            r"(?:compte|n° compte|account)\s*[:\s]*([A-Z0-9\s\-]{6,34})",
            r"(?:iban)\s*[:\s]*([A-Z0-9\s]{10,34})",
        ]),
        "period": _first_match(text, [
            r"(?:période|periode|du)\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\s*(?:au|à|a)\s*\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})",
        ]),
        "opening_balance": _first_amount(text, [rf"(?:solde initial|ancien solde)\s*[:\s]*{_AMOUNT_RE}"]),
        "closing_balance": _first_amount(text, [rf"(?:solde final|nouveau solde|solde au)\s*[:\s]*{_AMOUNT_RE}"]),
        "transactions": _extract_bank_transactions(text),
        "amount": _first_amount(text, [rf"(?:solde final|nouveau solde)\s*[:\s]*{_AMOUNT_RE}"]),
    }


def _extract_bank_transactions(text: str) -> list[dict[str, Any]]:
    txns: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(
            rf"({_DATE_RE})\s+(.{{5,50}}?)\s+({_AMOUNT_RE})?\s+({_AMOUNT_RE})?\s+({_AMOUNT_RE})?",
            line.strip(),
        )
        if not m:
            continue
        date_s, label, debit, credit, balance = m.groups()
        d = _parse_amount(debit)
        c = _parse_amount(credit)
        if d or c:
            txns.append({
                "date": date_s,
                "label": label.strip(),
                "debit": d,
                "credit": c,
                "balance": _parse_amount(balance),
                "reference": "",
            })
    return txns[:100]


def extract_purchase_order(text: str) -> dict[str, Any]:
    data = {
        "document_type": DOC_PO,
        "order_number": _first_match(text, [
            r"(?:commande|bon de commande|purchase order|n°)\s*[:\s#]*([A-Z0-9\-/]{3,30})",
        ]),
        "order_date": _first_match(text, [rf"(?:date)\s*[:\s]*{_DATE_RE}"]),
        "line_items": _extract_line_items(text),
    }
    data.update(_extract_party(text, "supplier"))
    data["amount"] = _first_amount(text, [rf"(?:total)\s*[:\s]*{_AMOUNT_RE}"])
    return data


def extract_delivery_note(text: str) -> dict[str, Any]:
    data = {
        "document_type": DOC_DELIVERY,
        "delivery_number": _first_match(text, [
            r"(?:livraison|bon de livraison|bl)\s*[:\s#]*([A-Z0-9\-/]{3,30})",
        ]),
        "delivery_date": _first_match(text, [rf"(?:date)\s*[:\s]*{_DATE_RE}"]),
        "line_items": _extract_line_items(text),
    }
    data.update(_extract_party(text, "client"))
    return data


def extract_accounting_entry(text: str) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    for raw in text.splitlines():
        m = re.match(
            rf"({_DATE_RE})?\s*(\d{{3,8}})\s+(.{{5,80}}?)\s+({_AMOUNT_RE})?\s+({_AMOUNT_RE})?",
            raw.strip(),
        )
        if m:
            date_s, account, label, debit, credit = m.groups()
            d = _parse_amount(debit)
            c = _parse_amount(credit)
            if d or c:
                lines.append({
                    "date": date_s or "",
                    "account_code": account,
                    "label": label.strip(),
                    "debit": d,
                    "credit": c,
                    "reference": "",
                })
    return {
        "document_type": DOC_LEDGER,
        "journal": _first_match(text, [r"(?:journal)\s*[:\s]+([A-Z0-9]{1,10})"]),
        "reference": _first_match(text, [r"(?:pièce|piece|réf|référence)\s*[:\s]+([A-Z0-9\-/]+)"]),
        "entries": lines[:80],
        "amount": sum((l.get("debit") or 0) for l in lines) or None,
    }


def apply_learned_patterns(text: str, patterns: list[dict]) -> dict[str, Any]:
    """Applique les corrections mémorisées."""
    patches: dict[str, Any] = {}
    for p in patterns:
        field_key = p.get("field_key")
        regex = p.get("pattern")
        if not field_key or not regex:
            continue
        try:
            m = re.search(regex, text, re.I | re.M)
            if m:
                val = m.group(1) if m.lastindex else m.group(0)
                patches[field_key] = str(val).strip()[:200]
        except re.error:
            continue
    return patches


def extract_structured(text: str, doc_type: str | None = None, learned: list[dict] | None = None) -> dict[str, Any]:
    text = text or ""
    if not doc_type:
        doc_type, type_conf = detect_document_type(text)
    else:
        type_conf = 0.85
    extractors = {
        DOC_INVOICE: extract_invoice,
        DOC_BANK: extract_bank_statement,
        DOC_PO: extract_purchase_order,
        DOC_DELIVERY: extract_delivery_note,
        DOC_LEDGER: extract_accounting_entry,
    }
    if doc_type in extractors:
        data = extractors[doc_type](text)
    else:
        data = extract_invoice(text)
        data["document_type"] = DOC_UNKNOWN
    if learned:
        data.update({k: v for k, v in apply_learned_patterns(text, learned).items() if v})
    data["document_type"] = doc_type if doc_type != DOC_UNKNOWN else data.get("document_type", DOC_UNKNOWN)
    data["document_label"] = DOC_LABELS.get(data["document_type"], "Document")
    data["type_confidence"] = round(type_conf, 2)
    data["confidence"] = _score_confidence(data)
    return data


def _score_confidence(data: dict) -> str:
    score = 0.0
    doc_type = data.get("document_type")
    if doc_type == DOC_INVOICE:
        if data.get("invoice_number"):
            score += 0.2
        if data.get("amount") or data.get("total_ttc"):
            score += 0.25
        if data.get("supplier_name"):
            score += 0.15
        if data.get("invoice_date"):
            score += 0.1
        if data.get("line_items"):
            score += 0.1
    elif doc_type == DOC_BANK:
        if data.get("account_number"):
            score += 0.25
        if data.get("transactions"):
            score += 0.25
        if data.get("closing_balance") is not None:
            score += 0.2
    else:
        if data.get("amount"):
            score += 0.3
        if data.get("line_items") or data.get("entries"):
            score += 0.2
    score += float(data.get("type_confidence") or 0) * 0.2
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


@dataclass
class ValidationIssue:
    severity: str  # error | warning | info
    field: str
    message: str
    code: str = ""


def validate_extraction(data: dict, *, db: Session | None = None) -> list[dict]:
    """Contrôles métier automatiques."""
    issues: list[ValidationIssue] = []
    doc_type = data.get("document_type", DOC_UNKNOWN)

    if doc_type == DOC_INVOICE:
        ht = data.get("total_ht")
        tva = data.get("total_vat")
        ttc = data.get("total_ttc") or data.get("amount")
        if ht and tva and ttc:
            calc = round((ht or 0) + (tva or 0), 2)
            if abs(calc - ttc) > max(1.0, ttc * 0.02):
                issues.append(ValidationIssue(
                    "error", "totals",
                    f"Incohérence HT+TVA ({fmt_num(calc)}) ≠ TTC ({fmt_num(ttc)})",
                    "TOTAL_MISMATCH",
                ))
        if not data.get("invoice_number"):
            issues.append(ValidationIssue("warning", "invoice_number", "Numéro de facture non détecté", "MISSING_NUMBER"))
        if not ttc:
            issues.append(ValidationIssue("warning", "amount", "Montant TTC non détecté", "MISSING_AMOUNT"))
        if not data.get("supplier_name"):
            issues.append(ValidationIssue("warning", "supplier_name", "Fournisseur non identifié", "MISSING_SUPPLIER"))
        for i, line in enumerate(data.get("line_items") or []):
            q, pu, tot = line.get("quantity"), line.get("unit_price"), line.get("total")
            if q and pu and tot and abs(q * pu - tot) > max(0.5, tot * 0.03):
                issues.append(ValidationIssue(
                    "warning", f"line_items[{i}]",
                    f"Ligne « {line.get('description', '')[:30]} » : qté×PU ≠ total",
                    "LINE_MATH",
                ))

    if doc_type == DOC_BANK:
        if not data.get("account_number"):
            issues.append(ValidationIssue("warning", "account_number", "Numéro de compte non détecté", "MISSING_ACCOUNT"))
        opening = data.get("opening_balance")
        closing = data.get("closing_balance")
        txns = data.get("transactions") or []
        if opening is not None and closing is not None and txns:
            net = sum((t.get("credit") or 0) - (t.get("debit") or 0) for t in txns)
            expected = round(opening + net, 2)
            if abs(expected - closing) > max(1.0, abs(closing) * 0.02):
                issues.append(ValidationIssue(
                    "warning", "closing_balance",
                    f"Solde final incohérent avec les mouvements (attendu ~{fmt_num(expected)})",
                    "BALANCE_MISMATCH",
                ))

    if doc_type == DOC_LEDGER:
        entries = data.get("entries") or []
        total_d = sum(e.get("debit") or 0 for e in entries)
        total_c = sum(e.get("credit") or 0 for e in entries)
        if entries and abs(total_d - total_c) > max(0.01, total_d * 0.01):
            issues.append(ValidationIssue(
                "error", "entries",
                f"Écriture déséquilibrée : débits {fmt_num(total_d)} ≠ crédits {fmt_num(total_c)}",
                "LEDGER_UNBALANCED",
            ))

    # Doublons facture fournisseur
    if db and doc_type == DOC_INVOICE and data.get("invoice_number"):
        try:
            from app.models_erp import Supplier, SupplierInvoice
            num = data["invoice_number"]
            dup = db.query(SupplierInvoice).filter(SupplierInvoice.number == num).first()
            if dup:
                issues.append(ValidationIssue(
                    "error", "invoice_number",
                    f"Facture fournisseur #{num} déjà enregistrée (id {dup.id})",
                    "DUPLICATE_INVOICE",
                ))
            sup_name = (data.get("supplier_name") or "").strip()
            if sup_name:
                match = db.query(Supplier).filter(Supplier.name.ilike(f"%{sup_name[:40]}%")).first()
                if match:
                    data["suggested_supplier_id"] = match.id
                    data["suggested_supplier_name"] = match.name
                else:
                    issues.append(ValidationIssue(
                        "info", "supplier_name",
                        f"Fournisseur « {sup_name} » inconnu — création suggérée à la validation",
                        "NEW_SUPPLIER",
                    ))
        except Exception:
            pass

    return [{"severity": i.severity, "field": i.field, "message": i.message, "code": i.code} for i in issues]


def fmt_num(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ")


def record_learning(db: Session, document_type: str, field_key: str, raw_text: str, old_value: str, new_value: str, user_id: int | None):
    """Mémorise une correction utilisateur pour améliorer les extractions futures."""
    from app.models_enterprise import OcrLearningPattern

    if not new_value or old_value == new_value:
        return
    pattern = ""
    snippet = ""
    if old_value and old_value in raw_text:
        idx = raw_text.find(old_value)
        snippet = raw_text[max(0, idx - 40): idx + len(old_value) + 40]
        escaped = re.escape(old_value)
        pattern = rf"({escaped})"
    elif new_value:
        # Ancre sur le libellé du champ
        anchors = {
            "supplier_name": r"(?:fournisseur|supplier|vendeur)\s*[:\s]+(.{3,80})",
            "invoice_number": r"(?:facture|invoice|n°)\s*[:\s#]*([A-Z0-9\-/]{3,30})",
            "client_name": r"(?:client|destinataire)\s*[:\s]+(.{3,80})",
        }
        pattern = anchors.get(field_key, "")
    if not pattern:
        return
    row = db.query(OcrLearningPattern).filter(
        OcrLearningPattern.document_type == document_type,
        OcrLearningPattern.field_key == field_key,
        OcrLearningPattern.pattern == pattern,
    ).first()
    if row:
        row.replacement_value = new_value[:500]
        row.hit_count = (row.hit_count or 0) + 1
        row.context_snippet = snippet[:500]
    else:
        row = OcrLearningPattern(
            document_type=document_type,
            field_key=field_key,
            pattern=pattern[:500],
            replacement_value=new_value[:500],
            context_snippet=snippet[:500],
            user_id=user_id,
            hit_count=1,
            created_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        )
        db.add(row)


def load_learning_patterns(db: Session, document_type: str | None = None) -> list[dict]:
    from app.models_enterprise import OcrLearningPattern
    q = db.query(OcrLearningPattern).order_by(OcrLearningPattern.hit_count.desc())
    if document_type:
        q = q.filter(OcrLearningPattern.document_type == document_type)
    return [
        {
            "field_key": r.field_key,
            "pattern": r.pattern,
            "replacement_value": r.replacement_value,
        }
        for r in q.limit(200).all()
    ]


def analyze_document_text(text: str, db: Session | None = None, document_type: str | None = None) -> dict[str, Any]:
    learned = load_learning_patterns(db, document_type) if db else []
    data = extract_structured(text, document_type, learned)
    # Appliquer remplacements appris (valeur directe si pattern matche)
    for p in learned:
        fk = p.get("field_key")
        pat = p.get("pattern")
        repl = p.get("replacement_value")
        if fk and pat and repl:
            try:
                if re.search(pat, text, re.I | re.M):
                    data[fk] = repl
            except re.error:
                pass
    issues = validate_extraction(data, db=db)
    errors = [i for i in issues if i["severity"] == "error"]
    data["validation"] = issues
    data["validation_ok"] = len(errors) == 0
    data["precision_estimate"] = _precision_estimate(data, issues)
    return data


def _precision_estimate(data: dict, issues: list[dict]) -> float:
    base = {"high": 0.92, "medium": 0.72, "low": 0.45}.get(data.get("confidence", "low"), 0.5)
    penalty = sum(0.08 if i["severity"] == "error" else 0.03 for i in issues)
    return round(max(0.1, min(0.99, base - penalty)), 2)
