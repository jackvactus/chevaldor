"""Écritures automatiques SYSCOHADA — double entrée, TVA, stocks (inventaire permanent)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models import Invoice, DocumentLine, Account
from app.models_erp import JournalEntry, JournalLine, SupplierInvoice
from app.models_prefs import SystemSettings
from app.syscohada.constants import DEFAULT_ACCOUNTS
from app.services.accounting_reports import validate_entry_balance
from app.fiscal_service import assert_fiscal_year_open

# Aligné avec accounting_engine — pas de ventilation TVA en journal (443/445).
JOURNAL_SPLIT_VAT = False


def _settings(db: Session) -> dict[str, Any]:
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    defaults = dict(DEFAULT_ACCOUNTS)
    if not row:
        return {"accounts": defaults, "plan": "SYSCOHADA"}
    try:
        acc = json.loads(row.default_accounts_json or "{}")
        defaults.update(acc)
    except Exception:
        pass
    return {
        "accounts": defaults,
        "plan": getattr(row, "accounting_plan", None) or "SYSCOHADA",
        "fiscal_year": getattr(row, "accounting_year", None) or date.today().year,
    }


def split_vat(amount_ttc: float, vat_rate: float) -> tuple[float, float, float]:
    """Retourne (HT, TVA, TTC) à partir d'un montant TTC."""
    rate = float(vat_rate or 0)
    if rate <= 0:
        ht = float(amount_ttc or 0)
        return round(ht, 2), 0.0, round(ht, 2)
    ttc = float(amount_ttc or 0)
    ht = ttc / (1 + rate / 100)
    tva = ttc - ht
    return round(ht, 2), round(tva, 2), round(ttc, 2)


def invoice_amounts(invoice: Invoice, lines: list[DocumentLine], db: Session | None = None) -> dict[str, float]:
    """Calcule HT / TVA / TTC depuis les lignes ou le montant global (HT)."""
    from app.fiscal_service import resolve_vat_rate, amounts_from_ht

    if lines:
        ht = tva = 0.0
        for ln in lines:
            line_ht = (ln.quantity or 0) * (ln.unit_price or 0)
            rate = resolve_vat_rate(db, line_rate=ln.vat_rate, doc_rate=invoice.vat_rate) if db else float(ln.vat_rate if ln.vat_rate is not None else (invoice.vat_rate or 0))
            _, line_tva, _ = amounts_from_ht(line_ht, rate)
            ht += line_ht
            tva += line_tva
        ttc = ht + tva
        return {"ht": round(ht, 2), "tva": round(tva, 2), "ttc": round(ttc, 2)}
    rate = resolve_vat_rate(db, doc_rate=invoice.vat_rate) if db else float(invoice.vat_rate or 0)
    ht, tva, ttc = amounts_from_ht(float(invoice.amount or 0), rate)
    return {"ht": ht, "tva": tva, "ttc": ttc}


def _line(account_code: str, debit: float, credit: float, label: str = "") -> dict:
    return {
        "account_code": account_code,
        "debit": round(debit, 2),
        "credit": round(credit, 2),
        "label": label,
    }


def build_sale_entry(
    invoice: Invoice,
    lines: list[DocumentLine],
    accounts: dict[str, str] | None = None,
    *,
    is_service: bool = True,
    with_stock: bool = False,
    db: Session | None = None,
) -> dict:
    """
    Facture client (journal VE) :
      Débit 411 Clients (TTC)
      Crédit 70x Produit (TTC si pas de ventilation TVA)
    """
    acc = {**DEFAULT_ACCOUNTS, **(accounts or {})}
    amounts = invoice_amounts(invoice, lines, db)
    is_credit = getattr(invoice, "doc_type", "invoice") == "credit_note"
    sign = -1 if is_credit else 1
    ht, tva, ttc = amounts["ht"] * sign, amounts["tva"] * sign, amounts["ttc"] * sign

    product_acc = acc["sales_services"] if is_service else acc["sales_goods"]
    vat_acc = acc["vat_collected_services"] if is_service else acc["vat_collected_sales"]
    client_acc = acc["clients"]
    post_amt = (abs(ttc) if not JOURNAL_SPLIT_VAT else abs(ht)) * sign

    journal_lines = [
        _line(client_acc, max(ttc, 0), max(-ttc, 0), invoice.number or ""),
        _line(product_acc, max(-post_amt, 0), max(post_amt, 0), "Vente"),
    ]
    if abs(tva) >= 0.01 and JOURNAL_SPLIT_VAT:
        journal_lines.append(_line(vat_acc, max(-tva, 0), max(tva, 0), "TVA collectée"))

    # Sortie stock (coût = HT simplifié — à affiner avec CMUP en stock_service)
    if with_stock and not is_credit and not is_service:
        journal_lines.extend([
            _line(acc["stock_variation_goods"], ht, 0, "Variation stock — sortie vente"),
            _line(acc["stock_goods"], 0, ht, "Stock marchandises"),
        ])

    return {
        "journal": "VE",
        "reference": invoice.number or f"F{invoice.id}",
        "label": f"Facture client {invoice.number or invoice.id}",
        "lines": journal_lines,
    }


