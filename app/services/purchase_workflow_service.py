"""Workflow achats Phase 2: DA -> BC -> Réception -> Facture + contrôle 3-way match."""
from __future__ import annotations

from datetime import date, datetime, timezone
from sqlalchemy.orm import Session

from app.models_erp import (
    PurchaseRequest, PurchaseRequestLine,
    PurchaseOrder, PurchaseOrderLine,
    GoodsReceipt, GoodsReceiptLine,
    SupplierInvoice,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _next_number(db: Session, model, prefix: str) -> str:
    n = db.query(model).count() + 1
    return f"{prefix}-{date.today().year}-{n:04d}"


def create_purchase_request(db: Session, body: dict, user_id: int | None = None) -> PurchaseRequest:
    row = PurchaseRequest(
        number=body.get("number") or _next_number(db, PurchaseRequest, "DA"),
        supplier_id=body.get("supplier_id"),
        date=body.get("date") or date.today(),
        status="brouillon",
        requested_by=user_id,
        notes=body.get("notes") or "",
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(row)
    db.flush()
    for i, ln in enumerate(body.get("lines") or []):
        db.add(PurchaseRequestLine(
            purchase_request_id=row.id,
            stock_item_id=ln.get("stock_item_id"),
            description=ln.get("description") or "",
            quantity=float(ln.get("quantity") or 0),
            unit_cost=float(ln.get("unit_cost") or 0),
            position=i,
        ))
    db.commit()
    db.refresh(row)
    return row


def approve_purchase_request(db: Session, request_id: int, user_id: int) -> PurchaseRequest:
    row = db.query(PurchaseRequest).filter(PurchaseRequest.id == request_id).first()
    if not row:
        raise ValueError("Demande d'achat introuvable")
    if row.status not in ("brouillon", "rejetée"):
        raise ValueError("Demande d'achat déjà traitée")
    row.status = "validée"
    row.approved_by = user_id
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def create_purchase_order_from_request(
    db: Session, request_id: int, *, expected_date: date | None = None, user_id: int | None = None
) -> PurchaseOrder:
    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == request_id).first()
    if not req:
        raise ValueError("Demande d'achat introuvable")
    if req.status not in ("validée", "convertie"):
        raise ValueError("La demande d'achat doit être validée avant conversion BC")

    po = PurchaseOrder(
        number=_next_number(db, PurchaseOrder, "BC"),
        purchase_request_id=req.id,
        supplier_id=req.supplier_id,
        date=date.today(),
        expected_date=expected_date,
        status="brouillon",
        approved_by=user_id,
        notes=req.notes or "",
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(po)
    db.flush()

    lines = db.query(PurchaseRequestLine).filter(
        PurchaseRequestLine.purchase_request_id == req.id
    ).order_by(PurchaseRequestLine.position).all()
    for i, ln in enumerate(lines):
        db.add(PurchaseOrderLine(
            purchase_order_id=po.id,
            stock_item_id=ln.stock_item_id,
            description=ln.description,
            quantity=ln.quantity,
            unit_cost=ln.unit_cost,
            position=i,
        ))
    req.status = "convertie"
    req.updated_at = _now()
    db.commit()
    db.refresh(po)
    return po


def approve_purchase_order(db: Session, order_id: int, user_id: int) -> PurchaseOrder:
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not po:
        raise ValueError("Bon de commande introuvable")
    if po.status not in ("brouillon",):
        raise ValueError("Bon de commande déjà validé")
    po.status = "validée"
    po.approved_by = user_id
    po.updated_at = _now()
    db.commit()
    db.refresh(po)
    return po


def evaluate_three_way_match(db: Session, supplier_invoice_id: int) -> dict:
    inv = db.query(SupplierInvoice).filter(SupplierInvoice.id == supplier_invoice_id).first()
    if not inv:
        raise ValueError("Facture fournisseur introuvable")
    if not inv.purchase_order_id:
        inv.three_way_status = "pending"
        inv.three_way_detail = "Aucun BC lié"
        db.commit()
        return {"ok": True, "status": inv.three_way_status, "detail": inv.three_way_detail}

    po_lines = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.purchase_order_id == inv.purchase_order_id
    ).all()
    receipts = db.query(GoodsReceipt).filter(
        GoodsReceipt.purchase_order_id == inv.purchase_order_id,
        GoodsReceipt.status == "validée",
    ).all()
    gr_ids = [r.id for r in receipts]
    gr_lines = db.query(GoodsReceiptLine).filter(GoodsReceiptLine.goods_receipt_id.in_(gr_ids)).all() if gr_ids else []

    po_total = sum(float((ln.quantity or 0) * (ln.unit_cost or 0)) for ln in po_lines)
    gr_total = sum(float((ln.quantity or 0) * (ln.unit_cost or 0)) for ln in gr_lines)
    inv_total = float(inv.amount or 0)

    tol = max(1000.0, 0.01 * max(po_total, inv_total, 1.0))  # tolérance minimale 1000 XOF
    ok_po_inv = abs(po_total - inv_total) <= tol
    ok_gr_inv = abs(gr_total - inv_total) <= tol
    ok_qty = (sum(float(ln.quantity or 0) for ln in gr_lines) + 1e-9) >= (sum(float(ln.quantity or 0) for ln in po_lines) * 0.9)

    matched = bool(receipts) and ok_po_inv and ok_gr_inv and ok_qty
    inv.three_way_status = "matched" if matched else "mismatch"
    inv.three_way_detail = (
        f"PO={po_total:.2f}; GR={gr_total:.2f}; INV={inv_total:.2f}; "
        f"receipts={len(receipts)}; ok_qty={ok_qty}; tol={tol:.2f}"
    )

    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == inv.purchase_order_id).first()
    if po:
        po.status = "facturée" if matched else ("partiellement_reçue" if receipts else po.status)
        po.updated_at = _now()
    db.commit()
    return {
        "ok": True,
        "status": inv.three_way_status,
        "detail": inv.three_way_detail,
        "totals": {"po": po_total, "gr": gr_total, "invoice": inv_total, "tolerance": tol},
    }


