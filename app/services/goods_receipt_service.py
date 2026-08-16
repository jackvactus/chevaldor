"""Réceptions marchandises — stock + lien achats."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models_erp import GoodsReceipt, GoodsReceiptLine, Supplier
from app.services.stock_service import apply_movement


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def next_receipt_number(db: Session) -> str:
    n = db.query(GoodsReceipt).count() + 1
    y = date.today().year
    return f"BR-{y}-{n:04d}"


def create_goods_receipt(db: Session, data: dict) -> GoodsReceipt:
    row = GoodsReceipt(
        number=data.get("number") or next_receipt_number(db),
        supplier_id=data["supplier_id"],
        purchase_request_id=data.get("purchase_request_id"),
        purchase_order_id=data.get("purchase_order_id"),
        supplier_invoice_id=data.get("supplier_invoice_id"),
        warehouse_id=data.get("warehouse_id"),
        date=data.get("date") or date.today(),
        status="brouillon",
        notes=data.get("notes") or "",
    )
    db.add(row)
    db.flush()
    for i, ln in enumerate(data.get("lines") or []):
        db.add(GoodsReceiptLine(
            goods_receipt_id=row.id,
            stock_item_id=ln.get("stock_item_id"),
            description=ln.get("description") or "",
            quantity=float(ln.get("quantity") or 0),
            unit_cost=float(ln.get("unit_cost") or 0),
            position=i,
        ))
    db.commit()
    db.refresh(row)
    return row


def validate_goods_receipt(db: Session, receipt_id: int, *, user_id: int | None = None) -> dict:
    row = db.query(GoodsReceipt).filter(GoodsReceipt.id == receipt_id).first()
    if not row:
        raise ValueError("Bon de réception introuvable")
    if row.status == "validée":
        return {"ok": True, "id": row.id, "already": True}

    lines = db.query(GoodsReceiptLine).filter(GoodsReceiptLine.goods_receipt_id == row.id).all()
    if not lines:
        raise ValueError("Aucune ligne de réception")

    moves = 0
    for ln in lines:
        if not ln.stock_item_id or (ln.quantity or 0) <= 0:
            continue
        apply_movement(
            db,
            ln.stock_item_id,
            "entrée",
            ln.quantity,
            reason=f"Réception {row.number}",
            notes=ln.description or "",
            warehouse_id=row.warehouse_id,
            user_id=user_id,
            movement_kind="entrée",
        )
        moves += 1

    row.status = "validée"
    db.commit()
    return {"ok": True, "id": row.id, "stock_movements": moves, "number": row.number}


def list_goods_receipts(db: Session) -> list[dict]:
    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    out = []
    for r in db.query(GoodsReceipt).order_by(GoodsReceipt.date.desc()).all():
        lines = db.query(GoodsReceiptLine).filter(GoodsReceiptLine.goods_receipt_id == r.id).all()
        out.append({
            "id": r.id,
            "number": r.number,
            "supplier_id": r.supplier_id,
            "supplier_name": suppliers.get(r.supplier_id, "—"),
            "date": str(r.date) if r.date else "",
            "status": r.status,
            "lines_count": len(lines),
            "supplier_invoice_id": r.supplier_invoice_id,
        })
    return out
