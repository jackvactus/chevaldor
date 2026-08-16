"""Clôture comptable annuelle — solde classes 6/7 vers résultat."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models_erp import JournalEntry, JournalLine
from app.fiscal_service import close_fiscal_year, is_fiscal_year_closed, list_closed_fiscal_years
from app.services.accounting_reports import balance_generale, validate_entry_balance

RESULT_ACCOUNT = "131000"
RETAINED_EARNINGS = "121000"


def _closing_lines_for_pl(balance: list[dict]) -> list[dict]:
    """Solde les comptes 6 et 7 vers le compte de résultat 131000."""
    lines: list[dict] = []
    result_net = 0.0

    for row in balance:
        code = row.get("account_code", "")
        if not (code.startswith("6") or code.startswith("7")):
            continue
        bal = float(row.get("balance") or 0)
        if abs(bal) < 0.01:
            continue
        label = row.get("label") or code
        if code.startswith("6"):
            # Charges : solde débiteur → créditer le compte, débiter résultat
            if bal > 0:
                lines.append({"account_code": code, "debit": 0, "credit": round(bal, 2), "label": f"Clôture {label}"})
                result_net -= bal
        else:
            # Produits : solde créditeur → débiter le compte, créditer résultat
            if bal < 0:
                amt = abs(bal)
                lines.append({"account_code": code, "debit": round(amt, 2), "credit": 0, "label": f"Clôture {label}"})
                result_net += amt
            elif bal > 0:
                lines.append({"account_code": code, "debit": round(bal, 2), "credit": 0, "label": f"Clôture {label}"})
                result_net += bal

    if abs(result_net) >= 0.01:
        if result_net > 0:
            lines.append({
                "account_code": RESULT_ACCOUNT,
                "debit": 0,
                "credit": round(result_net, 2),
                "label": "Résultat bénéficiaire — clôture",
            })
        else:
            lines.append({
                "account_code": RESULT_ACCOUNT,
                "debit": round(abs(result_net), 2),
                "credit": 0,
                "label": "Résultat déficitaire — clôture",
            })

    return lines


def close_fiscal_year_full(db: Session, year: int, *, transfer_to_equity: bool = True) -> dict:
    """
    Clôture exercice :
    1. Écriture OD solde comptes 6/7 → 131000
    2. (Option) Transfert 131000 → 121000
    3. Verrouillage exercice
    """
    if is_fiscal_year_closed(db, year):
        raise ValueError(f"L'exercice {year} est déjà clôturé")

    balance = balance_generale(db, fiscal_year=year)
    pl_lines = _closing_lines_for_pl(balance)
    if not pl_lines:
        raise ValueError("Aucun solde de charges/produits à clôturer pour cet exercice")

    if not validate_entry_balance(pl_lines):
        raise ValueError("Écriture de clôture P&L non équilibrée")

    close_date = date(year, 12, 31)
    entry_pl = JournalEntry(
        date=close_date,
        journal="OD",
        reference=f"CLOTURE-PL-{year}",
        label=f"Clôture charges et produits — exercice {year}",
        status="validée",
        fiscal_year=year,
        period=12,
        source_type="fiscal_close",
        source_id=year,
    )
    db.add(entry_pl)
    db.flush()
    for ln in pl_lines:
        db.add(JournalLine(
            entry_id=entry_pl.id,
            account_code=ln["account_code"],
            debit=ln["debit"],
            credit=ln["credit"],
            label=ln["label"],
        ))

    entry_equity_id = None
    if transfer_to_equity:
        result_bal = sum(
            (r.get("credit", 0) or 0) - (r.get("debit", 0) or 0)
            for r in pl_lines if r["account_code"] == RESULT_ACCOUNT
        )
        if abs(result_bal) >= 0.01:
            eq_lines = []
            if result_bal > 0:
                eq_lines = [
                    {"account_code": RESULT_ACCOUNT, "debit": round(result_bal, 2), "credit": 0, "label": "Report résultat"},
                    {"account_code": RETAINED_EARNINGS, "debit": 0, "credit": round(result_bal, 2), "label": "Résultat affecté"},
                ]
            else:
                amt = abs(result_bal)
                eq_lines = [
                    {"account_code": RESULT_ACCOUNT, "debit": 0, "credit": round(amt, 2), "label": "Report résultat"},
                    {"account_code": RETAINED_EARNINGS, "debit": round(amt, 2), "credit": 0, "label": "Perte affectée"},
                ]
            if validate_entry_balance(eq_lines):
                entry_eq = JournalEntry(
                    date=close_date,
                    journal="OD",
                    reference=f"CLOTURE-RES-{year}",
                    label=f"Affectation résultat — exercice {year}",
                    status="validée",
                    fiscal_year=year,
                    period=12,
                    source_type="fiscal_close_equity",
                    source_id=year,
                )
                db.add(entry_eq)
                db.flush()
                for ln in eq_lines:
                    db.add(JournalLine(entry_id=entry_eq.id, **ln))
                entry_equity_id = entry_eq.id

    closed = close_fiscal_year(db, year)
    db.commit()
    return {
        "ok": True,
        "year": year,
        "closed_years": closed,
        "pl_entry_id": entry_pl.id,
        "equity_entry_id": entry_equity_id,
        "lines_count": len(pl_lines),
    }
