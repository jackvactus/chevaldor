"""API stock avancé — overview, entrepôts, mouvements, transferts, inventaire."""
from datetime import date as DateType
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_permission
from app.api_guards import require_action
from app.database import get_db
from app.models import User, StockItem, StockMovement
from app.models_stock import Warehouse, StockInventory
from app.services.stock_service import (
    list_overview,
    stock_alerts,
    stock_analytics,
    apply_movement,
    update_movement,
    delete_movement,
    ensure_default_warehouses,
    item_overview,
)
from app.services.stock_ledger_service import build_stock_ledger, lookup_stock_items
from app.services.stock_dedupe_service import find_duplicate_groups, merge_stock_items, merge_all_duplicates
from app import schemas

router = APIRouter(prefix="/api/stock", tags=["stock-advanced"])


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    type: str
    city: str
    is_active: bool


class WarehouseIn(BaseModel):
    code: str
    name: str
    type: str = "entrepôt"
    city: str = ""


class MovementIn(BaseModel):
    item_id: int
    type: str  # entrée, sortie
    quantity: float
    reason: str = ""
    project_id: Optional[int] = None
    notes: str = ""
    warehouse_id: Optional[int] = None
    warehouse_to_id: Optional[int] = None
    movement_kind: Optional[str] = None  # entrée, sortie, ajustement, inventaire, transfert
    date: Optional[DateType] = None
    unit_cost: Optional[float] = None  # montant unitaire (PU) — surtout utile pour figer le coût d'une sortie


class MovementUpdateIn(BaseModel):
    type: Optional[str] = None
    quantity: Optional[float] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_to_id: Optional[int] = None
    movement_kind: Optional[str] = None
    date: Optional[DateType] = None
    unit_cost: Optional[float] = None


class TransferIn(BaseModel):
    item_id: int
    quantity: float
    warehouse_from_id: int
    warehouse_to_id: int
    notes: str = ""


class StockExtendedIn(schemas.StockItemIn):
    qty_reserved: float = 0
    qty_on_order: float = 0
    max_quantity: float = 0
    safety_stock: float = 0
    reorder_point: float = 0
    warehouse_id: Optional[int] = None
    product_accounting_type: str = "MERCHANDISE"
    purchase_account: str = ""
    sale_account: str = ""
    stock_account: str = ""
    vat_account: str = ""


@router.get("/overview")
def get_overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ensure_default_warehouses(db)
    return {
        "items": list_overview(db),
        "analytics": stock_analytics(db),
        "warehouses": db.query(Warehouse).filter(Warehouse.is_active == True).all(),
    }


@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return stock_alerts(db)


@router.get("/analytics")
def get_analytics(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return stock_analytics(db)


@router.get("/warehouses", response_model=List[WarehouseOut])
def list_warehouses(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    ensure_default_warehouses(db)
    return db.query(Warehouse).order_by(Warehouse.name).all()


@router.post("/warehouses", response_model=WarehouseOut)
def create_warehouse(
    data: WarehouseIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("stock")),
):
    code = data.code.strip().upper()
    if db.query(Warehouse).filter(Warehouse.code == code).first():
        raise HTTPException(400, "Code entrepôt déjà utilisé")
    w = Warehouse(code=code, name=data.name, type=data.type, city=data.city)
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@router.post("/movements")
def create_stock_movement(
    data: MovementIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "update")),
):
    try:
        mov = apply_movement(
            db,
            item_id=data.item_id,
            movement_type=data.type,
            quantity=data.quantity,
            reason=data.reason,
            project_id=data.project_id,
            notes=data.notes,
            warehouse_id=data.warehouse_id,
            warehouse_to_id=data.warehouse_to_id,
            user_id=user.id,
            user_email=user.email,
            movement_kind=data.movement_kind or data.reason or data.type,
            mv_date=data.date,
            unit_cost=data.unit_cost,
        )
        db.commit()
        db.refresh(mov)
        return {"ok": True, "id": mov.id}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/movements/{movement_id}")
def edit_stock_movement(
    movement_id: int,
    data: MovementUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "update")),
):
    try:
        mov = update_movement(
            db,
            movement_id,
            movement_type=data.type,
            quantity=data.quantity,
            reason=data.reason,
            notes=data.notes,
            mv_date=data.date,
            unit_cost=data.unit_cost,
            warehouse_id=data.warehouse_id,
            warehouse_to_id=data.warehouse_to_id,
            movement_kind=data.movement_kind,
        )
        db.commit()
        db.refresh(mov)
        return {"ok": True, "id": mov.id}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/transfers")
