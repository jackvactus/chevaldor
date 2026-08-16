"""Logique métier stock — quantités, alertes, mouvements, transferts."""
from datetime import date, datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models import StockItem, StockMovement
from app.models_stock import Warehouse
from app.services.notify import create_app_notification


def _now_local_iso() -> str:
    """Horodatage local ISO sans fuseau — affichage fiable côté UI."""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def stamp_item_created(item: StockItem) -> None:
    now = _now_local_iso()
    if hasattr(item, "created_at") and not (getattr(item, "created_at", None) or "").strip():
        item.created_at = now
    if hasattr(item, "updated_at"):
        item.updated_at = now


def stamp_item_updated(item: StockItem) -> None:
    if hasattr(item, "updated_at"):
        item.updated_at = _now_local_iso()


def _get_attr(item: StockItem, name: str, default=0):
    return getattr(item, name, default) or default


def stock_levels(item: StockItem) -> dict:
    physical = float(item.quantity or 0)
    reserved = float(_get_attr(item, "qty_reserved"))
    on_order = float(_get_attr(item, "qty_on_order"))
    theoretical = float(_get_attr(item, "qty_theoretical")) or physical
    available = max(0.0, physical - reserved)
    min_q = float(item.min_quantity or 0)
    safety = float(_get_attr(item, "safety_stock")) or min_q
    reorder = float(_get_attr(item, "reorder_point")) or min_q
    max_q = float(_get_attr(item, "max_quantity"))
    return {
        "qty_physical": round(physical, 2),
        "qty_theoretical": round(theoretical, 2),
        "qty_reserved": round(reserved, 2),
        "qty_on_order": round(on_order, 2),
        "qty_available": round(available, 2),
        "min_quantity": round(min_q, 2),
        "max_quantity": round(max_q, 2),
        "safety_stock": round(safety, 2),
        "reorder_point": round(reorder, 2),
    }


def alert_level(item: StockItem) -> str:
    lv = stock_levels(item)
    if lv["qty_available"] <= 0:
        return "rupture"
    if lv["qty_available"] <= lv["reorder_point"]:
        return "faible"
    exp = getattr(item, "expiry_date", None)
    if exp:
        try:
            d = exp if hasattr(exp, "year") else date.fromisoformat(str(exp)[:10])
            if (d - date.today()).days <= 30:
                return "expiration"
        except (TypeError, ValueError):
            pass
    return "ok"


def item_overview(item: StockItem, warehouse_name: str = "") -> dict:
    lv = stock_levels(item)
    alert = alert_level(item)
    value = lv["qty_physical"] * float(item.unit_cost or 0)
    created = (getattr(item, "created_at", None) or "").strip()
    updated = (getattr(item, "updated_at", None) or "").strip()
    return {
        "id": item.id,
        "sku": item.sku,
        "name": item.name,
        "category": item.category or "",
        "unit": item.unit or "unité",
        "supplier": item.supplier or "",
        "location": item.location or "",
        "warehouse_id": getattr(item, "warehouse_id", None),
        "warehouse_name": warehouse_name,
        "unit_cost": item.unit_cost or 0,
        "unit_price": item.unit_price or 0,
        "product_accounting_type": getattr(item, "product_accounting_type", None) or "MERCHANDISE",
        "purchase_account": getattr(item, "purchase_account", "") or "",
        "sale_account": getattr(item, "sale_account", "") or "",
        "stock_account": getattr(item, "stock_account", "") or "",
        "vat_account": getattr(item, "vat_account", "") or "",
        "created_at": created,
        "updated_at": updated,
        "integrated_at": created or updated,
        "alert": alert,
        "stock_value": round(value, 2),
        **lv,
    }


def list_overview(db: Session) -> List[dict]:
    wh = {w.id: w.name for w in db.query(Warehouse).all()}
    items = db.query(StockItem).order_by(StockItem.name).all()
    # Backfill date d'intégration pour les articles existants sans horodatage
    need_stamp = [i for i in items if hasattr(i, "created_at") and not (getattr(i, "created_at", None) or "").strip()]
    if need_stamp:
        first_mov = {}
        for m in db.query(StockMovement).order_by(StockMovement.id.asc()).all():
            if m.item_id not in first_mov:
                first_mov[m.item_id] = (getattr(m, "logged_at", None) or "").strip() or (
                    m.date.isoformat() + "T00:00:00" if m.date else ""
                )
        changed = False
        for i in need_stamp:
            ts = first_mov.get(i.id) or _now_local_iso()
            i.created_at = ts
            if hasattr(i, "updated_at") and not (getattr(i, "updated_at", None) or "").strip():
                i.updated_at = ts
            changed = True
        if changed:
            try:
                db.commit()
            except Exception:
                db.rollback()
    return [item_overview(i, wh.get(getattr(i, "warehouse_id", None), "")) for i in items]


