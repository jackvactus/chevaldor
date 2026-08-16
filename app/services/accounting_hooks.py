"""Point d'entrée unique du moteur comptable — plus d'exceptions silencieuses."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models import Invoice
from app.models_erp import SupplierInvoice
from app.models_accounting import AccountingTransaction

logger = logging.getLogger("peya.accounting")


def _record_failure(db: Session, source_type: str, source_id: int, label: str, error: str) -> None:
    tx = db.query(AccountingTransaction).filter(
        AccountingTransaction.source_type == source_type,
        AccountingTransaction.source_id == source_id,
    ).first()
    if not tx:
        tx = AccountingTransaction(source_type=source_type, source_id=source_id, label=label)
        db.add(tx)
    tx.status = "error"
    tx.error_message = (error or "")[:2000]
    db.commit()
    logger.error("Comptabilisation échouée %s#%s : %s", source_type, source_id, error)


def dispatch_invoice_posting(db: Session, invoice: Invoice, *, force: bool = False) -> dict:
    from app.services.accounting_engine import on_invoice_validated, POSTING_STATUSES_INVOICE

    if invoice.status not in POSTING_STATUSES_INVOICE:
        return {"skipped": True, "reason": "status"}
    if getattr(invoice, "journal_entry_id", None) and not force:
        return {"skipped": True, "reason": "already_posted"}
    try:
        tx = on_invoice_validated(db, invoice, force=force)
        return {"ok": True, "journal_entry_id": tx.journal_entry_id if tx else None}
    except Exception as exc:
        _record_failure(db, "invoice", invoice.id, invoice.number or "", str(exc))
        return {"ok": False, "error": str(exc)}


def dispatch_supplier_invoice_posting(db: Session, inv: SupplierInvoice, *, force: bool = False) -> dict:
    from app.services.accounting_engine import on_supplier_invoice_validated, POSTING_STATUSES_PURCHASE

    if inv.status not in POSTING_STATUSES_PURCHASE:
        return {"skipped": True, "reason": "status"}
    if getattr(inv, "journal_entry_id", None) and not force:
        return {"skipped": True, "reason": "already_posted"}
    try:
        tx = on_supplier_invoice_validated(db, inv, force=force)
        return {"ok": True, "journal_entry_id": tx.journal_entry_id if tx else None}
    except Exception as exc:
        _record_failure(db, "supplier_invoice", inv.id, inv.number or "", str(exc))
        return {"ok": False, "error": str(exc)}


def dispatch_payment(
    db: Session,
    *,
    direction: str,
    amount: float,
    method: str,
    reference: str,
    label: str,
    payment_record_id: int,
    entry_date: date | None = None,
) -> dict:
    from app.services.accounting_engine import on_payment_recorded

    try:
        tx = on_payment_recorded(
            db,
            amount=amount,
            direction=direction,
            payment_method=method,
            reference=reference,
            label=label,
            source_id=payment_record_id,
            entry_date=entry_date,
        )
        return {"ok": True, "journal_entry_id": tx.journal_entry_id}
    except Exception as exc:
        st = f"payment_{direction}"
        _record_failure(db, st, payment_record_id, label, str(exc))
        return {"ok": False, "error": str(exc)}


def dispatch_stock_movement(db: Session, movement_id: int, *, force: bool = False) -> dict:
    from app.services.accounting_engine import on_stock_movement

    try:
        tx = on_stock_movement(db, movement_id, force=force)
        return {"ok": True, "journal_entry_id": tx.journal_entry_id if tx else None}
    except Exception as exc:
        _record_failure(db, "stock_movement", movement_id, "Mouvement stock", str(exc))
        return {"ok": False, "error": str(exc)}


def unpost_source(db: Session, source_type: str, source_id: int) -> None:
    """Retire l'écriture comptable (AccountingTransaction + JournalEntry + lignes, et
    l'historique lié) générée pour un document source donné, si elle existe. À appeler
    quand ce document source est supprimé alors qu'il avait déjà été comptabilisé —
    pour ne jamais laisser une écriture dans le journal référencer un document qui
    n'existe plus (cloisonnement : le journal ne doit contenir que de vraies écritures
    adossées à un document réel)."""
    from app.models_erp import JournalEntry, JournalLine
    from app.models_business_ext import JournalEntryHistory

    tx = db.query(AccountingTransaction).filter(
        AccountingTransaction.source_type == source_type,
        AccountingTransaction.source_id == source_id,
    ).first()
    if not tx:
        return
    if tx.journal_entry_id:
        db.query(JournalLine).filter(JournalLine.entry_id == tx.journal_entry_id).delete()
        db.query(JournalEntryHistory).filter(JournalEntryHistory.entry_id == tx.journal_entry_id).delete()
        entry = db.query(JournalEntry).filter(JournalEntry.id == tx.journal_entry_id).first()
        if entry:
            db.delete(entry)
    db.delete(tx)
    db.flush()
