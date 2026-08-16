"""Jeux de démonstration — catalogue et chargeurs."""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, List

from sqlalchemy.orm import Session

from app import seed as seed_peya
from app.models import Client, Deal, Invoice, Project, Quote, StockItem, Training, Trainee

DatasetLoader = Callable[[Session], None]

DATASETS: List[dict] = [
    {
        "id": "peya_energy",
        "name": "Peya Company — Énergie & IRVE",
        "tagline": "Multi-activités · Togo",
        "description": "Clients publics et privés, projets TEGIS/IRVE, formations CCI, stock technique et comptabilité complète.",
        "icon": "⚡",
        "accent": "#2d8a45",
        "modules": ["CRM", "Projets", "Formations", "Stock", "Compta"],
        "highlights": ["8+ clients", "12+ factures", "12 articles", "Achats & compta auto"],
        "recommended": True,
    },
    {
        "id": "commerce_retail",
        "name": "Commerce & distribution",
        "tagline": "Boutique · gros-détail",
        "description": "PME commerciale à Lomé : clients particuliers et revendeurs, catalogue produits, facturation rapide.",
        "icon": "🛒",
        "accent": "#1d4ed8",
        "modules": ["Clients", "Devis", "Factures", "Stock"],
        "highlights": ["6 clients", "8 factures", "16 produits", "Trésorerie & achats"],
        "recommended": False,
    },
    {
        "id": "formation_cfa",
        "name": "Centre de formation",
        "tagline": "Qualiopi · OPCO",
        "description": "Organisme de formation professionnelle : sessions, stagiaires, devis intra-entreprise et suivi pédagogique.",
        "icon": "🎓",
        "accent": "#7c3aed",
        "modules": ["Formations", "Stagiaires", "Devis", "Clients"],
        "highlights": ["5 clients", "6 sessions", "15 stagiaires", "RH & calendrier"],
        "recommended": False,
    },
    {
        "id": "btp_immobilier",
        "name": "BTP & immobilier",
        "tagline": "Chantiers · fournisseurs",
        "description": "Promoteur et entreprise BTP : projets chantier, achats matériaux, sous-traitance et facturation acomptes.",
        "icon": "🏗️",
        "accent": "#c45a2a",
        "modules": ["Projets", "Achats", "Fournisseurs", "Budgets"],
        "highlights": ["5 clients", "6 chantiers", "8 fournisseurs", "Budgets & achats"],
        "recommended": False,
    },
    {
        "id": "minimal",
        "name": "Démarrage à blanc",
        "tagline": "Structure minimale",
        "description": "Plan comptable SYSCOHADA allégé et 2 clients fictifs — idéal pour saisir vos propres données.",
        "icon": "📋",
        "accent": "#64748b",
        "modules": ["Comptabilité", "Clients"],
        "highlights": ["SYSCOHADA complet", "2 clients", "Plan 1409 comptes", "Zéro facture"],
        "recommended": False,
    },
]

_LOADERS: Dict[str, DatasetLoader] = {}


def _register(dataset_id: str):
    def deco(fn: DatasetLoader):
        _LOADERS[dataset_id] = fn
        return fn
    return deco


def list_datasets() -> List[dict]:
    return DATASETS


def get_dataset(dataset_id: str) -> dict:
    for d in DATASETS:
        if d["id"] == dataset_id:
            return d
    raise ValueError(f"Jeu de démonstration inconnu : {dataset_id}")


def load_dataset(db: Session, dataset_id: str) -> dict:
    if dataset_id not in _LOADERS:
        raise ValueError(f"Jeu non implémenté : {dataset_id}")
    _LOADERS[dataset_id](db)
    meta = get_dataset(dataset_id)
    from app.demo_seed_common import finalize_demo_dataset
    if dataset_id == "minimal":
        stats = _minimal_stats(db)
    elif dataset_id == "peya_energy":
        stats = _collect_stats(db)
    else:
        stats = finalize_demo_dataset(db)
    return {"dataset": dataset_id, "name": meta["name"], **stats}


def _minimal_stats(db: Session) -> dict:
    from app.demo_seed_common import ensure_syscohada_chart
    ensure_syscohada_chart(db)
    return _collect_stats(db)


def _collect_stats(db: Session) -> dict:
    from app.models_erp import JournalEntry, Supplier, SupplierInvoice, Employee, BankAccount
    from app.models import StockMovement, Trainee, Deal
    from app.models_calendar import CalendarEvent
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
    }


@_register("peya_energy")
def _load_peya_energy(db: Session) -> None:
    seed_peya.run(db, force=True)  # inclut finalize_demo_dataset