def stock_alerts(db: Session) -> List[dict]:
    alerts = []
    for item in db.query(StockItem).all():
        level = alert_level(item)
        if level == "ok":
            continue
        ov = item_overview(item)
        alerts.append({
            "item_id": item.id,
            "sku": item.sku,
            "name": item.name,
            "level": level,
            "qty_available": ov["qty_available"],
            "reorder_point": ov["reorder_point"],
            "message": {
                "rupture": "Rupture de stock",
                "faible": "Stock faible",
                "expiration": "Produit bientôt expiré",
            }.get(level, level),
        })
    return alerts


def apply_movement(
    db: Session,
    item_id: int,
    movement_type: str,
    quantity: float,
    reason: str = "",
    project_id: int = None,
    notes: str = "",
    warehouse_id: int = None,
    warehouse_to_id: int = None,
    user_id: int = None,
    user_email: str = "",
    movement_kind: str = None,
    mv_date=None,
    unit_cost: float = None,
) -> StockMovement:
    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise ValueError("Article introuvable")
    kind = movement_kind or movement_type
    qty_before = float(item.quantity or 0)
    delta = float(quantity or 0)
    if delta <= 0 and kind != "inventaire":
        raise ValueError("La quantité doit être strictement positive.")
    is_out = movement_type == "sortie" or kind in ("sortie", "transfert")
    if is_out and kind != "inventaire" and qty_before - delta < 0:
        raise ValueError(
            f"Stock insuffisant pour {item.name or item.sku} : "
            f"disponible {qty_before}, demandé {delta}."
        )
    if kind in ("entrée", "ajustement") and movement_type == "entrée":
        item.quantity = qty_before + delta
    elif kind == "ajustement" and movement_type == "sortie":
        item.quantity = max(0, qty_before - delta)
    elif kind == "inventaire":
        item.quantity = delta
        delta = delta - qty_before
    elif kind == "transfert":
        item.quantity = max(0, qty_before - delta)
    elif movement_type == "entrée":
        item.quantity = qty_before + delta
    else:
        item.quantity = max(0, qty_before - delta)
    qty_after = float(item.quantity or 0)
    now = _now_local_iso()
    stamp_item_updated(item)
    mov = StockMovement(
        item_id=item_id,
        date=mv_date or date.today(),
        type=movement_type,
        quantity=abs(delta) if kind != "inventaire" else quantity,
        reason=reason or kind,
        project_id=project_id,
        notes=notes,
    )
    if hasattr(StockMovement, "logged_at"):
        mov.logged_at = now
        mov.user_id = user_id
        mov.user_email = user_email or ""
        mov.warehouse_id = warehouse_id
        mov.warehouse_to_id = warehouse_to_id
        mov.qty_before = qty_before
        mov.qty_after = qty_after
        mov.movement_kind = kind
    mov.unit_cost = float(unit_cost) if unit_cost is not None else float(item.unit_cost or 0)
    db.add(mov)
    db.flush()
    try:
        from app.services.accounting_hooks import dispatch_stock_movement
        dispatch_stock_movement(db, mov.id)
    except Exception:
        pass
    lvl = alert_level(item)
    if lvl in ("rupture", "faible"):
        try:
            create_app_notification(
                db,
                user_id=user_id or 1,
                type_="warn",
                title="Alerte stock",
                message=f"{item.name} ({item.sku}) : {lvl}",
                category="stock",
            )
        except Exception:
            pass
    return mov


