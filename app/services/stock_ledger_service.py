"""Grand livre stock — format fiche mouvements (SI / Entrée / Vente / Sortie / SF)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models import StockItem, StockMovement
from app.services.stock_service import list_overview


def _is_entry(mtype: str) -> bool:
    t = (mtype or "").lower().strip()
    return t in ("entrée", "entree", "in", "achat") or t.startswith("entr")


def _is_sale(reason: str, kind: str) -> bool:
    s = f"{reason} {kind}".lower()
    return any(w in s for w in ("vente", "facture", "client", "livraison"))


def _fmt_num(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return round(float(v), 3)


def _movement_row(it: StockItem, m: StockMovement, qb: float, qa: float, is_first: bool) -> dict:
    qty = float(m.quantity or 0)
    # PRU historique au moment du mouvement si connu (mouvements créés après le 2026-07-21) ;
    # à défaut, repli sur le PRU actuel de l'article (mouvements plus anciens, non snapshotés) —
    # évite de recalculer silencieusement les montants d'un grand livre passé avec un coût actuel
    # qui a pu changer depuis.
    snapshot = getattr(m, "unit_cost", None)
    pu = float(snapshot) if snapshot is not None else float(it.unit_cost or 0)
    is_in = _is_entry(m.type)
    kind = getattr(m, "movement_kind", "") or m.reason or ""
    is_sale = (not is_in) and _is_sale(m.reason or "", kind)
    date_str = str(m.date)[:10] if m.date else ""

    return {
        "date": date_str,
        "reference": it.sku or "",
        "designation": it.name or "",
        "item_id": it.id,
        "initial_q": _fmt_num(qb) if is_first else None,
        "initial_pu": _fmt_num(pu) if is_first else None,
        "initial_m": _fmt_num(qb * pu) if is_first else None,
        "entry_q": _fmt_num(qty) if is_in else None,
        "entry_pu": _fmt_num(pu) if is_in else None,
        "entry_m": _fmt_num(qty * pu) if is_in else None,
        "sale_date": date_str if is_sale else None,
        "sale_designation": (m.reason or it.name or "").strip() if is_sale else None,
        "exit_q": _fmt_num(qty) if not is_in else None,
        "exit_pu": _fmt_num(pu) if not is_in else None,
        "exit_m": _fmt_num(qty * pu) if not is_in else None,
        "stock_final": _fmt_num(qa),
        "movement_id": m.id,
        "movement_type": m.type or "",
        "movement_kind": kind,
        "reason": m.reason or "",
        "notes": m.notes or "",
        "quantity": _fmt_num(qty),
        "unit_cost": _fmt_num(pu),
        "warehouse_id": getattr(m, "warehouse_id", None),
    }


def _rows_for_item(it: StockItem, movements: list[StockMovement]) -> list[dict]:
    rows: list[dict] = []
    running: Optional[float] = None

    for i, m in enumerate(movements):
        qty = float(m.quantity or 0)
        qb_raw = getattr(m, "qty_before", None)
        qa_raw = getattr(m, "qty_after", None)

        if qb_raw is not None:
            qb = float(qb_raw)
        elif running is not None:
            qb = running
        else:
            qb = 0.0

        if qa_raw is not None:
            qa = float(qa_raw)
        else:
            is_in = _is_entry(m.type)
            qa = qb + qty if is_in else max(0.0, qb - qty)

        running = qa
        rows.append(_movement_row(it, m, qb, qa, is_first=(i == 0)))

    return rows


def lookup_stock_items(db: Session, query: str, limit: int = 20) -> list[dict]:
    q = (query or "").strip().lower()
    if not q or len(q) < 1:
        return []
    out: list[dict] = []
    for it in db.query(StockItem).order_by(StockItem.name).all():
        sku = (it.sku or "").lower()
        name = (it.name or "").lower()
        barcode = (getattr(it, "barcode", None) or "").lower()
        if not (
            q == sku or q == name or q == barcode
            or q in sku or q in name or q in barcode
            or sku.startswith(q) or name.startswith(q)
            or any(part and part in name for part in q.split())
        ):
            continue
        out.append({
            "id": it.id,
            "sku": it.sku or "",
            "barcode": getattr(it, "barcode", None) or "",
            "name": it.name or "",
            "category": it.category or "",
            "unit": it.unit or "unité",
            "unit_cost": float(it.unit_cost or 0),
            "unit_price": float(it.unit_price or 0),
            "quantity": float(it.quantity or 0),
            "label": f"{it.sku} — {it.name}".strip(" —"),
        })
        if len(out) >= limit:
            break
    return out


def build_stock_ledger(db: Session, item_id: Optional[int] = None, limit: int = 1000) -> dict:
    items_q = db.query(StockItem)
    if item_id:
        items_q = items_q.filter(StockItem.id == item_id)
    items = {i.id: i for i in items_q.order_by(StockItem.name).all()}

    mov_q = db.query(StockMovement)
    if item_id:
        mov_q = mov_q.filter(StockMovement.item_id == item_id)
    elif items:
        mov_q = mov_q.filter(StockMovement.item_id.in_(list(items.keys())))

    cap = min(max(limit, 1), 2000)
    all_movements = mov_q.order_by(StockMovement.date.asc(), StockMovement.id.asc()).all()

    by_item: dict[int, list[StockMovement]] = {iid: [] for iid in items}
    for m in all_movements:
        if m.item_id in by_item:
            by_item[m.item_id].append(m)

    rows: list[dict] = []

    for iid, it in items.items():
        movs = by_item.get(iid) or []
        if movs:
            rows.extend(_rows_for_item(it, movs))
        else:
            qty = float(it.quantity or 0)
            pu = float(it.unit_cost or 0)
            ts = (getattr(it, "created_at", None) or "")[:10]
            rows.append({
                "date": ts,
                "reference": it.sku or "",
                "designation": it.name or "",
                "item_id": it.id,
                "initial_q": _fmt_num(qty),
                "initial_pu": _fmt_num(pu),
                "initial_m": _fmt_num(qty * pu),
                "entry_q": None,
                "entry_pu": None,
                "entry_m": None,
                "sale_date": None,
                "sale_designation": None,
                "exit_q": None,
                "exit_pu": None,
                "exit_m": None,
                "stock_final": _fmt_num(qty),
                "movement_id": None,
                "movement_type": "solde",
                "movement_kind": "stock actuel",
                "reason": "",
                "notes": "",
            })

    rows.sort(key=lambda r: (r["date"] or "9999", r.get("movement_id") or 0, r.get("item_id") or 0))
    if len(rows) > cap:
        rows = rows[-cap:]

    overview = list_overview(db)
    if item_id:
        overview = [x for x in overview if x["id"] == item_id]

    total_qty = sum(float(x.get("qty_physical") or 0) for x in overview)
    total_val = sum(float(x.get("stock_value") or 0) for x in overview)

    return {
        "rows": rows,
        "summary": {
            "items_count": len(overview),
            "movements_count": len([r for r in rows if r.get("movement_id")]),
            "total_quantity": round(total_qty, 2),
            "total_value": round(total_val, 2),
        },
        "items": overview,
    }
