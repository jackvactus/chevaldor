"""Trésorerie avancée P1 — tableau de bord, prévisions cashflow, comptes unifiés."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Invoice
from app.models_erp import BankAccount, SupplierInvoice, TreasuryMovement

ACCOUNT_TYPES = ("bank", "cash", "mobile_money", "check")
TYPE_LABELS = {
    "bank": "Banque",
    "cash": "Caisse",
    "mobile_money": "Mobile Money",
    "check": "Chèques",
}


def infer_account_type(bank: BankAccount) -> str:
    t = getattr(bank, "account_type", None) or ""
    if t in ACCOUNT_TYPES:
        return t
    name = f"{bank.name or ''} {bank.bank_name or ''}".lower()
    if any(x in name for x in ("caisse", "cash", "espèce")):
        return "cash"
    if any(x in name for x in ("flooz", "mixx", "momo", "mobile", "tmoney", "fedapay")):
        return "mobile_money"
    if "chèque" in name or "cheque" in name:
        return "check"
    return "bank"


def treasury_dashboard(db: Session) -> dict:
    banks = db.query(BankAccount).filter(BankAccount.is_active == True).order_by(BankAccount.name).all()  # noqa: E712
    by_type: Dict[str, float] = {t: 0.0 for t in ACCOUNT_TYPES}
    accounts: List[dict] = []
    for b in banks:
        t = infer_account_type(b)
        bal = float(b.balance or 0)
        by_type[t] += bal
        accounts.append({
            "id": b.id,
            "name": b.name,
            "bank_name": b.bank_name,
            "account_type": t,
            "type_label": TYPE_LABELS.get(t, t),
            "balance": bal,
            "currency": b.currency or "XOF",
            "iban": b.iban or "",
        })

    moves = db.query(TreasuryMovement).order_by(TreasuryMovement.date.desc()).limit(100).all()
    month_start = date.today().replace(day=1)
    in_month = [m for m in moves if m.date and m.date >= month_start]
    inflows = sum(float(m.amount or 0) for m in in_month if "entree" in (m.type or ""))
    outflows = sum(float(m.amount or 0) for m in in_month if "sortie" in (m.type or ""))

    unreconciled = db.query(TreasuryMovement).filter(TreasuryMovement.reconciled == False).count()  # noqa: E712

    return {
        "total_balance": sum(by_type.values()),
        "by_type": [{"type": k, "label": TYPE_LABELS[k], "balance": v} for k, v in by_type.items()],
        "accounts": accounts,
        "month_inflows": inflows,
        "month_outflows": outflows,
        "month_net": inflows - outflows,
        "unreconciled_movements": unreconciled,
        "recent_movements": [
            {
                "id": m.id,
                "date": str(m.date) if m.date else "",
                "type": m.type,
                "label": m.label,
                "amount": m.amount or 0,
                "payment_method": getattr(m, "payment_method", None) or "",
                "reconciled": bool(m.reconciled),
                "bank_account_id": m.bank_account_id,
            }
            for m in moves[:30]
        ],
    }


def cashflow_forecast(db: Session, *, days: int = 90) -> dict:
    today = date.today()
    end = today + timedelta(days=days)
    buckets: Dict[str, Dict[str, float]] = {}

    def week_key(d: date) -> str:
        iso = d.isocalendar()
        return f"S{iso[1]:02d}-{iso[0]}"

    for i in range(0, days + 1, 7):
        k = week_key(today + timedelta(days=i))
        buckets[k] = {"inflows": 0.0, "outflows": 0.0, "label": k}

    invoices = db.query(Invoice).filter(
        Invoice.status.in_(["envoyée", "en retard", "validée"]),
    ).all()
    for inv in invoices:
        balance = max(0, float(inv.amount or 0) - float(inv.paid or 0))
        if balance <= 0:
            continue
        due = inv.due_date or inv.date or today
        if due < today:
            due = today
        if due > end:
            continue
        buckets.setdefault(week_key(due), {"inflows": 0.0, "outflows": 0.0, "label": week_key(due)})
        buckets[week_key(due)]["inflows"] += balance

    supplier_inv = db.query(SupplierInvoice).filter(
        SupplierInvoice.status.in_(["validée", "à payer", "envoyée"]),
    ).all()
    for si in supplier_inv:
        amt = float(si.amount or 0) - float(getattr(si, "paid", 0) or 0)
        if amt <= 0:
            continue
        due = getattr(si, "due_date", None) or getattr(si, "date", None) or today
        if hasattr(due, "year") and due < today:
            due = today
        if hasattr(due, "year") and due > end:
            continue
        if hasattr(due, "year"):
            k = week_key(due)
            buckets.setdefault(k, {"inflows": 0.0, "outflows": 0.0, "label": k})
            buckets[k]["outflows"] += amt

    labels = sorted(buckets.keys())[:14]
    return {
        "days": days,
        "labels": labels,
        "inflows": [round(buckets[k]["inflows"], 0) for k in labels],
        "outflows": [round(buckets[k]["outflows"], 0) for k in labels],
        "net": [round(buckets[k]["inflows"] - buckets[k]["outflows"], 0) for k in labels],
        "expected_collections": round(sum(b["inflows"] for b in buckets.values()), 0),
        "expected_payments": round(sum(b["outflows"] for b in buckets.values()), 0),
    }


def create_treasury_from_payment(
    db: Session,
    *,
    amount: float,
    label: str,
    reference: str = "",
    payment_method: str = "mobile_money",
    bank_account_id: int | None = None,
    movement_date: date | None = None,
) -> TreasuryMovement:
    type_map = {
        "caisse": "caisse_entree",
        "cash": "caisse_entree",
        "banque": "banque_entree",
        "bank": "banque_entree",
        "mobile_money": "mobile_money_entree",
        "flooz": "mobile_money_entree",
        "mixx": "mobile_money_entree",
        "fedapay": "mobile_money_entree",
        "cheque": "cheque_entree",
    }
    mtype = type_map.get(payment_method, "banque_entree")
    if not bank_account_id:
        acc = db.query(BankAccount).filter(BankAccount.is_active == True).first()  # noqa: E712
        bank_account_id = acc.id if acc else None
    mov = TreasuryMovement(
        date=movement_date or date.today(),
        type=mtype,
        bank_account_id=bank_account_id,
        label=label[:200],
        amount=amount,
        category="Encaissement",
        reference=reference[:80],
        reconciled=False,
    )
    if hasattr(TreasuryMovement, "payment_method"):
        mov.payment_method = payment_method
    db.add(mov)
    if bank_account_id:
        bank = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
        if bank:
            bank.balance = float(bank.balance or 0) + amount
    db.flush()
    return mov