def update_movement(
    db: Session,
    movement_id: int,
    *,
    movement_type: str = None,
    quantity: float = None,
    reason: str = None,
    notes: str = None,
    mv_date=None,
    unit_cost: float = None,
    warehouse_id: int = None,
    warehouse_to_id: int = None,
    movement_kind: str = None,
) -> StockMovement:
    """Modifie un mouvement existant : annule son effet sur le stock puis réapplique
    le nouvel effet, et recomptabilise l'écriture liée (le cas échéant)."""
    mov = db.query(StockMovement).filter(StockMovement.id == movement_id).first()
    if not mov:
        raise ValueError("Mouvement introuvable")
    item = db.query(StockItem).filter(StockItem.id == mov.item_id).first()
    if not item:
        raise ValueError("Article introuvable")

    # 1) Annule l'effet de l'ancien mouvement sur la quantité de l'article
    if getattr(mov, "qty_before", None) is not None:
        item.quantity = float(mov.qty_before)
    else:
        qty = float(mov.quantity or 0)
        current = float(item.quantity or 0)
        if _is_entry(mov.type):
            item.quantity = max(0.0, current - qty)
        else:
            item.quantity = current + qty

    # 2) Réapplique le nouvel effet (mêmes règles que apply_movement)
    new_type = movement_type or mov.type
    new_kind = movement_kind or mov.movement_kind or new_type
    new_qty = float(quantity) if quantity is not None else float(mov.quantity or 0)
    qty_before = float(item.quantity or 0)
    delta = new_qty
    if delta <= 0 and new_kind != "inventaire":
        raise ValueError("La quantité doit être strictement positive.")
    is_out = new_type == "sortie" or new_kind in ("sortie", "transfert")
    if is_out and new_kind != "inventaire" and qty_before - delta < 0:
        raise ValueError(
            f"Stock insuffisant pour {item.name or item.sku} : "
            f"disponible {qty_before}, demandé {delta}."
        )
    if new_kind in ("entrée", "ajustement") and new_type == "entrée":
        item.quantity = qty_before + delta
    elif new_kind == "ajustement" and new_type == "sortie":
        item.quantity = max(0, qty_before - delta)
    elif new_kind == "inventaire":
        item.quantity = delta
        delta = delta - qty_before
    elif new_kind == "transfert":
        item.quantity = max(0, qty_before - delta)
    elif new_type == "entrée":
        item.quantity = qty_before + delta
    else:
        item.quantity = max(0, qty_before - delta)
    qty_after = float(item.quantity or 0)
    stamp_item_updated(item)

    mov.type = new_type
    mov.movement_kind = new_kind
    mov.quantity = abs(delta) if new_kind != "inventaire" else new_qty
    if mv_date is not None:
        mov.date = mv_date
    if reason is not None:
        mov.reason = reason
    if notes is not None:
        mov.notes = notes
    if warehouse_id is not None:
        mov.warehouse_id = warehouse_id
    if warehouse_to_id is not None:
        mov.warehouse_to_id = warehouse_to_id
    mov.qty_before = qty_before
    mov.qty_after = qty_after
    if unit_cost is not None:
        mov.unit_cost = float(unit_cost)
    db.add(mov)
    db.flush()
    try:
        from app.services.accounting_hooks import dispatch_stock_movement
        dispatch_stock_movement(db, mov.id, force=True)
    except Exception:
        pass
    return mov


def delete_movement(db: Session, movement_id: int) -> StockItem:
    """Supprime un mouvement, restaure le stock à l'état antérieur et retire
    l'écriture comptable liée (pas d'écriture orpheline sans mouvement réel)."""
    mov = db.query(StockMovement).filter(StockMovement.id == movement_id).first()
    if not mov:
        raise ValueError("Mouvement introuvable")
    item = db.query(StockItem).filter(StockItem.id == mov.item_id).first()
    if not item:
        raise ValueError("Article introuvable")
    if getattr(mov, "qty_before", None) is not None:
        item.quantity = float(mov.qty_before)
    else:
        qty = float(mov.quantity or 0)
        current = float(item.quantity or 0)
        if _is_entry(mov.type):
            item.quantity = max(0.0, current - qty)
        else:
            item.quantity = current + qty
    stamp_item_updated(item)
    _delete_stock_movement_posting(db, movement_id)
    db.delete(mov)
    db.flush()
    return item


def _delete_stock_movement_posting(db: Session, movement_id: int) -> None:
    """Supprime l'écriture comptable (AccountingTransaction + JournalEntry + lignes)
    liée à un mouvement de stock, pour ne jamais laisser d'écriture orpheline dans
    le journal quand le mouvement qui l'a générée est supprimé."""
    from app.models_accounting import AccountingTransaction
    from app.models_erp import JournalEntry, JournalLine

    tx = db.query(AccountingTransaction).filter(
        AccountingTransaction.source_type == "stock_movement",
        AccountingTransaction.source_id == movement_id,
    ).first()
    if not tx:
        return
    if tx.journal_entry_id:
        db.query(JournalLine).filter(JournalLine.entry_id == tx.journal_entry_id).delete()
        entry = db.query(JournalEntry).filter(JournalEntry.id == tx.journal_entry_id).first()
        if entry:
            db.delete(entry)
    db.delete(tx)
    db.flush()


