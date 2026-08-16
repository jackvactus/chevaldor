"""Contre-passation d'écritures comptables validées."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models_erp import JournalEntry, JournalLine
from app.fiscal_service import assert_fiscal_year_open
from app.services.accounting_reports import validate_entry_balance


def reverse_journal_entry(
    db: Session,
    entry_id: int,
    *,
    reversal_date: date | None = None,
    label: str = "",
) -> dict:
    """Génère une écriture inverse (storno) liée à l'originale."""
    entry = db.query(JournalEntry).filter(JournalEntry.id == entry_id).first()
    if not entry:
        raise ValueError("Écriture introuvable")
    if entry.status != "validée":
        raise ValueError("Seules les écritures validées peuvent être contre-passées")
    if getattr(entry, "reversed_by_id", None):
        raise ValueError("Écriture déjà contre-passée")

    existing = db.query(JournalEntry).filter(
        JournalEntry.source_type == "reversal",
        JournalEntry.source_id == entry_id,
    ).first()
    if existing:
        raise ValueError(f"Contre-passation déjà existante (#{existing.id})")

    assert_fiscal_year_open(db, entry.fiscal_year)
    lines_src = db.query(JournalLine).filter(JournalLine.entry_id == entry.id).all()
    if not lines_src:
        raise ValueError("Écriture sans lignes")

    rev_lines = []
    for ln in lines_src:
        rev_lines.append({
            "account_code": ln.account_code,
            "debit": round(ln.credit or 0, 2),
            "credit": round(ln.debit or 0, 2),
            "label": f"CP — {ln.label or entry.label}",
            "letter_code": "",
        })

    if not validate_entry_balance(rev_lines):
        raise ValueError("Contre-passation non équilibrée")

    rev_date = reversal_date or date.today()
    rev = JournalEntry(
        date=rev_date,
        journal=entry.journal,
        reference=f"CP-{entry.reference or entry.id}",
        label=label or f"Contre-passation {entry.reference or entry.label}",
        status="validée",
        fiscal_year=entry.fiscal_year,
        period=entry.period,
        source_type="reversal",
        source_id=entry.id,
    )
    db.add(rev)
    db.flush()

    for jl in rev_lines:
        db.add(JournalLine(
            entry_id=rev.id,
            account_code=jl["account_code"],
            debit=jl["debit"],
            credit=jl["credit"],
            label=jl["label"],
        ))

    entry.reversed_by_id = rev.id
    db.commit()
    return {
        "ok": True,
        "original_id": entry.id,
        "reversal_id": rev.id,
        "reference": rev.reference,
    }
