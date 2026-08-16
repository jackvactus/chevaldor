"""Audit de conformité SYSCOHADA — écarts et recommandations."""

from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Account, Invoice, StockItem, DocumentLine
from app.models_erp import JournalEntry, SupplierInvoice
from app.models_accounting import (
    AccountingTransaction, TaxRate, VatPeriod, SupplierInvoiceLine,
    StockCategory, PrepaidExpense, PaymentRecord,
)
from app.models_prefs import SystemSettings
from app.syscohada.chart import SYSCOHADA_CHART


def run_compliance_audit(db: Session) -> dict:
    """Retourne un score et la liste des écarts par domaine."""
    checks: list[dict] = []
    score = 100

    def add(domain: str, level: str, message: str, points: int = 0):
        nonlocal score
        if level in ("error", "warn") and points:
            score = max(0, score - points)
        checks.append({"domain": domain, "level": level, "message": message})

    # Plan comptable
    target = len(SYSCOHADA_CHART)
    acc_count = db.query(Account).count()
    classes = {a.code[0] for a in db.query(Account.code).all() if a.code}
    if acc_count < target:
        add(
            "plan",
            "error" if acc_count < 100 else "warn",
            f"Plan comptable incomplet ({acc_count}/{target} comptes officiels)",
            15 if acc_count < 100 else 8,
        )
    else:
        add("plan", "ok", f"Plan SYSCOHADA complet ({acc_count} comptes, classes 1–9)")

    missing_classes = set("123456789") - classes
    if missing_classes:
        add("plan", "warn", f"Classes absentes : {', '.join(sorted(missing_classes))}", 3)

    # Moteur auto
    posted = db.query(AccountingTransaction).filter(AccountingTransaction.status == "posted").count()
    errors = db.query(AccountingTransaction).filter(AccountingTransaction.status == "error").count()
    if posted == 0:
        add("engine", "warn", "Aucune écriture automatique générée — validez des factures", 10)
    else:
        add("engine", "ok", f"{posted} opération(s) comptabilisée(s) automatiquement")
    if errors:
        add("engine", "error", f"{errors} échec(s) de comptabilisation — voir accounting_transactions", 10)

    inv_total = db.query(Invoice).filter(Invoice.doc_type != "credit_note").count()
    inv_posted = db.query(Invoice).filter(Invoice.journal_entry_id.isnot(None)).count()
    if inv_total and inv_posted < inv_total * 0.5:
        add("engine", "warn", f"Factures clients : {inv_posted}/{inv_total} avec écriture", 5)

    sf_total = db.query(SupplierInvoice).count()
    sf_lines = db.query(SupplierInvoiceLine).count()
    if sf_total and sf_lines == 0:
        add("achats", "warn", "Factures fournisseur sans lignes typées — utilisez supplier-invoices/lines", 8)

    # Produits typés
    items = db.query(StockItem).count()
    typed = db.query(StockItem).filter(StockItem.product_accounting_type.isnot(None)).count()
    if items and typed < items:
        add("produits", "warn", f"{items - typed} article(s) sans product_accounting_type", 5)

    with_accounts = db.query(StockItem).filter(
        (StockItem.purchase_account != "") | (StockItem.purchase_account_id.isnot(None))
    ).count()
    if items and with_accounts < items * 0.3:
        add("produits", "warn", "Peu d'articles avec comptes achat/vente/stock définis", 5)

    # TVA
    if db.query(TaxRate).count() == 0:
        add("tva", "warn", "Aucun taux TVA en base — importez le plan SYSCOHADA", 5)
    open_periods = db.query(VatPeriod).filter(VatPeriod.status == "open").count()
    add("tva", "info", f"{open_periods} période(s) TVA ouverte(s)")

    # Stocks OHADA
    if db.query(StockCategory).count() < 4:
        add("stocks", "warn", "Catégories stock OHADA (31-37) non initialisées", 5)
    else:
        add("stocks", "ok", "Catégories stock OHADA présentes")

    sys = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    inv_method = getattr(sys, "inventory_method", "PERMANENT") if sys else "PERMANENT"
    add("stocks", "info", f"Méthode inventaire : {inv_method}")

    # Paiements
    payments = db.query(PaymentRecord).count()
    if payments == 0:
        add("tresorerie", "info", "Encaissements via POST /invoices/{id}/payment pour écritures BQ/CA")

    # CCA
    prepaid = db.query(PrepaidExpense).filter(PrepaidExpense.status == "active").count()
    if prepaid:
        add("cca", "info", f"{prepaid} charge(s) constatée(s) d'avance active(s)")

    validated_entries = db.query(JournalEntry).filter(JournalEntry.status == "validée").count()
    if validated_entries == 0:
        add("journal", "warn", "Journal vide — le moteur alimentera les écritures à la validation", 5)

    doc_lines_typed = db.query(DocumentLine).filter(DocumentLine.product_type != "SERVICE").count()
    if db.query(DocumentLine).count() and doc_lines_typed == 0:
        add("facturation", "info", "Lignes facture : renseignez product_type par ligne")

    level1 = all(c["level"] != "error" for c in checks if c["domain"] in ("plan", "engine", "tva"))
    return {
        "framework": "SYSCOHADA",
        "score": score,
        "level1_ready": level1,
        "checks": checks,
        "summary": {
            "accounts": acc_count,
            "auto_posted": posted,
            "auto_errors": errors,
            "invoices_with_entry": inv_posted,
            "supplier_lines": sf_lines,
            "inventory_method": inv_method,
        },
    }