def delete_stock_item(
    db: Session,
    item_id: int,
    user_id: int | None = None,
    user_email: str = "",
) -> dict:
    """Supprime un article même s'il est lié à des devis/factures — les lignes
    documentaires sont conservées, seul le lien stock_item_id est retiré."""
    from app.models import DocumentLine, StockMovement
    from app.models_accounting import SupplierInvoiceLine
    from app.models_enterprise_suite import StockLot, StockSerial
    from app.models_erp import GoodsReceiptLine, PurchaseRequestLine, PurchaseOrderLine
    from app.services.audit_log import log_audit

    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise ValueError("Article introuvable")

    before = {
        "id": item.id,
        "sku": item.sku or "",
        "name": item.name or "",
        "quantity": float(item.quantity or 0),
    }
    detached: dict[str, int] = {}

    movements = db.query(StockMovement).filter(StockMovement.item_id == item_id).all()
    if movements:
        detached["stock_movements"] = len(movements)
    for mov in movements:
        _delete_stock_movement_posting(db, mov.id)
        db.delete(mov)

    n = (
        db.query(DocumentLine)
        .filter(DocumentLine.stock_item_id == item_id)
        .update({DocumentLine.stock_item_id: None}, synchronize_session=False)
    )
    if n:
        detached["document_lines"] = n

    n = (
        db.query(SupplierInvoiceLine)
        .filter(SupplierInvoiceLine.stock_item_id == item_id)
        .update({SupplierInvoiceLine.stock_item_id: None}, synchronize_session=False)
    )
    if n:
        detached["supplier_invoice_lines"] = n

    for model, label in (
        (StockLot, "stock_lots"),
        (StockSerial, "stock_serials"),
    ):
        n = db.query(model).filter(model.stock_item_id == item_id).delete(synchronize_session=False)
        if n:
            detached[label] = n

    for model, label in (
        (GoodsReceiptLine, "goods_receipt_lines"),
        (PurchaseRequestLine, "purchase_request_lines"),
        (PurchaseOrderLine, "purchase_order_lines"),
    ):
        n = (
            db.query(model)
            .filter(model.stock_item_id == item_id)
            .update({model.stock_item_id: None}, synchronize_session=False)
        )
        if n:
            detached[label] = n

    log_audit(
        db,
        action="delete",
        module="stock",
        entity_type="stock_item",
        entity_id=item_id,
        detail=(
            f"Suppression article « {item.name} » (#{item_id}) — "
            f"liens détachés : {detached or 'aucun'}."
        ),
        user_id=user_id,
        user_email=user_email,
        old_value=str(before),
    )
    db.delete(item)
    db.flush()
    return {"ok": True, "detached": detached}


def _is_entry(mtype: str) -> bool:
    t = (mtype or "").lower().strip()
    return t in ("entrée", "entree", "in", "achat") or t.startswith("entr")


def ensure_default_warehouses(db: Session):
    if db.query(Warehouse).count() > 0:
        return
    from app.region_config import REGION
    defaults = REGION["warehouses"]
    for code, name, typ, city in defaults:
        db.add(Warehouse(code=code, name=name, type=typ, city=city))
    db.commit()


def stock_analytics(db: Session) -> dict:
    items = db.query(StockItem).all()
    total_value = sum((i.quantity or 0) * (i.unit_cost or 0) for i in items)
    alerts = stock_alerts(db)
    rupture = sum(1 for a in alerts if a["level"] == "rupture")
    faible = sum(1 for a in alerts if a["level"] == "faible")
    by_qty = sorted(items, key=lambda x: x.quantity or 0, reverse=True)
    return {
        "total_value": round(total_value, 2),
        "total_items": len(items),
        "rupture_count": rupture,
        "low_stock_count": faible,
        "top_sellers": [{"name": i.name, "sku": i.sku, "quantity": i.quantity} for i in by_qty[:5]],
        "slow_movers": [{"name": i.name, "sku": i.sku, "quantity": i.quantity} for i in by_qty[-5:] if (i.quantity or 0) >= 0],
        "alerts": alerts[:20],
    }
