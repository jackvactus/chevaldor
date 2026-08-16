"""États financiers SYSCOHADA — bilan, compte de résultat, flux de trésorerie."""

from __future__ import annotations

from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models_erp import JournalLine, JournalEntry, SupplierInvoice, TreasuryMovement, BankAccount
from app.models import Account, Invoice
from app.services.accounting_reports import balance_generale, compte_de_resultat


# Rubriques bilan OHADA (système normal — structure simplifiée)
BILAN_ACTIF_SECTIONS = [
    ("immobilisations", "2", "Immobilisations brutes"),
    ("amortissements", "28", "Amortissements (soustraction)"),
    ("stocks", "3", "Stocks"),
    ("tiers_actif", "41", "Créances clients et autres"),
    ("tresorerie", "5", "Trésorerie"),
]

BILAN_PASSIF_SECTIONS = [
    ("capitaux", "1", "Capitaux propres et ressources stables"),
    ("tiers_passif", "40", "Dettes fournisseurs et autres"),
    ("etat", "44", "État et taxes"),
]


def _sum_by_prefix(balance: list[dict], prefix: str, side: str = "balance") -> float:
    total = 0.0
    for row in balance:
        code = row.get("account_code", "")
        if not code.startswith(prefix):
            continue
        bal = row.get("balance", 0) or 0
        if side == "debit":
            total += row.get("debit", 0) or 0
        elif side == "credit":
            total += row.get("credit", 0) or 0
        else:
            total += bal
    return round(total, 2)


def bilan_ohada(db: Session, fiscal_year: int | None = None) -> dict:
    """Bilan structuré selon les classes SYSCOHADA (actif / passif)."""
    balance = balance_generale(db, fiscal_year=fiscal_year)
    actif_lines = []
    passif_lines = []

    for key, prefix, label in BILAN_ACTIF_SECTIONS:
        if key == "amortissements":
            amt = _sum_by_prefix(balance, prefix, "credit")
            actif_lines.append({"section": key, "label": label, "amount": -abs(amt)})
        else:
            amt = sum(r["balance"] for r in balance if r["account_code"].startswith(prefix) and r["balance"] > 0)
            actif_lines.append({"section": key, "label": label, "amount": round(amt, 2)})

    for key, prefix, label in BILAN_PASSIF_SECTIONS:
        amt = sum(-r["balance"] for r in balance if r["account_code"].startswith(prefix) and r["balance"] < 0)
        if amt <= 0:
            amt = sum(r["credit"] - r["debit"] for r in balance if r["account_code"].startswith(prefix))
        passif_lines.append({"section": key, "label": label, "amount": round(max(amt, 0), 2)})

    total_actif = round(sum(l["amount"] for l in actif_lines), 2)
    total_passif = round(sum(l["amount"] for l in passif_lines), 2)

    creances = db.query(func.coalesce(func.sum(Invoice.amount - Invoice.paid), 0)).filter(
        Invoice.status.in_(["envoyée", "en retard"]),
        Invoice.is_archived == False,  # noqa: E712
    ).scalar() or 0
    dettes = db.query(func.coalesce(func.sum(SupplierInvoice.amount - SupplierInvoice.paid), 0)).filter(
        SupplierInvoice.status.in_(["validée", "en retard"]),
    ).scalar() or 0

    return {
        "framework": "SYSCOHADA",
        "fiscal_year": fiscal_year,
        "actif": {"lines": actif_lines, "total": total_actif},
        "passif": {"lines": passif_lines, "total": total_passif},
        "equilibre": round(total_actif - total_passif, 2),
        "creances_clients_hors_compta": float(creances),
        "dettes_fournisseurs_hors_compta": float(dettes),
        "detail_balance": balance,
    }