def build_purchase_entry(
    supplier_invoice: SupplierInvoice,
    accounts: dict[str, str] | None = None,
    *,
    vat_rate: float | None = None,
    is_service: bool = False,
    with_stock: bool = True,
    db: Session | None = None,
) -> dict:
    """
    Facture fournisseur (journal AC) :
      Débit 601/604 ou stock (TTC si pas de ventilation TVA)
      Crédit 401 Fournisseur (TTC)
    """
    from app.fiscal_service import resolve_vat_rate, amounts_from_ht

    acc = {**DEFAULT_ACCOUNTS, **(accounts or {})}
    rate = resolve_vat_rate(db, doc_rate=vat_rate) if db else float(vat_rate or 0)
    ht, tva, ttc = amounts_from_ht(float(supplier_invoice.amount or 0), rate)
    post_amt = ttc if not JOURNAL_SPLIT_VAT else ht

    if with_stock and not is_service:
        charge_acc = acc["stock_goods"]
        charge_label = "Entrée stock — achat"
    else:
        charge_acc = acc["purchases_services"] if is_service else acc["purchases_goods"]
        charge_label = "Achat"
    vat_acc = acc["vat_deductible_services"] if is_service else acc["vat_deductible_purchases"]

    journal_lines = [
        _line(charge_acc, post_amt, 0, charge_label),
        _line(acc["suppliers"], 0, ttc, supplier_invoice.number or ""),
    ]
    if JOURNAL_SPLIT_VAT and tva >= 0.01:
        journal_lines.insert(1, _line(vat_acc, tva, 0, "TVA récupérable"))

    return {
        "journal": "AC",
        "reference": supplier_invoice.number or f"SF{supplier_invoice.id}",
        "label": f"Facture fournisseur {supplier_invoice.number or supplier_invoice.id}",
        "lines": journal_lines,
    }


def build_payment_entry(
    amount: float,
    *,
    direction: str,
    payment_method: str = "banque",
    reference: str = "",
    label: str = "",
    accounts: dict[str, str] | None = None,
    counterparty_account: str | None = None,
) -> dict:
    """Encaissement client ou décaissement fournisseur."""
    acc = {**DEFAULT_ACCOUNTS, **(accounts or {})}
    amt = abs(float(amount or 0))
    treasury = acc["cash"] if payment_method in ("caisse", "cash", "flooz", "mixx", "fedapay") else acc["bank"]
    journal = "CA" if payment_method in ("caisse", "cash", "flooz", "mixx", "fedapay") else "BQ"
    cp = counterparty_account or (acc["clients"] if direction == "in" else acc["suppliers"])

    if direction == "in":
        lines = [_line(treasury, amt, 0, label), _line(cp, 0, amt, label)]
    else:
        lines = [_line(cp, amt, 0, label), _line(treasury, 0, amt, label)]

    return {
        "journal": journal,
        "reference": reference,
        "label": label or reference,
        "lines": lines,
    }


def build_vat_regularization(accounts: dict[str, str] | None = None) -> dict:
    """Clôture TVA : solde 443 + 445 vers 444 (journal OD)."""
    acc = {**DEFAULT_ACCOUNTS, **(accounts or {})}
    return {
        "journal": "OD",
        "reference": "TVA-CLOTURE",
        "label": "Régularisation TVA périodique",
        "lines": [
            _line(acc["vat_collected_sales"], 0, 0, "À compléter selon soldes 443"),
            _line(acc["vat_deductible_purchases"], 0, 0, "À compléter selon soldes 445"),
            _line(acc["vat_due"], 0, 0, "TVA due ou crédit 444"),
        ],
        "note": "Saisir les montants nets des soldes 443 et 445 avant validation.",
    }


def persist_entry(
    db: Session,
    payload: dict,
    *,
    entry_date: date | None = None,
    fiscal_year: int | None = None,
    period: int | None = None,
    status: str = "validée",
) -> JournalEntry:
    """Enregistre une écriture équilibrée en base."""
    lines = payload.get("lines") or []
    if not validate_entry_balance(lines):
        raise ValueError("Écriture non équilibrée (débit ≠ crédit)")
    fy = fiscal_year or date.today().year
    assert_fiscal_year_open(db, fy)
    entry = JournalEntry(
        date=entry_date or date.today(),
        journal=payload.get("journal", "OD"),
        reference=payload.get("reference", ""),
        label=payload.get("label", ""),
        status=status,
        fiscal_year=fy,
        period=period or (entry_date or date.today()).month,
    )
    db.add(entry)
    db.flush()
    for ln in lines:
        db.add(JournalLine(
            entry_id=entry.id,
            account_code=ln["account_code"],
            debit=ln.get("debit", 0) or 0,
            credit=ln.get("credit", 0) or 0,
            label=ln.get("label", ""),
        ))
    db.commit()
    db.refresh(entry)
    return entry


def post_invoice(db: Session, invoice_id: int, *, with_stock: bool = False) -> JournalEntry:
    from app.services.accounting_engine import on_invoice_validated
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise ValueError("Facture introuvable")
    tx = on_invoice_validated(db, invoice, force=True)
    if not tx or not tx.journal_entry_id:
        raise ValueError("Écriture non générée")
    entry = db.query(JournalEntry).filter(JournalEntry.id == tx.journal_entry_id).first()
    return entry


def post_supplier_invoice(
    db: Session,
    supplier_invoice_id: int,
    *,
    vat_rate: float = 18.0,
    with_stock: bool = True,
) -> JournalEntry:
    from app.services.accounting_engine import on_supplier_invoice_validated
    inv = db.query(SupplierInvoice).filter(SupplierInvoice.id == supplier_invoice_id).first()
    if not inv:
        raise ValueError("Facture fournisseur introuvable")
    tx = on_supplier_invoice_validated(db, inv, force=True)
    if not tx or not tx.journal_entry_id:
        raise ValueError("Écriture non générée")
    return db.query(JournalEntry).filter(JournalEntry.id == tx.journal_entry_id).first()