def create_goods_receipt_from_order(db: Session, order_id: int) -> GoodsReceipt:
    """Crée un bon de réception brouillon à partir des lignes du BC."""
    from app.services.goods_receipt_service import create_goods_receipt

    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not po:
        raise ValueError("Bon de commande introuvable")
    if po.status not in ("validée", "partiellement_reçue"):
        raise ValueError("Le BC doit être validé avant réception")

    lines = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.purchase_order_id == po.id
    ).order_by(PurchaseOrderLine.position).all()
    if not lines:
        raise ValueError("BC sans lignes")

    payload = {
        "supplier_id": po.supplier_id,
        "purchase_order_id": po.id,
        "purchase_request_id": po.purchase_request_id,
        "notes": f"Réception auto depuis {po.number}",
        "lines": [
            {
                "stock_item_id": ln.stock_item_id,
                "description": ln.description,
                "quantity": ln.quantity,
                "unit_cost": ln.unit_cost,
            }
            for ln in lines
        ],
    }
    gr = create_goods_receipt(db, payload)
    po.status = "partiellement_reçue"
    po.updated_at = _now()
    db.commit()
    db.refresh(gr)
    return gr


def record_supplier_payment(
    db: Session,
    invoice_id: int,
    amount: float,
    *,
    user_id: int | None = None,
    movement_type: str = "banque_sortie",
    bank_account_id: int | None = None,
    reference: str = "",
) -> dict:
    """Enregistre un paiement fournisseur (trésorerie + mise à jour facture)."""
    from app.models_erp import TreasuryMovement, BankAccount

    inv = db.query(SupplierInvoice).filter(SupplierInvoice.id == invoice_id).first()
    if not inv:
        raise ValueError("Facture fournisseur introuvable")
    if inv.status not in ("validée", "payée", "en retard"):
        raise ValueError("La facture doit être validée avant paiement")

    reste = max(0.0, float(inv.amount or 0) - float(inv.paid or 0))
    pay = min(float(amount or 0), reste)
    if pay <= 0:
        raise ValueError("Montant invalide ou facture déjà soldée")

    inv.paid = float(inv.paid or 0) + pay
    if inv.paid >= float(inv.amount or 0) - 1e-6:
        inv.status = "payée"
        inv.payment_date = date.today()
    inv.updated_at = _now()

    tm = TreasuryMovement(
        date=date.today(),
        type=movement_type,
        bank_account_id=bank_account_id,
        label=f"Paiement fournisseur {inv.number}",
        amount=pay,
        category="achats",
        reference=reference or inv.number or "",
        notes=f"supplier_invoice_id={inv.id}",
    )
    db.add(tm)
    if bank_account_id and movement_type in ("banque_entree", "banque_sortie"):
        bank = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
        if bank:
            if movement_type == "banque_entree":
                bank.balance = (bank.balance or 0) + pay
            else:
                bank.balance = (bank.balance or 0) - pay

    db.commit()
    db.refresh(inv)
    return {
        "ok": True,
        "paid_amount": pay,
        "invoice_id": inv.id,
        "invoice_status": inv.status,
        "treasury_movement_id": tm.id,
        "remaining": max(0.0, float(inv.amount or 0) - float(inv.paid or 0)),
    }
