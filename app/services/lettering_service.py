"""Lettrage clients (411) et fournisseurs (401)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models_erp import JournalEntry, JournalLine


def open_lettering_lines(db: Session, prefix: str = "411") -> list[dict]:
    """Lignes non lettrées sur comptes tiers."""
    prefix = (prefix or "411").strip()
    rows = (
        db.query(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalLine.account_code.startswith(prefix))
        .filter((JournalLine.letter_code == "") | (JournalLine.letter_code.is_(None)))
        .order_by(JournalEntry.date.desc(), JournalLine.id.desc())
        .limit(500)
        .all()
    )
    out = []
    for ln, entry in rows:
        bal = round((ln.debit or 0) - (ln.credit or 0), 2)
        if abs(bal) < 0.01:
            continue
        out.append({
            "line_id": ln.id,
            "entry_id": entry.id,
            "date": str(entry.date) if entry.date else "",
            "journal": entry.journal,
            "reference": entry.reference,
            "account_code": ln.account_code,
            "label": ln.label or entry.label,
            "debit": ln.debit or 0,
            "credit": ln.credit or 0,
            "balance": bal,
        })
    return out


def apply_lettering(db: Session, line_ids: list[int], letter_code: str) -> dict:
    if not line_ids or not letter_code:
        raise ValueError("Lignes et code lettrage requis")
    code = letter_code.strip().upper()
    updated = 0
    total_debit = total_credit = 0.0
    lines = db.query(JournalLine).filter(JournalLine.id.in_(line_ids)).all()
    if len(lines) != len(line_ids):
        raise ValueError("Certaines lignes sont introuvables")
    for ln in lines:
        if not (ln.account_code.startswith("411") or ln.account_code.startswith("401")):
            raise ValueError(f"Compte {ln.account_code} non éligible au lettrage")
        total_debit += ln.debit or 0
        total_credit += ln.credit or 0
        ln.letter_code = code
        updated += 1
    if abs(total_debit - total_credit) > 0.02:
        db.rollback()
        raise ValueError(f"Lettrage non équilibré : débit {total_debit} ≠ crédit {total_credit}")
    db.commit()
    return {"ok": True, "letter_code": code, "lines": updated, "debit": total_debit, "credit": total_credit}


def remove_lettering(db: Session, letter_code: str) -> dict:
    if not letter_code:
        raise ValueError("Code lettrage requis")
    code = letter_code.strip().upper()
    lines = db.query(JournalLine).filter(JournalLine.letter_code == code).all()
    if not lines:
        raise ValueError(f"Aucune ligne pour le lettrage {code}")
    for ln in lines:
        ln.letter_code = ""
    db.commit()
    return {"ok": True, "letter_code": code, "lines": len(lines)}