def compte_resultat_ohada(db: Session, fiscal_year: int | None = None) -> dict:
    """Compte de résultat par grandes masses (classes 6, 7, 8)."""
    balance = balance_generale(db, fiscal_year=fiscal_year)
    charges_6 = round(sum(r["debit"] - r["credit"] for r in balance if r["account_code"].startswith("6")), 2)
    produits_7 = round(sum(r["credit"] - r["debit"] for r in balance if r["account_code"].startswith("7")), 2)
    charges_8 = round(sum(r["debit"] - r["credit"] for r in balance if r["account_code"].startswith("8") and _type_8(r["account_code"]) == "charge"), 2)
    produits_8 = round(sum(r["credit"] - r["debit"] for r in balance if r["account_code"].startswith("8") and _type_8(r["account_code"]) == "produit"), 2)

    result_exploitation = round(produits_7 - charges_6, 2)
    result_hao = round(produits_8 - charges_8, 2)
    result_net = round(result_exploitation + result_hao, 2)

    fallback = compte_de_resultat(db, fiscal_year=fiscal_year)
    if not balance:
        return {
            "framework": "SYSCOHADA",
            "fiscal_year": fiscal_year,
            "lines": fallback.get("lines", []),
            "resultat_net": fallback.get("net_result", 0),
            "source": "transactions",
        }

    lines = [
        {"label": "Produits d'exploitation (cl. 7)", "amount": produits_7},
        {"label": "Charges d'exploitation (cl. 6)", "amount": charges_6},
        {"label": "Résultat d'exploitation", "amount": result_exploitation},
        {"label": "Produits HAO (cl. 8)", "amount": produits_8},
        {"label": "Charges HAO (cl. 8)", "amount": charges_8},
        {"label": "Résultat hors activités ordinaires", "amount": result_hao},
        {"label": "Résultat net", "amount": result_net},
    ]
    return {
        "framework": "SYSCOHADA",
        "fiscal_year": fiscal_year,
        "lines": lines,
        "resultat_net": result_net,
        "source": "journal",
    }


def _type_8(code: str) -> str:
    try:
        n = int(code[:2])
        return "produit" if n % 2 == 0 else "charge"
    except ValueError:
        return "charge"


def tafire_simplifie(db: Session, fiscal_year: int | None = None) -> dict:
    """Tableau des flux de trésorerie — méthode indirecte simplifiée."""
    cr = compte_resultat_ohada(db, fiscal_year=fiscal_year)
    resultat = cr.get("resultat_net", 0) or 0

    encaissements = sum(i.paid or 0 for i in db.query(Invoice).all())
    decaissements = sum(s.paid or 0 for s in db.query(SupplierInvoice).all())
    flux_ops = encaissements - decaissements

    treso_mvt = 0.0
    for m in db.query(TreasuryMovement).all():
        amt = m.amount or 0
        if m.type in ("caisse_entree", "banque_entree"):
            treso_mvt += amt
        else:
            treso_mvt -= amt

    banques = sum(b.balance or 0 for b in db.query(BankAccount).all())

    return {
        "framework": "SYSCOHADA",
        "fiscal_year": fiscal_year,
        "flux_exploitation": {
            "resultat_net": round(float(resultat), 2),
            "encaissements_clients": round(encaissements, 2),
            "decaissements_fournisseurs": round(decaissements, 2),
            "flux_net_exploitation": round(flux_ops, 2),
        },
        "flux_tresorerie_direct": round(treso_mvt, 2),
        "tresorerie_cloture": round(banques, 2),
        "variation_estimee": round(flux_ops + treso_mvt, 2),
    }


def vat_position(db: Session, fiscal_year: int | None = None) -> dict:
    """Position TVA — soldes 443, 445, 444."""
    balance = balance_generale(db, fiscal_year=fiscal_year)
    collected = 0.0
    deductible = 0.0
    for row in balance:
        code = row["account_code"]
        bal = row.get("balance", 0) or 0
        if code.startswith("443"):
            collected += -bal if bal < 0 else (row.get("credit", 0) - row.get("debit", 0))
        elif code.startswith("445"):
            deductible += bal if bal > 0 else (row.get("debit", 0) - row.get("credit", 0))
    due = round(collected - deductible, 2)
    return {
        "tva_collectee_443": round(collected, 2),
        "tva_recuperable_445": round(deductible, 2),
        "tva_due_nette": due,
        "position": "due" if due > 0 else ("credit" if due < 0 else "neutre"),
        "compte_cible": "444100" if due > 0 else "444900",
    }