@_register("commerce_retail")
def _load_commerce(db: Session) -> None:
    clients = []
    for row in [
        ("Boutique Étoile", "Commerce", "Détail", "M. Agbé", "Lomé"),
        ("Super Marché du Port", "Grande surface", "Gros", "Service achats", "Lomé"),
        ("Pharmacie Centrale", "Santé", "Détail", "Dr. Mensah", "Lomé"),
        ("Hôtel Palm Beach", "Hôtellerie", "CHR", "Réception", "Lomé"),
        ("Épicerie Kara", "Commerce", "Détail", "Mme Tchalla", "Kara"),
        ("Revendeur Atakpamé", "Distribution", "Gros", "M. Koudjo", "Atakpamé"),
    ]:
        c = Client(name=row[0], type=row[1], segment=row[2], contact=row[3], city=row[4], status="actif")
        db.add(c)
        clients.append(c)
    db.commit()
    for c in clients:
        db.refresh(c)

    for d in [
        (clients[0].id, "Commande récurrente produits frais", 8500, "qualified"),
        (clients[1].id, "Contrat approvisionnement trimestriel", 42000, "negotiation"),
        (clients[3].id, "Équipements restauration", 12800, "proposal"),
    ]:
        db.add(Deal(title=d[1], client_id=d[0], amount=d[2], stage=d[3], pole="Commerce", probability=50))
    db.commit()

    for q in [
        ("DEV-COM-001", clients[0].id, 8500, "envoyé", "Approvisionnement février"),
        ("DEV-COM-002", clients[1].id, 42000, "accepté", "Contrat Q1"),
        ("DEV-COM-003", clients[3].id, 12800, "brouillon", "Matériel cuisine"),
    ]:
        db.add(Quote(number=q[0], client_id=q[1], amount=q[2], status=q[3], title=q[4], date=date.today()))
    db.commit()

    for inv in [
        ("FAC-COM-001", clients[0].id, 8500, 8500, "payée"),
        ("FAC-COM-002", clients[1].id, 21000, 0, "envoyée"),
        ("FAC-COM-003", clients[4].id, 3200, 1600, "partielle"),
    ]:
        db.add(Invoice(
            number=inv[0], client_id=inv[1], amount=inv[2], paid=inv[3], status=inv[4],
            date=date.today(), due_date=date.today(),
        ))
    db.commit()

    for s in [
        ("RIZ-25KG", "Riz parfumé 25 kg", "Alimentaire", 120, 18500, 22000),
        ("HUILE-5L", "Huile végétale 5 L", "Alimentaire", 80, 4200, 5500),
        ("EAU-1.5L", "Eau minérale pack 12", "Boissons", 200, 1800, 2500),
        ("SAVON-BLK", "Savon de Marseille", "Hygiène", 150, 900, 1400),
        ("CAFE-500", "Café moulu 500 g", "Alimentaire", 45, 3200, 4500),
        ("LAIT-PWD", "Lait en poudre 400 g", "Alimentaire", 60, 2100, 2900),
        ("JUS-ORNG", "Jus d'orange 1 L", "Boissons", 90, 1100, 1600),
        ("PAIN-MIX", "Farine mixte 1 kg", "Alimentaire", 100, 650, 950),
        ("BISC-CHOC", "Biscuits chocolat", "Snacking", 70, 800, 1200),
        ("NETT-MULT", "Nettoyant multi-usages", "Entretien", 55, 1500, 2200),
        ("PAP-TOIL", "Papier toilette x12", "Hygiène", 40, 2800, 3800),
        ("CONF-MIX", "Confiserie assortie", "Snacking", 35, 1900, 2800),
    ]:
        db.add(StockItem(
            sku=s[0], name=s[1], category=s[2], quantity=s[3],
            unit_cost=s[4], unit_price=s[5], unit="unité", supplier="Grossiste Lomé",
        ))
    db.commit()

    for inv in [
        ("FAC-COM-004", clients[2].id, 15600, 15600, "payée"),
        ("FAC-COM-005", clients[3].id, 22400, 0, "envoyée"),
        ("FAC-COM-006", clients[5].id, 9800, 0, "en retard"),
        ("FAC-COM-007", clients[0].id, 41200, 20000, "envoyée"),
        ("FAC-COM-008", clients[1].id, 67500, 67500, "payée"),
    ]:
        db.add(Invoice(
            number=inv[0], client_id=inv[1], amount=inv[2], paid=inv[3], status=inv[4],
            date=date.today(), due_date=date.today(),
        ))
    db.commit()


