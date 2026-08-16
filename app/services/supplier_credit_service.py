"""Avoirs fournisseurs — annulation partielle ou totale facture achat."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models_erp import SupplierInvoice


def create_supplier_credit_note(
    db: Session,
    supplier_invoice_id: int,
    *,
    amount: float | None = None,
    notes: str = "",
) -> SupplierInvoice:
    src = db.query(SupplierInvoice).filter(SupplierInvoice.id == supplier_invoice_id).first()
    if not src:
        raise ValueError("Facture fournisseur introuvable")
    if getattr(src, "doc_type", "invoice") == "credit_note":
        raise ValueError("Impossible de créer un avoir depuis un avoir")
    if src.status not in ("validée", "payée", "en retard"):
        raise ValueError("La facture source doit être validée")

    amt = float(amount if amount is not None else src.amount or 0)
    if amt <= 0:
        raise ValueError("Montant avoir invalide")

    n = db.query(SupplierInvoice).count() + 1
    cn = SupplierInvoice(
        number=f"AF{date.today().year}-{n:04d}",
        supplier_id=src.supplier_id,
        date=date.today(),
        due_date=date.today(),
        amount=amt,
        paid=0,
        status="validée",
        doc_type="credit_note",
        related_supplier_invoice_id=src.id,
        reference=src.number or "",
        notes=notes or f"Avoir sur {src.number}",
    )
    db.add(cn)
    db.commit()
    db.refresh(cn)

    from app.services.accounting_hooks import dispatch_supplier_invoice_posting
    dispatch_supplier_invoice_posting(db, cn, force=True)
    return cn
