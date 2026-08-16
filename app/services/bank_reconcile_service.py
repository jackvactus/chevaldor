"""Rapprochement bancaire — mouvements de trésorerie."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models_erp import BankAccount, TreasuryMovement, JournalLine, JournalEntry


def reconciliation_dashboard(db: Session) -> dict:
    banks = db.query(BankAccount).order_by(BankAccount.name).all()
    moves = db.query(TreasuryMovement).order_by(TreasuryMovement.date.desc()).limit(200).all()
    bank_map = {b.id: b.name for b in banks}
    unreconciled = [m for m in moves if not m.reconciled]
    journal_bank = (
        db.query(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalLine.account_code.startswith("52"))
        .order_by(JournalEntry.date.desc())
        .limit(100)
        .all()
    )
    return {
        "banks": [
            {"id": b.id, "name": b.name, "balance": b.balance or 0, "bank_name": b.bank_name}
            for b in banks
        ],
        "movements": [
            {
                "id": m.id,
                "date": str(m.date) if m.date else "",
                "type": m.type,
                "label": m.label,
                "amount": m.amount or 0,
                "bank_account_id": m.bank_account_id,
                "bank_name": bank_map.get(m.bank_account_id, ""),
                "reconciled": bool(m.reconciled),
                "reference": m.reference or "",
            }
            for m in moves
        ],
        "unreconciled_count": len(unreconciled),
        "journal_bank_lines": [
            {
                "line_id": ln.id,
                "date": str(ent.date) if ent.date else "",
                "account_code": ln.account_code,
                "label": ln.label or ent.label,
                "debit": ln.debit or 0,
                "credit": ln.credit or 0,
            }
            for ln, ent in journal_bank
        ],
    }


def reconcile_movement(db: Session, movement_id: int, *, reconciled: bool = True) -> dict:
    m = db.query(TreasuryMovement).filter(TreasuryMovement.id == movement_id).first()
    if not m:
        raise ValueError("Mouvement introuvable")
    m.reconciled = reconciled
    db.commit()
    return {"ok": True, "id": m.id, "reconciled": m.reconciled}
