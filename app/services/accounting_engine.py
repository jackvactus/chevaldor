"""
Moteur de comptabilisation SYSCOHADA automatique.

Flux : Opération métier → Validation → Accounting Engine → Journal Entries
Aucune saisie manuelle obligatoire pour les opérations standard.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Invoice, DocumentLine, StockItem
from app.models_erp import JournalEntry, JournalLine, SupplierInvoice
from app.models_accounting import AccountingTransaction, SupplierInvoiceLine, TaxRate
from app.models_prefs import SystemSettings
from app.syscohada.constants import DEFAULT_ACCOUNTS
from app.syscohada.product_types import (
    accounts_for_type,
    resolve_line_accounts,
    CREDIT_NOTE_TYPES,
    ACCESSORY_FEE_TYPES,
)
from app.syscohada.posting import _line, _settings
from app.services.accounting_reports import validate_entry_balance
from app.fiscal_service import assert_fiscal_year_open, resolve_vat_rate, amounts_from_ht


POSTING_STATUSES_INVOICE = frozenset({"envoyée", "payée", "en retard"})
POSTING_STATUSES_PURCHASE = frozenset({"validée", "payée", "en retard"})
# Pas de comptes 443/445 en journal — montant TTC sur produits/charges ; TVA gérée en facturation.
JOURNAL_SPLIT_VAT = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def get_inventory_method(db: Session) -> str:
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    return getattr(row, "inventory_method", None) or "PERMANENT"


def _merge_lines(lines: list[dict]) -> list[dict]:
    """Regroupe les lignes par compte (débit/crédit cumulés)."""
    buckets: dict[str, dict] = {}
    for ln in lines:
        code = ln["account_code"]
        if code not in buckets:
            buckets[code] = {"account_code": code, "debit": 0.0, "credit": 0.0, "label": ln.get("label", "")}
        buckets[code]["debit"] += ln.get("debit", 0) or 0
        buckets[code]["credit"] += ln.get("credit", 0) or 0
    result = []
    for b in buckets.values():
        d, c = round(b["debit"], 2), round(b["credit"], 2)
        if d > 0 or c > 0:
            result.append(_line(b["account_code"], d, c, b["label"]))
    return result


def _line_amounts(quantity: float, unit_price: float, vat_rate: float) -> tuple[float, float, float]:
    ht = (quantity or 0) * (unit_price or 0)
    return amounts_from_ht(ht, vat_rate)


def _journal_product_amount(ht: float, ttc: float) -> float:
    """Montant inscrit au compte produit/charge (TTC si pas de ventilation TVA)."""
    return abs(ttc) if not JOURNAL_SPLIT_VAT else abs(ht)


def _resolve_product_accounts(db: Session, product_type: str, stock_item_id: int | None) -> dict:
    from app.services.account_resolver import resolve_product_accounts_db

    item = None
    if stock_item_id:
        item = db.query(StockItem).filter(StockItem.id == stock_item_id).first()
        if item:
            product_type = item.product_accounting_type or product_type
    return resolve_product_accounts_db(db, item, product_type)


def _resolve_line_account(
    db: Session,
    *,
    product_type: str,
    stock_item_id: int | None,
    account_id: int | None = None,
    code_override: str = "",
    purchase_account: str = "",
    purchase_account_id: int | None = None,
    sale_account: str = "",
    sale_account_id: int | None = None,
) -> dict:
    from app.services.account_resolver import account_code as acode

    acc = _resolve_product_accounts(db, product_type, stock_item_id)
    if account_id or code_override:
        c = acode(db, account_id=account_id, code=code_override, fallback="")
        if c:
            acc["purchase"] = c
    if purchase_account or purchase_account_id:
        acc["purchase"] = acode(db, code=purchase_account, account_id=purchase_account_id, fallback=acc.get("purchase") or "")
    if sale_account or sale_account_id:
        acc["sale"] = acode(db, code=sale_account, account_id=sale_account_id, fallback=acc.get("sale") or "")
    return acc


def _allocate_accessory_fees(product_lines: list[dict], fee_lines: list) -> list[dict]:
    """Répartit transport/douane/assurance proportionnellement au HT par type."""
    if not product_lines or not fee_lines:
        return product_lines

    ht_by_type: dict[str, float] = {}
    for pl in product_lines:
        ht_by_type[pl["product_type"]] = ht_by_type.get(pl["product_type"], 0) + pl["ht"]

    total_ht = sum(ht_by_type.values()) or 1.0
    extra: dict[str, float] = {k: 0.0 for k in ht_by_type}

    for fee in fee_lines:
        fee_ht = fee["ht"]
        kind = (fee.get("line_kind") or "transport").upper()
        fee_meta = ACCESSORY_FEE_TYPES.get(kind, ACCESSORY_FEE_TYPES.get("TRANSPORT", {}))
        targets = fee_meta.get("accounts", {})
        if targets:
            eligible = [t for t in ht_by_type if t in targets]
            if not eligible:
                eligible = list(ht_by_type.keys())
        else:
            eligible = list(ht_by_type.keys())
        eligible_ht = sum(ht_by_type[t] for t in eligible) or total_ht
        for ptype in eligible:
            share = ht_by_type[ptype] / eligible_ht if eligible_ht else 0
            extra[ptype] = extra.get(ptype, 0) + fee_ht * share

    for pl in product_lines:
        pl["ht"] = round(pl["ht"] + extra.get(pl["product_type"], 0), 2)
        pl["ttc"] = round(pl["ht"] * (1 + pl["vat_rate"] / 100), 2)
        pl["tva"] = round(pl["ttc"] - pl["ht"], 2)
    return product_lines


def build_invoice_lines(
    db: Session,
    invoice: Invoice,
    doc_lines: list[DocumentLine],
    cfg: dict,
) -> list[dict]:
    """Écriture VE multi-lignes par typologie article."""
    acc_default = cfg["accounts"]
    from app.services.auxiliary_account_service import client_account_for_invoice
    client_acc = client_account_for_invoice(db, invoice.client_id, acc_default)
    is_credit = getattr(invoice, "doc_type", "invoice") == "credit_note"
    sign = -1 if is_credit else 1
    journal_lines: list[dict] = []
    total_ttc = 0.0

    cn_type = getattr(invoice, "credit_note_type", "") or "RETURN"
    cn_meta = CREDIT_NOTE_TYPES.get(cn_type, CREDIT_NOTE_TYPES["RETURN"])

    if doc_lines:
        for ln in doc_lines:
            ptype = ln.product_type or "SERVICE"
            if ln.stock_item_id:
                si = db.query(StockItem).filter(StockItem.id == ln.stock_item_id).first()
                if si:
                    ptype = si.product_accounting_type or ptype
            acc = _resolve_line_account(
                db,
                product_type=ptype,
                stock_item_id=ln.stock_item_id,
                account_id=getattr(ln, "account_id", None),
                code_override=getattr(ln, "account_code", "") or "",
                sale_account=getattr(ln, "sale_account", "") or "",
                sale_account_id=getattr(ln, "sale_account_id", None),
            )
            if is_credit and cn_meta.get("accounts_debit"):
                acc["sale"] = cn_meta["accounts_debit"]

            rate = resolve_vat_rate(db, line_rate=ln.vat_rate, doc_rate=invoice.vat_rate)
            ht, tva, ttc = _line_amounts(ln.quantity, ln.unit_price, rate)
            ht, tva, ttc = ht * sign, tva * sign, ttc * sign
            total_ttc += ttc

            sale_code = acc["sale"] or acc_default["sales_services"]
            vat_code = acc.get("vat_collected") or acc_default["vat_collected_services"]
            post_amt = _journal_product_amount(ht, ttc) * (1 if sign >= 0 else -1)

            journal_lines.append(_line(sale_code, max(-post_amt, 0), max(post_amt, 0), ln.description or "Vente"))
            if JOURNAL_SPLIT_VAT and abs(tva) >= 0.01:
                journal_lines.append(_line(vat_code, max(-tva, 0), max(tva, 0), "TVA collectée"))

            inv_method = get_inventory_method(db)
            stock_types = ("MERCHANDISE", "RAW_MATERIAL", "SUPPLY")
            if (
                inv_method == "PERMANENT"
                and not is_credit
                and acc.get("stock")
                and acc.get("variation")
                and ptype in stock_types
            ):
                cost = abs(ht)
                journal_lines.append(_line(acc["variation"], cost, 0, "Sortie stock"))
                journal_lines.append(_line(acc["stock"], 0, cost, "Stock"))

            if is_credit and cn_meta.get("reverse_stock") and acc.get("stock") and acc.get("variation"):
                cost = abs(ht)
                journal_lines.append(_line(acc["stock"], cost, 0, "Retour stock"))
                journal_lines.append(_line(acc["variation"], 0, cost, "Variation stock"))
    else:
        rate = resolve_vat_rate(db, doc_rate=invoice.vat_rate)
        ht, tva, ttc = amounts_from_ht(float(invoice.amount or 0), rate)
        ht, tva, ttc = ht * sign, tva * sign, ttc * sign
        total_ttc = ttc
        sale_code = acc_default["sales_services"]
        post_amt = _journal_product_amount(ht, ttc) * (1 if sign >= 0 else -1)
        journal_lines.append(_line(sale_code, max(-post_amt, 0), max(post_amt, 0), "Vente"))
        if JOURNAL_SPLIT_VAT and abs(tva) >= 0.01:
            journal_lines.append(_line(acc_default["vat_collected_services"], max(-tva, 0), max(tva, 0), "TVA"))

    journal_lines.insert(0, _line(client_acc, max(total_ttc, 0), max(-total_ttc, 0), invoice.number or ""))
    return _merge_lines(journal_lines)


def build_supplier_invoice_lines(
    db: Session,
    inv: SupplierInvoice,
    cfg: dict,
) -> list[dict]:
    """Écriture AC multi-lignes — typologie + frais accessoires répartis."""
    from app.services.account_resolver import account_code

    acc_default = cfg["accounts"]
    from app.services.auxiliary_account_service import supplier_account_for_invoice
    supplier_acc = supplier_account_for_invoice(db, inv.supplier_id, acc_default)
    inv_method = get_inventory_method(db)
    lines_db = db.query(SupplierInvoiceLine).filter(
        SupplierInvoiceLine.supplier_invoice_id == inv.id
    ).order_by(SupplierInvoiceLine.position).all()

    journal_lines: list[dict] = []
    supplier_credit = 0.0

    if lines_db:
        product_rows: list[dict] = []
        fee_rows: list[dict] = []

        for ln in lines_db:
            kind = (ln.line_kind or "product").lower()
            rate = resolve_vat_rate(db, line_rate=ln.vat_rate, doc_rate=getattr(inv, "vat_rate", None))
            ht, tva, ttc = _line_amounts(ln.quantity, ln.unit_price, rate)
            row = {
                "line": ln,
                "product_type": ln.product_type or "MERCHANDISE",
                "ht": ht,
                "tva": tva,
                "ttc": ttc,
                "vat_rate": rate,
                "line_kind": kind,
            }
            if kind == "product":
                product_rows.append(row)
            else:
                fee_rows.append(row)

        product_rows = _allocate_accessory_fees(product_rows, fee_rows)

        for row in product_rows:
            ln = row["line"]
            ptype = row["product_type"]
            acc = _resolve_line_account(
                db,
                product_type=ptype,
                stock_item_id=ln.stock_item_id,
                account_id=ln.account_id,
                code_override=ln.account_code or "",
                purchase_account=ln.purchase_account or "",
                purchase_account_id=getattr(ln, "purchase_account_id", None),
            )
            ht, tva, ttc = row["ht"], row["tva"], row["ttc"]
            supplier_credit += ttc

            if ptype == "ASSET":
                charge_acc = acc.get("purchase") or "244200"
            elif inv_method == "PERMANENT" and acc.get("stock") and ptype in ("MERCHANDISE", "RAW_MATERIAL", "SUPPLY"):
                charge_acc = acc["stock"]
            else:
                charge_acc = acc["purchase"] or acc_default["purchases_goods"]

            vat_code = account_code(
                db,
                code=ln.vat_account or "",
                account_id=getattr(ln, "vat_account_id", None),
                fallback=acc.get("vat_deductible") or acc_default["vat_deductible_purchases"],
            )

            post_amt = _journal_product_amount(ht, ttc)

            journal_lines.append(_line(charge_acc, post_amt, 0, ln.description or "Achat"))
            if JOURNAL_SPLIT_VAT and tva >= 0.01:
                journal_lines.append(_line(vat_code, tva, 0, "TVA récupérable"))

        for row in fee_rows:
            ln = row["line"]
            ptype = row["product_type"]
            kind = row["line_kind"].upper()
            fee = ACCESSORY_FEE_TYPES.get(kind, ACCESSORY_FEE_TYPES["TRANSPORT"])
            charge_acc = fee["accounts"].get(ptype, accounts_for_type(ptype).get("accessory") or "601500")
            ht, tva, ttc = row["ht"], row["tva"], row["ttc"]
            supplier_credit += ttc
            post_amt = _journal_product_amount(ht, ttc)
            journal_lines.append(_line(charge_acc, post_amt, 0, ln.description or fee.get("label", "Frais")))
            if JOURNAL_SPLIT_VAT and tva >= 0.01:
                journal_lines.append(_line(acc_default["vat_deductible_purchases"], tva, 0, "TVA frais"))
    else:
        rate = resolve_vat_rate(db, doc_rate=getattr(inv, "vat_rate", None))
        ht, tva, ttc = amounts_from_ht(float(inv.amount or 0), rate)
        supplier_credit = ttc
        post_amt = _journal_product_amount(ht, ttc)
        journal_lines.append(_line(acc_default["purchases_goods"], post_amt, 0, "Achat"))
        if JOURNAL_SPLIT_VAT and tva >= 0.01:
            journal_lines.append(_line(acc_default["vat_deductible_purchases"], tva, 0, "TVA"))

    journal_lines.append(_line(supplier_acc, 0, round(supplier_credit, 2), inv.number or ""))
    merged = _merge_lines(journal_lines)
    if getattr(inv, "doc_type", "invoice") == "credit_note":
        for ln in merged:
            d, c = ln.get("debit", 0), ln.get("credit", 0)
            ln["debit"], ln["credit"] = c, d
    return merged


def _already_posted(db: Session, source_type: str, source_id: int) -> AccountingTransaction | None:
    return db.query(AccountingTransaction).filter(
        AccountingTransaction.source_type == source_type,
        AccountingTransaction.source_id == source_id,
        AccountingTransaction.status == "posted",
    ).first()


def post_transaction(
    db: Session,
    source_type: str,
    source_id: int,
    payload: dict,
    *,
    entry_date: date | None = None,
    fiscal_year: int | None = None,
    force: bool = False,
) -> AccountingTransaction:
    """Persiste accounting_transaction + journal_entry + lines."""
    existing = db.query(AccountingTransaction).filter(
        AccountingTransaction.source_type == source_type,
        AccountingTransaction.source_id == source_id,
    ).first()
    if existing:
        if existing.status == "posted" and not force:
            return existing
        if existing.journal_entry_id:
            db.query(JournalLine).filter(JournalLine.entry_id == existing.journal_entry_id).delete()
            old = db.query(JournalEntry).filter(JournalEntry.id == existing.journal_entry_id).first()
            if old:
                db.delete(old)
        db.delete(existing)
        db.flush()

    lines = payload.get("lines") or []
    if not validate_entry_balance(lines):
        raise ValueError(f"Écriture non équilibrée pour {source_type}#{source_id}")

    cfg = _settings(db)
    fy = fiscal_year or cfg.get("fiscal_year") or date.today().year
    assert_fiscal_year_open(db, fy)
    ed = entry_date or date.today()

    tx = AccountingTransaction(
        source_type=source_type,
        source_id=source_id,
        status="draft",
        label=payload.get("label", ""),
        amount=sum(l.get("debit", 0) or 0 for l in lines),
    )
    db.add(tx)
    db.flush()

    entry = JournalEntry(
        date=ed,
        journal=payload.get("journal", "OD"),
        reference=payload.get("reference", ""),
        label=payload.get("label", ""),
        status="validée",
        fiscal_year=fy,
        period=ed.month,
        source_type=source_type,
        source_id=source_id,
        accounting_transaction_id=tx.id,
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

    tx.journal_entry_id = entry.id
    tx.status = "posted"
    tx.posted_at = _now_iso()
    db.commit()
    db.refresh(tx)
    return tx


def on_invoice_validated(db: Session, invoice: Invoice, *, force: bool = False) -> AccountingTransaction | None:
    """Hook : facture client validée → écriture VE automatique."""
    if invoice.status not in POSTING_STATUSES_INVOICE:
        return None
    if getattr(invoice, "journal_entry_id", None) and not force:
        existing = _already_posted(db, "invoice", invoice.id)
        if existing:
            return existing

    cfg = _settings(db)
    doc_lines = db.query(DocumentLine).filter(DocumentLine.invoice_id == invoice.id).all()
    lines = build_invoice_lines(db, invoice, doc_lines, cfg)
    payload = {
        "journal": "VE",
        "reference": invoice.number or f"F{invoice.id}",
        "label": f"Facture client {invoice.number or invoice.id}",
        "lines": lines,
    }
    tx = post_transaction(db, "invoice", invoice.id, payload, entry_date=invoice.date, force=force)
    invoice.journal_entry_id = tx.journal_entry_id
    db.commit()
    return tx


def on_supplier_invoice_validated(db: Session, inv: SupplierInvoice, *, force: bool = False) -> AccountingTransaction | None:
    """Hook : facture fournisseur validée → écriture AC automatique."""
    if inv.status not in POSTING_STATUSES_PURCHASE:
        return None
    if getattr(inv, "journal_entry_id", None) and not force:
        existing = _already_posted(db, "supplier_invoice", inv.id)
        if existing:
            return existing

    cfg = _settings(db)
    lines = build_supplier_invoice_lines(db, inv, cfg)
    payload = {
        "journal": "AC",
        "reference": inv.number or f"SF{inv.id}",
        "label": f"Facture fournisseur {inv.number or inv.id}",
        "lines": lines,
    }
    tx = post_transaction(db, "supplier_invoice", inv.id, payload, entry_date=inv.date, force=force)
    inv.journal_entry_id = tx.journal_entry_id
    db.commit()
    return tx


def on_payment_recorded(
    db: Session,
    *,
    amount: float,
    direction: str,
    payment_method: str,
    reference: str,
    label: str,
    source_id: int,
    entry_date: date | None = None,
) -> AccountingTransaction:
    """Encaissement / décaissement → BQ ou CA."""
    from app.syscohada.posting import build_payment_entry
    cfg = _settings(db)
    payload = build_payment_entry(
        amount,
        direction=direction,
        payment_method=payment_method,
        reference=reference,
        label=label,
        accounts=cfg["accounts"],
    )
    st = f"payment_{direction}"
    return post_transaction(db, st, source_id, payload, entry_date=entry_date)


def close_vat_period(db: Session, year: int, period: int) -> dict:
    """
    Centralisation TVA : soldes 443 + 445 → 4441 (due) ou 4449 (crédit).
    """
    from app.models_accounting import VatPeriod, VatDeclaration
    from app.services.accounting_reports import balance_generale

    vp = db.query(VatPeriod).filter(VatPeriod.year == year, VatPeriod.period == period).first()
    if not vp:
        vp = VatPeriod(year=year, period=period, status="open")
        db.add(vp)
        db.flush()

    if vp.status == "closed":
        raise ValueError(f"Période TVA {year}-{period:02d} déjà clôturée")

    balance = balance_generale(db, fiscal_year=year, period=str(period))
    collected = deductible = 0.0
    for row in balance:
        code = row["account_code"]
        if code.startswith("443"):
            collected += (row.get("credit", 0) or 0) - (row.get("debit", 0) or 0)
        elif code.startswith("445"):
            deductible += (row.get("debit", 0) or 0) - (row.get("credit", 0) or 0)

    collected = round(collected, 2)
    deductible = round(deductible, 2)
    net = round(collected - deductible, 2)
    cfg = _settings(db)
    acc = cfg["accounts"]

    # Bascule SYSCOHADA : 443 et 445 → 444
    lines: list[dict] = []
    if collected > 0.01:
        lines.append(_line(acc.get("vat_collected_sales", "443100"), collected, 0, "Centralisation TVA facturée"))
    if deductible > 0.01:
        lines.append(_line(acc.get("vat_deductible_purchases", "445200"), 0, deductible, "Centralisation TVA récupérable"))

    if net > 0.01:
        lines.append(_line(acc.get("vat_due", "444100"), 0, net, "TVA due"))
        position = "due"
        target = acc.get("vat_due", "444100")
    elif net < -0.01:
        lines.append(_line(acc.get("vat_credit", "444900"), abs(net), 0, "Crédit de TVA à reporter"))
        position = "credit"
        target = acc.get("vat_credit", "444900")
    else:
        position = "zero"
        target = ""

    if not lines:
        raise ValueError("Aucun solde TVA à centraliser sur cette période")

    lines = _merge_lines(lines)
    if not validate_entry_balance(lines):
        raise ValueError("Écriture TVA non équilibrée")

    payload = {
        "journal": "OD",
        "reference": f"TVA-{year}-{period:02d}",
        "label": f"Clôture TVA {year}/{period:02d}",
        "lines": lines,
    }
    tx = post_transaction(db, "vat_close", vp.id, payload, fiscal_year=year, force=True)

    decl = VatDeclaration(
        vat_period_id=vp.id,
        collected_amount=collected,
        deductible_amount=deductible,
        net_amount=net,
        position=position,
        account_due=target,
        declared_at=_now_iso(),
    )
    db.add(decl)
    vp.status = "closed"
    vp.closed_at = _now_iso()
    vp.journal_entry_id = tx.journal_entry_id
    db.commit()

    return {
        "ok": True,
        "period_id": vp.id,
        "collected": collected,
        "deductible": deductible,
        "net": net,
        "position": position,
        "journal_entry_id": tx.journal_entry_id,
    }


def seed_tax_rates(db: Session) -> None:
    from app.syscohada.constants import TOGO_VAT_RATES
    for t in TOGO_VAT_RATES:
        row = db.query(TaxRate).filter(TaxRate.code == t["code"]).first()
        if not row:
            db.add(TaxRate(
                code=t["code"],
                name=t["name"],
                rate=t["rate"],
                account_collected=t.get("account_collected", "443100"),
                account_deductible=t.get("account_deductible", "445200"),
            ))
    db.commit()


def amortize_prepaid_expense(db: Session, prepaid) -> dict:
    """Répartition mensuelle CCA — débit charge, crédit 476."""
    remaining = (prepaid.total_amount or 0) - (prepaid.amortized or 0)
    if remaining <= 0:
        raise ValueError("Charge constatée d'avance déjà soldée")
    months_left = max(prepaid.months or 1, 1)
    monthly = round(remaining / months_left, 2)
    if monthly <= 0:
        raise ValueError("Montant mensuel nul")

    lines = [
        _line(prepaid.account_charge or "626100", monthly, 0, prepaid.label),
        _line(prepaid.account_prepaid or "476000", 0, monthly, "CCA"),
    ]
    payload = {
        "journal": "OD",
        "reference": f"CCA-{prepaid.id}",
        "label": f"Étalement {prepaid.label}",
        "lines": lines,
    }
    tx = post_transaction(db, "prepaid_amortize", prepaid.id, payload)
    prepaid.amortized = round((prepaid.amortized or 0) + monthly, 2)
    if prepaid.amortized >= (prepaid.total_amount or 0) - 0.01:
        prepaid.status = "completed"
    db.commit()
    return {"ok": True, "amount": monthly, "journal_entry_id": tx.journal_entry_id}


def _unpost_stock_movement(db: Session, movement_id: int) -> None:
    """Retire l'écriture comptable (transaction + entrée + lignes) déjà postée pour ce
    mouvement, s'il en existe une — utilisé quand une édition rend le mouvement
    non-comptabilisable (transfert, montant nul...) pour ne pas laisser une écriture
    obsolète dans le journal IN."""
    existing = db.query(AccountingTransaction).filter(
        AccountingTransaction.source_type == "stock_movement",
        AccountingTransaction.source_id == movement_id,
    ).first()
    if not existing:
        return
    if existing.journal_entry_id:
        db.query(JournalLine).filter(JournalLine.entry_id == existing.journal_entry_id).delete()
        old = db.query(JournalEntry).filter(JournalEntry.id == existing.journal_entry_id).first()
        if old:
            db.delete(old)
    db.delete(existing)
    db.flush()


def on_stock_movement(db: Session, movement_id: int, *, force: bool = False) -> AccountingTransaction | None:
    """Inventaire permanent — entrée/sortie stock → journal IN.

    Les transferts inter-magasins (movement_kind == "transfert") ne génèrent
    aucune écriture : ils déplacent le stock entre deux magasins de la même
    société sans changer sa valeur totale (les deux jambes s'annulent), les
    comptabiliser ne ferait qu'ajouter du bruit net-zéro dans le journal IN —
    le cloisonner correctement veut dire ne jamais y mettre autre chose que
    de vraies entrées/sorties de stock.
    """
    from app.models import StockMovement

    mov = db.query(StockMovement).filter(StockMovement.id == movement_id).first()
    if not mov:
        raise ValueError("Mouvement stock introuvable")
    # Un mouvement édité peut basculer vers un cas non-comptabilisable (transfert,
    # méthode d'inventaire désactivée, montant nul) alors qu'une écriture existait déjà
    # pour son état précédent — on la retire systématiquement pour ne jamais laisser
    # une écriture orpheline qui ne correspond plus au mouvement réel.
    if get_inventory_method(db) != "PERMANENT":
        _unpost_stock_movement(db, movement_id)
        return None
    if getattr(mov, "movement_kind", "") == "transfert":
        _unpost_stock_movement(db, movement_id)
        return None

    item = db.query(StockItem).filter(StockItem.id == mov.item_id).first()
    if not item:
        raise ValueError("Article introuvable")

    acc = _resolve_product_accounts(db, item.product_accounting_type or "MERCHANDISE", item.id)
    stock_acc = acc.get("stock") or "311100"
    var_acc = acc.get("variation") or "603100"
    unit_cost = mov.unit_cost if mov.unit_cost else float(item.unit_cost or 0)
    amount = round(abs(mov.quantity or 0) * float(unit_cost or 0), 2)
    if amount <= 0:
        amount = round(abs(mov.quantity or 0) * float(item.unit_price or 0) * 0.7, 2)
    if amount <= 0:
        _unpost_stock_movement(db, movement_id)
        return None

    # Le sens réel du mouvement (entrée/sortie) fait foi — movement_kind ("ajustement",
    # "inventaire"...) ne doit jamais l'emporter, sinon un ajustement à la baisse (perte,
    # casse) se retrouve comptabilisé comme une entrée de stock au lieu d'une sortie.
    is_in = mov.type == "entrée"
    if is_in:
        lines = [_line(stock_acc, amount, 0, "Entrée stock"), _line(var_acc, 0, amount, "Variation")]
    else:
        lines = [_line(var_acc, amount, 0, "Sortie stock"), _line(stock_acc, 0, amount, "Variation")]

    payload = {
        "journal": "IN",
        "reference": f"STK-{movement_id}",
        "label": mov.reason or "Mouvement stock",
        "lines": lines,
    }
    return post_transaction(db, "stock_movement", movement_id, payload, entry_date=mov.date, force=force)


def create_prepaid_expense(db: Session, data: dict) -> dict:
    """CCA — constatation initiale : débit 476, crédit charge (ou fournisseur)."""
    from app.models_accounting import PrepaidExpense

    row = PrepaidExpense(**data)
    db.add(row)
    db.flush()
    lines = [
        _line(row.account_prepaid or "476000", row.total_amount, 0, row.label),
        _line(row.account_charge or "626100", 0, row.total_amount, "Charge à étaler"),
    ]
    payload = {
        "journal": "OD",
        "reference": f"CCA-NEW-{row.id}",
        "label": f"Constatation CCA — {row.label}",
        "lines": lines,
    }
    post_transaction(db, "prepaid_init", row.id, payload, entry_date=row.start_date)
    db.commit()
    return {"ok": True, "id": row.id}


def seed_credit_note_types(db: Session) -> None:
    from app.models_accounting import CreditNoteTypeRef
    from app.syscohada.product_types import CREDIT_NOTE_TYPES

    for code, meta in CREDIT_NOTE_TYPES.items():
        if not db.query(CreditNoteTypeRef).filter(CreditNoteTypeRef.code == code).first():
            db.add(CreditNoteTypeRef(
                code=code,
                label=meta.get("label", code),
                account_code=meta.get("accounts_debit", ""),
                reverse_stock=bool(meta.get("reverse_stock")),
            ))
    db.commit()


def seed_stock_categories(db: Session) -> None:
    from app.models_accounting import StockCategory
    from app.syscohada.product_types import STOCK_CATEGORIES_OHADA
    for cat in STOCK_CATEGORIES_OHADA:
        row = db.query(StockCategory).filter(StockCategory.code == cat["code"]).first()
        if not row:
            acc_map = accounts_for_type(cat["product_type"])
            db.add(StockCategory(
                code=cat["code"],
                label=cat["label"],
                account_stock=cat["account"],
                account_variation=acc_map.get("variation") or "603100",
                product_type=cat["product_type"],
            ))
    db.commit()
