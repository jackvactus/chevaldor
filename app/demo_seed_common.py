"""Helpers partagés — jeux de démonstration volumineux."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import (
    Client, Deal, DocumentLine, Invoice, Project, Quote, StockItem, StockMovement,
    Training, Trainee, Transaction,
)
from app.models_calendar import CalendarEvent
from app.models_erp import (
    BankAccount, Budget, CostCenter, Employee, LeaveRequest,
    Supplier, SupplierInvoice, TreasuryMovement,
)
from app.models_accounting import SupplierInvoiceLine
from app.models_stock import Warehouse
from app.services.stock_service import ensure_default_warehouses


def ensure_syscohada_chart(db: Session) -> None:
    from app.syscohada.service import import_syscohada_chart
    import_syscohada_chart(db, force=False)


def seed_document_lines_for_invoices(db: Session) -> int:
    """Ajoute des lignes typées sur les factures sans lignes."""
    count = 0
    for inv in db.query(Invoice).all():
        if db.query(DocumentLine).filter(DocumentLine.invoice_id == inv.id).count():
            continue
        amt = float(inv.amount or 0) / 1.18
        db.add(DocumentLine(
            invoice_id=inv.id,
            description=f"Prestation / fourniture — {inv.number}",
            quantity=1,
            unit_price=round(amt * 0.7, 2),
            vat_rate=18,
            product_type="SERVICE",
            position=0,
        ))
        db.add(DocumentLine(
            invoice_id=inv.id,
            description="Frais techniques & déplacement",
            quantity=1,
            unit_price=round(amt * 0.3, 2),
            vat_rate=18,
            product_type="SERVICE",
            position=1,
        ))
        count += 1
    db.commit()
    return count


def seed_supplier_ecosystem(db: Session, suppliers_spec: Iterable[tuple] | None = None) -> None:
    """Fournisseurs, factures achat et lignes SYSCOHADA."""
    if db.query(Supplier).count() == 0:
        rows = suppliers_spec or [
            ("FOU-REXEL", "Rexel Togo", "Lomé", 30),
            ("FOU-SCHN", "Schneider Electric", "Lomé", 45),
            ("FOU-CIT", "Citelum Afrique", "Lomé", 60),
            ("FOU-RS", "RS Components", "Paris", 30),
            ("FOU-BTP", "Matériaux BTP Lomé", "Lomé", 30),
            ("FOU-TRANS", "Trans Afrique Logistique", "Lomé", 15),
            ("FOU-IT", "Informatique Pro Togo", "Lomé", 30),
            ("FOU-ASS", "Assurances UEMOA", "Lomé", 30),
        ]
        for code, name, city, delay in rows:
            db.add(Supplier(
                code=code, name=name, city=city,
                payment_terms=delay, status="actif", email=f"contact@{code.lower()}.tg",
            ))
        db.commit()

    suppliers = db.query(Supplier).all()
    if not suppliers or db.query(SupplierInvoice).count() >= 6:
        return

    specs = [
        ("FF-2026-001", 0, "validée", 425000, [
            ("Câbles et armoires", "MERCHANDISE", 10, 25000),
            ("Transport chantier", "transport", 1, 15000),
        ]),
        ("FF-2026-002", 1, "validée", 890000, [
            ("Bornes IRVE Schneider", "ASSET", 2, 350000),
            ("Installation", "SERVICE", 1, 120000),
        ]),
        ("FF-2026-003", 2, "payée", 156000, [
            ("Nœuds télégestion", "MERCHANDISE", 4, 32000),
        ]),
        ("FF-2026-004", 4, "brouillon", 78000, [
            ("Ciment & fer", "RAW_MATERIAL", 50, 1200),
        ]),
        ("FF-2026-005", 5, "validée", 45000, [
            ("Livraison express Lomé-Kara", "transport", 1, 38000),
        ]),
        ("FF-2026-006", 6, "en retard", 125000, [
            ("Serveur & licences", "NON_STOCK_SUPPLY", 1, 105000),
        ]),
    ]
    today = date.today()
    for num, sup_idx, status, total_hint, lines in specs:
        if sup_idx >= len(suppliers):
            continue
        if db.query(SupplierInvoice).filter(SupplierInvoice.number == num).first():
            continue
        inv = SupplierInvoice(
            number=num,
            supplier_id=suppliers[sup_idx].id,
            date=today - timedelta(days=sup_idx * 7 + 3),
            amount=0,
            paid=total_hint if status == "payée" else 0,
            status=status,
        )
        db.add(inv)
        db.flush()
        total = 0.0
        for i, (desc, ptype, qty, pu) in enumerate(lines):
            kind = "product" if ptype not in ("transport", "customs", "insurance") else ptype.lower()
            ht = qty * pu
            tva = ht * 0.18
            total += ht + tva
            db.add(SupplierInvoiceLine(
                supplier_invoice_id=inv.id,
                description=desc,
                quantity=qty,
                unit_price=pu,
                vat_rate=18,
                product_type=ptype.upper() if kind == "product" else "MERCHANDISE",
                line_kind=kind,
                position=i,
            ))
        inv.amount = round(total, 2)
    db.commit()


def seed_finance_stack(db: Session) -> None:
    """Banques, trésorerie, RH, analytique."""
    if not db.query(BankAccount).count():
        db.add(BankAccount(name="Compte principal Ecobank", bank_name="Ecobank", balance=4850000, currency="XOF"))
        db.add(BankAccount(name="Compte projet BOA", bank_name="BOA Togo", balance=1250000, currency="XOF"))
        db.add(BankAccount(name="Caisse siège", bank_name="Caisse", balance=320000, currency="XOF"))
        db.commit()

    banks = db.query(BankAccount).all()
    if banks and db.query(TreasuryMovement).count() < 8:
        moves = [
            ("banque_entree", banks[0].id, 1890000, "Encaissement F2026-001"),
            ("banque_entree", banks[0].id, 1440000, "Encaissement F2026-003"),
            ("banque_sortie", banks[0].id, 425000, "Paiement Rexel FF-2026-001"),
            ("banque_sortie", banks[0].id, 890000, "Paiement Schneider"),
            ("caisse_entree", banks[2].id if len(banks) > 2 else banks[0].id, 85000, "Espèces formation"),
            ("caisse_sortie", banks[2].id if len(banks) > 2 else banks[0].id, 12000, "Frais déplacement"),
            ("banque_entree", banks[1].id if len(banks) > 1 else banks[0].id, 625000, "Acompte projet"),
            ("banque_sortie", banks[0].id, 156000, "TVA & charges sociales"),
        ]
        for kind, bid, amt, label in moves:
            db.add(TreasuryMovement(
                bank_account_id=bid, type=kind, amount=amt, label=label,
                date=date.today() - timedelta(days=5), reference=label[:20],
            ))
        db.commit()

    if not db.query(Employee).count():
        emps = [
            ("EMP-01", "Kossi", "Mensah", "Directeur technique", 850000, "Direction"),
            ("EMP-02", "Afi", "Tchalla", "Commerciale", 420000, "Commercial"),
            ("EMP-03", "Yao", "Koffi", "Technicien IRVE", 380000, "Technique"),
            ("EMP-04", "Efua", "Agbeko", "Formatrice", 450000, "Formation"),
            ("EMP-05", "Komlan", "Dossou", "Comptable", 520000, "Finance"),
            ("EMP-06", "Abla", "Soglo", "Assistante RH", 310000, "RH"),
        ]
        for mat, fn, ln, role, sal, dept in emps:
            db.add(Employee(
                matricule=mat, firstname=fn, lastname=ln, position=role,
                department=dept, salary_base=sal, hire_date=date(2024, 1, 15), status="actif",
            ))
        db.commit()

    emps = db.query(Employee).all()
    if emps and not db.query(LeaveRequest).count():
        db.add(LeaveRequest(employee_id=emps[2].id, start_date=date.today() + timedelta(days=14),
                             end_date=date.today() + timedelta(days=18), type="congé", status="en attente"))
        db.add(LeaveRequest(employee_id=emps[3].id, start_date=date.today() - timedelta(days=30),
                             end_date=date.today() - timedelta(days=25), type="congé", status="approuvé"))
        db.commit()

    if not db.query(CostCenter).count():
        db.add(CostCenter(code="CC-ADM", name="Administration", type="coût", budget=1200000))
        db.add(CostCenter(code="CC-PROJ", name="Projets & installations", type="coût", budget=8500000))
        db.add(CostCenter(code="CC-FORM", name="Formation", type="profit", budget=2400000))
        db.commit()

    yr = date.today().year
    if db.query(Budget).filter(Budget.year == yr).count() < 3:
        db.add(Budget(year=yr, name="Matériel & stock", amount_planned=3500000, amount_actual=890000, department="Achats"))
        db.add(Budget(year=yr, name="Charges personnel", amount_planned=4200000, amount_actual=2100000, department="RH"))
        db.add(Budget(year=yr, name="Commercial & marketing", amount_planned=800000, amount_actual=245000, department="Commercial"))
        db.commit()


def seed_calendar_events(db: Session) -> None:
    if db.query(CalendarEvent).count() >= 10:
        return
    invs = db.query(Invoice).filter(Invoice.status.in_(("envoyée", "en retard"))).limit(3).all()
    base = date.today()
    events = [
        ("Réunion client Mairie Lomé", "meeting", "ventes", 0, "Mairie de Lomé"),
        ("Livraison matériel IRVE", "delivery", "stock", 3, ""),
        ("Session formation J3", "training", "rh", 5, "CCI / CCIT"),
        ("Point trésorerie hebdo", "meeting", "compta", 7, ""),
        ("Visite chantier BTP", "site", "direction", 10, "BTP Atlantique"),
    ]
    for title, kind, cat, offset, desc in events:
        db.add(CalendarEvent(
            title=title, event_type=kind, category=cat,
            start_date=base + timedelta(days=offset),
            end_date=base + timedelta(days=offset), status="planifié",
            description=desc,
        ))
    for inv in invs:
        db.add(CalendarEvent(
            title=f"Relance {inv.number}", event_type="reminder", category="compta",
            start_date=inv.due_date or base, end_date=inv.due_date or base,
            status="planifié", description=inv.number or "",
        ))
    db.commit()


def seed_stock_movements(db: Session) -> None:
    ensure_default_warehouses(db)
    items = db.query(StockItem).limit(6).all()
    if not items or db.query(StockMovement).count() >= 10:
        return
    wh = db.query(Warehouse).first()
    for i, item in enumerate(items):
        db.add(StockMovement(
            item_id=item.id, type="entrée" if i % 2 == 0 else "sortie",
            quantity=2 + i, reason="achat" if i % 2 == 0 else "projet",
            date=date.today() - timedelta(days=i + 1),
            warehouse_id=wh.id if wh else None,
        ))
    db.commit()


def enrich_stock_accounting(db: Session) -> None:
    types = ["MERCHANDISE", "ASSET", "SUPPLY", "RAW_MATERIAL", "SERVICE"]
    for i, item in enumerate(db.query(StockItem).all()):
        if not getattr(item, "product_accounting_type", None) or item.product_accounting_type == "MERCHANDISE":
            item.product_accounting_type = types[i % len(types)]
    db.commit()


def post_demo_accounting(db: Session) -> dict:
    """Génère écritures pour factures / achats validés."""
    from app.services.accounting_hooks import dispatch_invoice_posting, dispatch_supplier_invoice_posting

    inv_ok = sf_ok = 0
    for inv in db.query(Invoice).filter(Invoice.status.in_(("envoyée", "payée", "en retard"))).all():
        try:
            r = dispatch_invoice_posting(db, inv, force=True)
            if r.get("ok"):
                inv_ok += 1
        except Exception:
            pass
    for sf in db.query(SupplierInvoice).filter(SupplierInvoice.status.in_(("validée", "payée", "en retard"))).all():
        try:
            r = dispatch_supplier_invoice_posting(db, sf, force=True)
            if r.get("ok"):
                sf_ok += 1
        except Exception:
            pass
    return {"invoices_posted": inv_ok, "purchases_posted": sf_ok}


def seed_legacy_transactions(db: Session, count: int = 15) -> None:
    """Quelques transactions historiques (repli si pas d'écritures journal)."""
    if db.query(Transaction).count() >= count:
        return
    today = date.today()
    samples = [
        ("produit", "706100", "Prestations consulting", 450000),
        ("produit", "701100", "Vente marchandises", 280000),
        ("charge", "601100", "Achats marchandises", 190000),
        ("charge", "622100", "Honoraires", 75000),
        ("charge", "641100", "Salaires", 520000),
        ("charge", "626100", "Télécom", 45000),
    ]
    for i, (typ, acc, label, amt) in enumerate(samples):
        db.add(Transaction(
            date=today - timedelta(days=30 - i * 3),
            type=typ, label=label, amount=amt, account_code=acc, category=label.split()[0],
        ))
    db.commit()


def seed_finance_advanced(db: Session) -> None:
    """Immobilisations, paie, consignes, subventions, acomptes IS."""
    from app.models_syscohada import FixedAsset, AssetCategory
    from app.models_accounting import Consignment, Grant, CorporateTaxInstallment
    from app.services.fixed_asset_service import create_fixed_asset
    from app.services.payroll_service import generate_payroll_run

    if not db.query(AssetCategory).count():
        ensure_syscohada_chart(db)

    cats = {c.code: c for c in db.query(AssetCategory).all()}
    if not db.query(FixedAsset).count():
        specs = [
            ("IMMO-01", "Véhicule utilitaire Toyota", "MAT-TRANS", 12500000, 2500000),
            ("IMMO-02", "Matériel IRVE Schneider", "MAT-BUREAU", 8900000, 890000),
            ("IMMO-03", "Serveur & licences ERP", "MAT-INFO", 3200000, 320000),
            ("IMMO-04", "Mobilier bureau Lomé", "MAT-BUREAU", 1850000, 185000),
        ]
        today = date.today()
        for code, label, cat_code, cost, residual in specs:
            cat = cats.get(cat_code) or next(iter(cats.values()), None)
            create_fixed_asset(db, {
                "code": code,
                "label": label,
                "category_id": cat.id if cat else None,
                "acquisition_cost": cost,
                "residual_value": residual,
                "acquisition_date": today - timedelta(days=400),
                "service_date": today - timedelta(days=380),
            })

    if not db.query(Consignment).count():
        db.add(Consignment(code="CONS-BIDON", label="Bidons gasoil 20L", unit_value=2500, qty_out=120, qty_returned=45))
        db.add(Consignment(code="CONS-PALETTE", label="Palettes bois", unit_value=8500, qty_out=80, qty_returned=30))
        db.commit()

    if not db.query(Grant).count():
        db.add(Grant(code="SUB-CEET", label="Subvention branchement CEET", grant_type="investment", amount=15000000, received=7500000))
        db.add(Grant(code="SUB-FORM", label="Aide formation ANPE", grant_type="exploitation", amount=2500000, received=2500000))
        db.commit()

    y, m = date.today().year, date.today().month
    from app.models_accounting import PayrollRun
    if not db.query(PayrollRun).count() and db.query(Employee).count():
        generate_payroll_run(db, y, m)

    if not db.query(CorporateTaxInstallment).count():
        for q, amt in enumerate([450000, 450000, 450000, 450000], 1):
            db.add(CorporateTaxInstallment(fiscal_year=y, period=q, amount=amt, status="planned" if q > 1 else "paid"))
        db.commit()


def finalize_demo_dataset(db: Session) -> dict:
    """Couche commune après chargement d'un jeu."""
    ensure_syscohada_chart(db)
    from app.services.auxiliary_account_service import backfill_auxiliary_accounts
    backfill_auxiliary_accounts(db)
    seed_document_lines_for_invoices(db)
    seed_supplier_ecosystem(db)
    seed_finance_stack(db)
    seed_finance_advanced(db)
    seed_calendar_events(db)
    seed_stock_movements(db)
    enrich_stock_accounting(db)
    accounting = post_demo_accounting(db)
    seed_legacy_transactions(db)

    from app.models_erp import JournalEntry
    return {
        "clients": db.query(Client).count(),
        "deals": db.query(Deal).count(),
        "quotes": db.query(Quote).count(),
        "invoices": db.query(Invoice).count(),
        "projects": db.query(Project).count(),
        "trainings": db.query(Training).count(),
        "trainees": db.query(Trainee).count(),
        "stock_items": db.query(StockItem).count(),
        "stock_movements": db.query(StockMovement).count(),
        "suppliers": db.query(Supplier).count(),
        "supplier_invoices": db.query(SupplierInvoice).count(),
        "employees": db.query(Employee).count(),
        "bank_accounts": db.query(BankAccount).count(),
        "journal_entries": db.query(JournalEntry).count(),
        "calendar_events": db.query(CalendarEvent).count(),
        **accounting,
    }
