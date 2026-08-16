"""Moteur de calcul centralisé documents commerciaux (HT / TVA / remise / TTC).

Source de vérité unique pour factures, devis, dashboards, exports et PDF.
Aligné sur LineKit (frontend/utils/lines.js) — arrondi entier FCFA.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from sqlalchemy.orm import Session

from app.fiscal_service import resolve_vat_rate


def _round_fcfa(v: float | int | None) -> float:
    return float(round(float(v or 0)))


def _clamp_pct(v: float | int | None) -> float:
    return min(100.0, max(0.0, float(v or 0)))


def line_ht(
    quantity: float | int | None,
    unit_price: float | int | None,
    discount_pct: float | int | None = 0,
    discount_amount: float | int | None = 0,
) -> float:
    q = float(quantity or 0)
    pu = _round_fcfa(unit_price)
    brut = _round_fcfa(q * pu)
    amt = max(0.0, _round_fcfa(discount_amount))
    if amt > 0:
        disc = min(amt, brut)
    else:
        disc = _round_fcfa(brut * _clamp_pct(discount_pct) / 100)
    return max(0.0, brut - disc)


def line_tva(ht: float, vat_rate: float | int | None) -> float:
    return _round_fcfa(ht * _clamp_pct(vat_rate) / 100)


def line_ttc(
    quantity: float | int | None,
    unit_price: float | int | None,
    vat_rate: float | int | None = 0,
    discount_pct: float | int | None = 0,
    discount_amount: float | int | None = 0,
) -> float:
    ht = line_ht(quantity, unit_price, discount_pct, discount_amount)
    return ht + line_tva(ht, vat_rate)


def commission_amount(subtotal_ht: float, commission_pct: float | int | None = 0) -> float:
    return _round_fcfa(max(0.0, float(subtotal_ht or 0)) * _clamp_pct(commission_pct) / 100)


def totals_from_lines(
    lines: Iterable[Mapping[str, Any] | Any],
    *,
    global_discount_pct: float | int | None = 0,
    global_discount_amount: float | int | None = 0,
    commission_pct: float | int | None = 0,
    default_vat_rate: float | int | None = 0,
) -> dict:
    """Calcule les totaux document à partir des lignes.

    Retourne : subtotal_ht, total_tva, ttc, global_disc, commission,
    amount (HT + commission, sémantique historique Invoice.amount),
    amount_ht, amount_ttc, paid_remaining helpers.
    """
    rows = []
    for ln in lines or []:
        if isinstance(ln, Mapping):
            rows.append(ln)
        else:
            rows.append({
                "quantity": getattr(ln, "quantity", 0),
                "unit_price": getattr(ln, "unit_price", None) if getattr(ln, "unit_price", None) is not None else getattr(ln, "unit_cost", 0),
                "discount_pct": getattr(ln, "discount_pct", 0),
                "discount_amount": getattr(ln, "discount_amount", 0),
                "vat_rate": getattr(ln, "vat_rate", None),
                "description": getattr(ln, "description", "") or "",
            })

    usable = [
        r for r in rows
        if (r.get("description") or r.get("unit_price") or r.get("quantity"))
    ]

    breakdown: dict[str, dict] = {}
    base_subtotal_ht = 0.0
    line_discount_total = 0.0

    for r in usable:
        up = r.get("unit_price", 0)
        disc_pct = r.get("discount_pct", 0) or 0
        disc_amt = r.get("discount_amount", 0) or 0
        qty = r.get("quantity", 0) or 0
        brut = _round_fcfa(float(qty) * _round_fcfa(up))
        amt = max(0.0, _round_fcfa(disc_amt))
        line_disc = min(amt, brut) if amt > 0 else _round_fcfa(brut * _clamp_pct(disc_pct) / 100)
        ht = line_ht(qty, up, disc_pct, disc_amt)
        vat_rate = r.get("vat_rate")
        if vat_rate is None or vat_rate == "":
            vat_rate = default_vat_rate or 0
        rate_key = f"{float(vat_rate or 0):.2f}"
        vat = line_tva(ht, vat_rate)
        base_subtotal_ht += ht
        line_discount_total += line_disc
        if rate_key not in breakdown:
            breakdown[rate_key] = {"subtotal_ht": 0.0, "total_tva": 0.0, "ttc": 0.0, "rate": float(vat_rate or 0)}
        breakdown[rate_key]["subtotal_ht"] += ht
        breakdown[rate_key]["total_tva"] += vat

    global_pct = _clamp_pct(global_discount_pct)
    global_amt = max(0.0, _round_fcfa(global_discount_amount))
    global_disc = min(global_amt, base_subtotal_ht) if global_amt > 0 else _round_fcfa(base_subtotal_ht * global_pct / 100)
    subtotal_ht = max(0.0, base_subtotal_ht - global_disc)
    proportional = (subtotal_ht / base_subtotal_ht) if base_subtotal_ht else 0.0

    total_tva = 0.0
    for rate_key, b in breakdown.items():
        b["subtotal_ht"] = _round_fcfa(b["subtotal_ht"] * proportional)
        b["total_tva"] = line_tva(b["subtotal_ht"], b["rate"])
        b["ttc"] = b["subtotal_ht"] + b["total_tva"]
        total_tva += b["total_tva"]

    commission = commission_amount(subtotal_ht, commission_pct)
    amount_ht = _round_fcfa(subtotal_ht + commission)
    ttc = _round_fcfa(subtotal_ht + total_tva + commission)

    return {
        "subtotal_ht": _round_fcfa(subtotal_ht),
        "total_tva": _round_fcfa(total_tva),
        "ttc": ttc,
        "global_disc": _round_fcfa(global_disc),
        "line_discount_total": _round_fcfa(line_discount_total),
        "commission": commission,
        "amount": amount_ht,  # compat Invoice.amount (HT + commission)
        "amount_ht": amount_ht,
        "amount_ttc": ttc,
        "count": len(usable),
        "vat_breakdown": breakdown,
    }


def payment_status(amount_ttc: float, paid: float | int | None) -> dict:
    amt = max(0.0, float(amount_ttc or 0))
    pay = max(0.0, float(paid or 0))
    remaining = max(0.0, _round_fcfa(amt - pay))
    if amt <= 0:
        status = "brouillon"
    elif remaining <= 0.01:
        status = "payée"
    elif pay > 0:
        status = "partielle"
    else:
        status = "impayée"
    return {
        "amount_ttc": _round_fcfa(amt),
        "paid": _round_fcfa(pay),
        "remaining": remaining,
        "payment_status": status,
    }


def compute_document_totals(
    db: Session,
    lines: Iterable[Any],
    *,
    doc_vat_rate: float | int | None = None,
    discount_pct: float | int | None = 0,
    discount_amount: float | int | None = 0,
    commission_pct: float | int | None = 0,
    paid: float | int | None = 0,
) -> dict:
    """Point d'entrée unique : validation → normalisation → calcul → indicateurs."""
    default_vat = resolve_vat_rate(db, line_rate=None, doc_rate=doc_vat_rate)
    totals = totals_from_lines(
        lines,
        global_discount_pct=discount_pct,
        global_discount_amount=discount_amount,
        commission_pct=commission_pct,
        default_vat_rate=default_vat,
    )
    pay = payment_status(totals["amount_ttc"], paid)
    totals.update(pay)
    return totals


def apply_document_amounts(doc: Any, totals: Mapping[str, Any]) -> None:
    """Persiste le montant HT (+ commission) sur le document — sémantique historique."""
    if doc is None:
        return
    doc.amount = float(totals.get("amount") or 0)
