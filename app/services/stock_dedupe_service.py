"""Détection et fusion des articles de stock en double (`StockItem`).

Root cause des doublons observés : plusieurs SKU créés pour le même produit au fil
d'imports/saisies successifs (ex. « Farine de blé de 50 kg » saisi 4 fois avec des SKU
différents). La fusion réattribue toutes les références liées (mouvements, lignes de
devis/facture/achat, lots, numéros de série...) vers un seul article conservé, cumule
les quantités et recalcule un coût moyen pondéré — puis supprime les doublons.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models import StockItem, StockMovement, DocumentLine
from app.models_accounting import SupplierInvoiceLine
from app.models_enterprise_suite import StockLot, StockSerial
from app.models_erp import GoodsReceiptLine, PurchaseRequestLine, PurchaseOrderLine
from app.services.audit_log import log_audit

# Mêmes 8 tables que la pré-vérification de `DELETE /api/stock/{id}` (main.py::delete_stock) —
# c'est l'inventaire exhaustif des colonnes FK vers stock_items.id dans le schéma.
DEPENDENT_TABLES = (
    (StockMovement, "item_id"),
    (DocumentLine, "stock_item_id"),
    (SupplierInvoiceLine, "stock_item_id"),
    (StockLot, "stock_item_id"),
    (StockSerial, "stock_item_id"),
    (GoodsReceiptLine, "stock_item_id"),
    (PurchaseRequestLine, "stock_item_id"),
    (PurchaseOrderLine, "stock_item_id"),
)


def _is_entry_movement(mtype: str) -> bool:
    """Même sémantique que `stock_ledger_service._is_entry` — le sens réel du mouvement
    (`type`) fait foi, jamais `movement_kind` (voir correctif M4 du 2026-07-28)."""
    t = (mtype or "").lower().strip()
    return t in ("entrée", "entree", "in", "achat") or t.startswith("entr")


_UNIT_SUFFIX = re.compile(
    r"\s+(?:g|kg|l|ml|cl|pcs?|unités?|unites?)\s*$",
    re.IGNORECASE,
)


def normalize_item_name(name: str) -> str:
    """Casse/accents/espaces ignorés, + espace forcé aux frontières lettre/chiffre —
    sans quoi « Huile aicha25l » et « Huile aicha 25l » (même produit, juste un espace
    de saisie manquant/en trop autour du conditionnement) ne se regroupaient pas.
    Les suffixes d'unité en fin de libellé (« 210g » vs « 210 ») sont aussi ignorés."""
    s = (name or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"(?<=[a-z])(?=[0-9])", " ", s)
    s = re.sub(r"(?<=[0-9])(?=[a-z])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _UNIT_SUFFIX.sub("", s).strip()
    return s


def _names_similar(a: str, b: str) -> bool:
    """Rapproche les fautes de frappe d'une lettre en fin (« koutoubili » / « koutoubilim »)."""
    if not a or not b or a == b:
        return a == b
    if abs(len(a) - len(b)) > 2:
        return False
    return a.startswith(b) or b.startswith(a)


def _cluster_by_similar_names(items: list[StockItem]) -> dict[str, list[StockItem]]:
    """Union-find sur les clés normalisées quasi identiques."""
    keyed: dict[str, list[StockItem]] = defaultdict(list)
    for it in items:
        key = normalize_item_name(it.name)
        if key:
            keyed[key].append(it)

    keys = sorted(keyed)
    parent = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if _names_similar(a, b):
                union(a, b)

    merged: dict[str, list[StockItem]] = defaultdict(list)
    for key, its in keyed.items():
        merged[find(key)].extend(its)
    return dict(merged)


def _dependency_count(db: Session, item_id: int) -> int:
    return sum(
        db.query(model).filter(getattr(model, fk) == item_id).count()
        for model, fk in DEPENDENT_TABLES
    )


def _item_summary(db: Session, it: StockItem) -> dict:
    return {
        "id": it.id,
        "sku": it.sku or "",
        "name": it.name,
        "unit": it.unit or "",
        "category": it.category or "",
        "quantity": float(it.quantity or 0),
        "unit_cost": float(it.unit_cost or 0),
        "warehouse_id": it.warehouse_id,
        "links": _dependency_count(db, it.id),
    }


def _pick_canonical(db: Session, items: list[StockItem]) -> StockItem:
    """L'article le plus référencé (mouvements/lignes liées) est conservé — c'est celui
    dont la disparition aurait le plus d'impact ; à égalité, le plus ancien (id le plus
    petit, probablement la fiche d'origine avant les doublons)."""
    def score(it: StockItem):
        return (_dependency_count(db, it.id), -it.id)
    return max(items, key=score)


def find_duplicate_groups(db: Session) -> list[dict]:
    """Regroupe les articles dont le nom est identique une fois normalisé (casse/accents/
    espaces ignorés — ex. « Spaghetti Santa » / « spaghetti santa »)."""
    items = db.query(StockItem).all()
    groups = _cluster_by_similar_names(items)

    result = []
    for key, its in groups.items():
        if len(its) < 2:
            continue
        its = sorted(its, key=lambda x: x.id)
        keep = _pick_canonical(db, its)
        result.append({
            "key": key,
            "suggested_keep_id": keep.id,
            "items": [_item_summary(db, i) for i in its],
        })
    result.sort(key=lambda g: g["key"])
    return result


def merge_stock_items(
    db: Session,
    keep_id: int,
    merge_ids: list[int],
    user_id: Optional[int] = None,
    user_email: str = "",
) -> dict:
    merge_ids = [i for i in dict.fromkeys(merge_ids) if i != keep_id]
    if not merge_ids:
        raise ValueError("Aucun article à fusionner (liste vide ou identique à l'article cible).")

    keep = db.query(StockItem).filter(StockItem.id == keep_id).first()
    if not keep:
        raise ValueError("Article cible introuvable.")
    dups = db.query(StockItem).filter(StockItem.id.in_(merge_ids)).all()
    if len(dups) != len(merge_ids):
        raise ValueError("Un ou plusieurs articles à fusionner sont introuvables.")

    before = {"keep": _item_summary(db, keep), "merged": [_item_summary(db, d) for d in dups]}

    # Coût moyen pondéré (CMP) sur la quantité totale — méthode de valorisation SYSCOHADA
    # standard, seule façon défendable de fusionner deux coûts unitaires différents.
    total_qty = float(keep.quantity or 0)
    total_value = total_qty * float(keep.unit_cost or 0)
    for d in dups:
        q = float(d.quantity or 0)
        total_qty += q
        total_value += q * float(d.unit_cost or 0)

    if not keep.warehouse_id:
        for d in dups:
            if d.warehouse_id:
                keep.warehouse_id = d.warehouse_id
                break
    if not (keep.sku or "").strip():
        for d in dups:
            if (d.sku or "").strip():
                keep.sku = d.sku
                break

    # Réattribution de toutes les références liées vers l'article conservé.
    moved: dict[str, int] = {}
    for model, fk in DEPENDENT_TABLES:
        n = (
            db.query(model)
            .filter(getattr(model, fk).in_(merge_ids))
            .update({fk: keep_id}, synchronize_session=False)
        )
        if n:
            moved[model.__tablename__] = n

    # Le grand livre stock (stock_ledger_service) affiche qty_before/qty_after tels que
    # stockés sur chaque mouvement. Une fois des mouvements de plusieurs articles
    # regroupés sur un seul, leur solde couru d'origine (calculé contre l'historique de
    # leur article de départ) n'a plus de sens — on le reconstruit dans l'ordre
    # chronologique, ancré pour retomber exactement sur le total réel cumulé (couvre
    # aussi les quantités sans aucun mouvement, ex. import direct : elles sont absorbées
    # dans le solde de départ du tout premier mouvement, exactement comme le fait déjà
    # le grand livre pour un article sans mouvement du tout).
    kept_movements = (
        db.query(StockMovement)
        .filter(StockMovement.item_id == keep_id)
        .order_by(StockMovement.date.asc(), StockMovement.id.asc())
        .all()
    )
    net_delta = 0.0
    for m in kept_movements:
        q = float(m.quantity or 0)
        net_delta += q if _is_entry_movement(m.type) else -q
    running = total_qty - net_delta
    for m in kept_movements:
        m.qty_before = running
        q = float(m.quantity or 0)
        running += q if _is_entry_movement(m.type) else -q
        m.qty_after = running

    keep.quantity = round(running, 6)
    if total_qty > 0:
        keep.unit_cost = round(total_value / total_qty, 4)

    removed_ids = [d.id for d in dups]
    removed_names = ", ".join(f"#{d.id} ({d.sku})" for d in dups)
    for d in dups:
        db.delete(d)

    log_audit(
        db,
        action="merge",
        module="stock",
        entity_type="stock_item",
        entity_id=keep_id,
        detail=(
            f"Fusion de {len(dups)} doublon(s) de « {keep.name} » dans l'article #{keep_id} "
            f"({keep.sku}) : {removed_names} supprimé(s), "
            f"{sum(moved.values())} référence(s) réattribuée(s)."
        ),
        user_id=user_id,
        user_email=user_email,
        old_value=str(before),
        new_value=str(_item_summary(db, keep)),
    )

    db.commit()
    db.refresh(keep)
    return {"keep": _item_summary(db, keep), "moved": moved, "removed_ids": removed_ids}


def merge_all_duplicates(
    db: Session,
    user_id: Optional[int] = None,
    user_email: str = "",
) -> list[dict]:
    """Fusionne automatiquement tous les groupes de doublons détectés, chacun vers son
    article suggéré (`suggested_keep_id`)."""
    groups = find_duplicate_groups(db)
    results = []
    for g in groups:
        keep_id = g["suggested_keep_id"]
        merge_ids = [i["id"] for i in g["items"] if i["id"] != keep_id]
        res = merge_stock_items(db, keep_id, merge_ids, user_id=user_id, user_email=user_email)
        res["key"] = g["key"]
        results.append(res)
    return results