@_register("formation_cfa")
def _load_formation(db: Session) -> None:
    clients = []
    for row in [
        ("CCI Togo", "Institution", "OPCO"),
        ("Banque Atlantique", "Entreprise", "Intra"),
        ("Mairie de Lomé", "Collectivité", "Public"),
        ("Oragroup", "Industrie", "Intra"),
        ("Startup Hub Lomé", "Incubateur", "Inter"),
    ]:
        c = Client(name=row[0], type=row[1], segment=row[2], status="actif", city="Lomé")
        db.add(c)
        clients.append(c)
    db.commit()
    for c in clients:
        db.refresh(c)

    trainings = []
    for t in [
        ("Excel avancé — gestionnaires", clients[0].id, 5, 950, "en cours"),
        ("Cybersécurité fondamentaux", clients[1].id, 3, 1200, "planifiée"),
        ("Management d'équipe", clients[2].id, 2, 1100, "planifiée"),
        ("Comptabilité SYSCOHADA", None, 4, 900, "ouverte"),
    ]:
        tr = Training(
            title=t[0], client_id=t[1], duration=t[2], daily_rate=t[3], status=t[4],
            start_date=date.today(), mode="intra" if t[1] else "inter", location="Lomé",
        )
        db.add(tr)
        trainings.append(tr)
    db.commit()

    db.add(Quote(number="DEV-FOR-001", client_id=clients[0].id, amount=4750, status="accepté", title="Excel avancé 5j", date=date.today()))
    db.add(Quote(number="DEV-FOR-002", client_id=clients[1].id, amount=3600, status="envoyé", title="Cybersécurité 3j", date=date.today()))
    db.commit()

    for inv in [
        ("FAC-FOR-001", clients[0].id, 4750, 4750, "payée"),
        ("FAC-FOR-002", clients[1].id, 3600, 0, "envoyée"),
        ("FAC-FOR-003", clients[3].id, 8800, 4400, "envoyée"),
        ("FAC-FOR-004", clients[2].id, 12500, 0, "en retard"),
    ]:
        db.add(Invoice(
            number=inv[0], client_id=inv[1], amount=inv[2], paid=inv[3], status=inv[4],
            date=date.today(), due_date=date.today(),
        ))
    for i in range(8):
        db.add(Trainee(
            training_id=trainings[i % len(trainings)].id,
            firstname=f"Stagiaire{i+1}", lastname="Demo",
            email=f"stagiaire{i+1}@demo.tg", company="Entreprise démo",
            attendance=80 + (i % 3) * 10, evaluation=12 + i % 5, certified=i % 2 == 0,
        ))
    db.commit()


@_register("btp_immobilier")
def _load_btp(db: Session) -> None:
    from app.models_erp import Budget, CostCenter, Supplier, SupplierInvoice

    clients = []
    for row in [
        ("Résidence Les Palmiers", "Promoteur", "Immobilier"),
        ("BTP Atlantique", "Entreprise", "Sous-traitance"),
        ("Mairie du Golfe", "Collectivité", "Public"),
        ("Investisseur privé Koffi", "Particulier", "Villa"),
        ("Coopérative Habitat+", "Coopérative", "Logement social"),
    ]:
        c = Client(name=row[0], type=row[1], segment=row[2], status="actif", city="Lomé")
        db.add(c)
        clients.append(c)
    db.commit()
    for c in clients:
        db.refresh(c)

    projects = []
    for p in [
        ("Villa 4 chambres — Baguida", clients[3].id, 85000, 35, "en cours"),
        ("Rénovation école primaire", clients[2].id, 120000, 10, "planifié"),
        ("Immeuble R+2 Tokoin", clients[0].id, 420000, 55, "en cours"),
        ("Lotissement 12 lots", clients[4].id, 280000, 20, "planifié"),
    ]:
        pr = Project(
            name=p[0], client_id=p[1], budget=p[2], progress=p[3], status=p[4],
            pole="BTP", start_date=date.today(),
        )
        db.add(pr)
        projects.append(pr)
    db.commit()

    for s in ["Cimencam Togo", "Fer à béton Lomé", "BTP Matériaux Kara", "Menuiserie Bois Tropiques"]:
        db.add(Supplier(name=s, city="Lomé", status="actif"))
    db.commit()

    suppliers = db.query(Supplier).all()
    db.add(SupplierInvoice(number="FF-BTP-001", supplier_id=suppliers[0].id, amount=1850000, status="validée", date=date.today()))
    db.add(SupplierInvoice(number="FF-BTP-002", supplier_id=suppliers[1].id, amount=920000, status="validée", date=date.today()))
    db.add(CostCenter(code="CH01", name="Chantier villa Baguida", type="coût"))
    db.add(Budget(year=date.today().year, name="Matériaux Q1", amount_planned=5000000, amount_actual=1200000, department="BTP"))
    db.commit()

    db.add(Quote(number="DEV-BTP-001", client_id=clients[3].id, amount=85000, status="accepté", title="Construction villa", date=date.today()))
    db.add(Invoice(number="FAC-BTP-001", client_id=clients[3].id, amount=25500, paid=25500, status="payée", date=date.today(), due_date=date.today(), project_id=projects[0].id))
    db.commit()


@_register("minimal")
def _load_minimal(db: Session) -> None:
    from app.demo_seed_common import ensure_syscohada_chart
    ensure_syscohada_chart(db)
    db.add(Client(name="Client démo A", type="Entreprise", status="actif", city="Lomé", segment="Services"))
    db.add(Client(name="Client démo B", type="Particulier", status="prospect", city="Kara", segment="Résidentiel"))
    db.commit()