def transfer_stock(
    data: TransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "update")),
):
    item = db.query(StockItem).filter(StockItem.id == data.item_id).first()
    if not item:
        raise HTTPException(404, "Article introuvable")
    w_from = db.query(Warehouse).filter(Warehouse.id == data.warehouse_from_id).first()
    w_to = db.query(Warehouse).filter(Warehouse.id == data.warehouse_to_id).first()
    if not w_from or not w_to:
        raise HTTPException(400, "Entrepôt source ou destination invalide")
    if data.warehouse_from_id == data.warehouse_to_id:
        raise HTTPException(400, "Les entrepôts source et destination doivent être distincts")
    try:
        # 1) Sortie magasin source
        apply_movement(
            db,
            item_id=data.item_id,
            movement_type="sortie",
            quantity=data.quantity,
            reason=f"Transfert → {w_to.name}",
            notes=data.notes,
            warehouse_id=data.warehouse_from_id,
            warehouse_to_id=data.warehouse_to_id,
            user_id=user.id,
            user_email=user.email,
            movement_kind="transfert",
        )
        # 2) Entrée magasin destination (crédite le stock — corrige la perte silencieuse)
        apply_movement(
            db,
            item_id=data.item_id,
            movement_type="entrée",
            quantity=data.quantity,
            reason=f"Transfert ← {w_from.name}",
            notes=data.notes,
            warehouse_id=data.warehouse_to_id,
            warehouse_to_id=None,
            user_id=user.id,
            user_email=user.email,
            movement_kind="entrée",
        )
        # Pointage magasin courant sur la destination
        if hasattr(item, "warehouse_id"):
            item.warehouse_id = data.warehouse_to_id
        db.commit()
        return {"ok": True, "message": f"Transfert {data.quantity} u. de {w_from.name} vers {w_to.name}"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))


@router.get("/lookup")
def stock_lookup(
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return lookup_stock_items(db, q, min(limit, 50))


class MergeIn(BaseModel):
    keep_id: int
    merge_ids: List[int]


@router.get("/duplicates")
def list_stock_duplicates(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("stock", "view")),
):
    return {"groups": find_duplicate_groups(db)}


@router.post("/duplicates/merge")
def merge_stock_duplicates(
    data: MergeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "delete")),
):
    try:
        return merge_stock_items(
            db, data.keep_id, data.merge_ids, user_id=user.id, user_email=user.email,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))


@router.post("/duplicates/merge-all")
def merge_all_stock_duplicates(
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "delete")),
):
    try:
        results = merge_all_duplicates(db, user_id=user.id, user_email=user.email)
        return {"ok": True, "merged_groups": len(results), "results": results}
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))


@router.get("/ledger")
def stock_ledger(
    item_id: Optional[int] = None,
    limit: int = 1000,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return build_stock_ledger(db, item_id=item_id, limit=min(limit, 2000))


@router.delete("/movements/{movement_id}")
def remove_stock_movement(
    movement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("stock", "delete")),
):
    try:
        item = delete_movement(db, movement_id)
        db.commit()
        return {"ok": True, "item_id": item.id, "quantity": item.quantity}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/movements/history")
def movement_history(
    item_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(StockMovement)
    if item_id:
        q = q.filter(StockMovement.item_id == item_id)
    rows = q.order_by(StockMovement.id.desc()).limit(min(limit, 500)).all()
    items = {i.id: i for i in db.query(StockItem).all()}
    wh = {w.id: w.name for w in db.query(Warehouse).all()}
    out = []
    for m in rows:
        it = items.get(m.item_id)
        logged = (getattr(m, "logged_at", "") or "").strip()
        date_str = str(m.date) if m.date else ""
        if not logged and date_str:
            logged = date_str + "T00:00:00"
        out.append({
            "id": m.id,
            "item_id": m.item_id,
            "sku": it.sku if it else "",
            "product": it.name if it else "",
            "date": date_str,
            "logged_at": logged,
            "type": m.type,
            "movement_kind": getattr(m, "movement_kind", "") or m.reason,
            "quantity": m.quantity,
            "qty_before": getattr(m, "qty_before", None),
            "qty_after": getattr(m, "qty_after", None),
            "user_email": getattr(m, "user_email", "") or "",
            "warehouse": wh.get(getattr(m, "warehouse_id", None), ""),
            "warehouse_to": wh.get(getattr(m, "warehouse_to_id", None), ""),
            "reason": m.reason,
            "notes": m.notes or "",
        })
    return out


@router.put("/items/{item_id}/extended")
def update_stock_extended(
    item_id: int,
    data: StockExtendedIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("stock", "update")),
):
    from app.services.stock_service import stamp_item_created, stamp_item_updated
    obj = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not obj:
        raise HTTPException(404)
    base = data.model_dump()
    for k, v in base.items():
        if hasattr(obj, k):
            setattr(obj, k, v)
    if not (getattr(obj, "created_at", None) or "").strip():
        stamp_item_created(obj)
    else:
        stamp_item_updated(obj)
    db.commit()
    wh = {w.id: w.name for w in db.query(Warehouse).all()}
    return item_overview(obj, wh.get(getattr(obj, "warehouse_id", None), ""))
