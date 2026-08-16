"""Données de démonstration — Peya Company Togo 2026"""
from datetime import date
from sqlalchemy.orm import Session
from app.models import (
    Client, Deal, Quote, Invoice, Project, Task,
    Training, Trainee, StockItem,
)


def run(db: Session, *, force: bool = False):
    """Charge les données de démo Peya Company. Idempotent sauf si force=True."""
    if not force and db.query(Client).count() > 0:
        return

    # --------- CLIENTS ---------
    clients_data = [
        dict(name="Mairie de Lomé", type="Collectivité", segment="Public",
             contact="Service Énergie", email="energie@mairie-lome.tg", phone="+228 22 21 39 00",
             city="Lomé", status="actif", notes="Éclairage public & efficacité énergétique"),
        dict(name="CCIT (Chambre de Commerce Togo)", type="Institution", segment="Public",
             contact="Pôle Formation", email="formation@ccit.tg", phone="+228 22 21 56 00",
             city="Lomé", status="actif", notes="Partenaire formation continue"),
        dict(name="CEET (Compagnie Énergie Électrique)", type="Entreprise", segment="Industrie",
             contact="Direction technique", email="contact@ceet.tg", phone="+228 22 21 70 00",
             city="Lomé", status="prospect", notes="Audit réseau & IRVE"),
        dict(name="BTP Atlantique Togo", type="Entreprise", segment="BTP/Immobilier",
             contact="Mme Mensah", email="contact@btp-atlantique.tg", phone="+228 90 12 34 56",
             city="Lomé", status="actif", notes="Résidences & bornes IRVE"),
        dict(name="M. Koffi (particulier)", type="Particulier", segment="Résidentiel",
             contact="M. Koffi", email="koffi.residence@gmail.com", phone="+228 99 88 77 66",
             city="Lomé", status="actif", notes="Domotique villa Baguida"),
        dict(name="Préfecture du Golfe", type="Collectivité", segment="Public",
             contact="DGS", email="contact@prefecture-golfe.tg", phone="+228 22 21 10 00",
             city="Lomé", status="prospect", notes="Marché transition énergétique"),
        dict(name="Oragroup Togo", type="Entreprise", segment="Industrie",
             contact="Directeur opérationnel", email="contact@oragroup.tg", phone="+228 22 25 00 00",
             city="Lomé", status="actif", notes="Co-traitance installations"),
        dict(name="Mairie de Kara", type="Collectivité", segment="Public",
             contact="Service Technique", email="technique@mairie-kara.tg", phone="+228 26 60 00 00",
             city="Kara", status="prospect", notes="Éclairage LED & télégestion"),
    ]
    clients = []
    for c in clients_data:
        obj = Client(**c)
        db.add(obj); clients.append(obj)
    db.commit()
    for c in clients: db.refresh(c)

    # --------- DEALS ---------
    deals_data = [
        dict(title="Extension TEGIS — secteur Charvein", client_id=clients[0].id, stage="negotiation",
             amount=48000, probability=60, close_date=date(2026, 4, 30), pole="Consulting"),
        dict(title="Cycle formation Réseaux & Cybersécurité", client_id=clients[1].id, stage="qualified",
             amount=12500, probability=50, close_date=date(2026, 3, 15), pole="Formation"),
        dict(title="Audit énergétique site Kourou", client_id=clients[2].id, stage="proposal",
             amount=5500, probability=70, close_date=date(2026, 2, 28), pole="Consulting"),
        dict(title="Installation 6 bornes IRVE — résidence Néréide", client_id=clients[3].id, stage="won",
             amount=18900, probability=100, close_date=date(2026, 1, 20), pole="Installations"),
        dict(title="Domotique villa — Home Assistant + KNX", client_id=clients[4].id, stage="lead",
             amount=8200, probability=30, close_date=date(2026, 5, 10), pole="Installations"),
        dict(title="Dossier FEDER smart-lighting", client_id=clients[5].id, stage="lead",
             amount=85000, probability=25, close_date=date(2026, 9, 30), pole="Consulting"),
        dict(title="Co-traitance marché public éclairage Macouria", client_id=clients[6].id, stage="qualified",
             amount=22000, probability=45, close_date=date(2026, 4, 15), pole="Installations"),
        dict(title="Étude éclairage intelligent ville", client_id=clients[7].id, stage="proposal",
             amount=14500, probability=55, close_date=date(2026, 3, 30), pole="Consulting"),
    ]
    for d in deals_data:
        db.add(Deal(**d))
    db.commit()

    # --------- QUOTES ---------
    quotes_data = [
        dict(number="Q2026-001", client_id=clients[0].id, date=date(2026,1,12), valid_until=date(2026,2,12),
             amount=48000, status="envoyé", title="Extension TEGIS Charvein"),
        dict(number="Q2026-002", client_id=clients[1].id, date=date(2026,1,15), valid_until=date(2026,2,15),
             amount=12500, status="accepté", title="Formation cybersécurité 5j"),
        dict(number="Q2026-003", client_id=clients[3].id, date=date(2026,1,8), valid_until=date(2026,2,8),
             amount=18900, status="accepté", title="6 bornes IRVE 22kVA Schneider"),
        dict(number="Q2026-004", client_id=clients[2].id, date=date(2026,1,22), valid_until=date(2026,2,22),
             amount=5500, status="envoyé", title="Audit énergétique Kourou"),
        dict(number="Q2026-005", client_id=clients[4].id, date=date(2026,2,1), valid_until=date(2026,3,1),
             amount=8200, status="brouillon", title="Domotique villa Adjovi"),
        dict(number="Q2026-006", client_id=clients[7].id, date=date(2026,2,5), valid_until=date(2026,3,5),
             amount=14500, status="envoyé", title="Étude éclairage Kourou"),
    ]
    for q in quotes_data:
        db.add(Quote(**q))
    db.commit()

    # --------- PROJECTS ---------
    projects_data = [
        dict(name="TEGIS Charvein — Phase préparatoire", client_id=clients[0].id, pole="Consulting",
             status="en cours", progress=35, budget=48000, billed=14400,
             start_date=date(2026,1,15), end_date=date(2026,5,30),
             description="Étude et déploiement extension TEGIS sur le secteur Charvein"),
        dict(name="IRVE Néréide — 6 bornes 22kVA", client_id=clients[3].id, pole="Installations",
             status="terminé", progress=100, budget=18900, billed=18900,
             start_date=date(2026,1,10), end_date=date(2026,1,25),
             description="Installation et mise en service de 6 bornes Schneider 22kVA avec cartes RFID"),
        dict(name="Formation Réseaux CCI — Session 1", client_id=clients[1].id, pole="Formation",
             status="en cours", progress=60, budget=12500, billed=12500,
             start_date=date(2026,2,15), end_date=date(2026,2,19),
             description="Module Réseaux & Cybersécurité Niveau 2 — 5 jours intra"),
        dict(name="Étude domotique villa Rémire", client_id=clients[4].id, pole="Consulting",
             status="planifié", progress=0, budget=1500, billed=0,
             start_date=date(2026,3,1), end_date=date(2026,3,15),
             description="Cahier des charges domotique Home Assistant + intégration KNX"),
        dict(name="Audit énergie EDF site Kourou", client_id=clients[2].id, pole="Consulting",
             status="planifié", progress=0, budget=5500, billed=0,
             start_date=date(2026,3,10), end_date=date(2026,4,10),
             description="Diagnostic consommations + préconisations ENR + dossier CEE"),
    ]
    projects = []
    for p in projects_data:
        obj = Project(**p)
        db.add(obj); projects.append(obj)
    db.commit()
    for p in projects: db.refresh(p)

    # --------- TASKS ---------
    tasks_data = [
        dict(project_id=projects[0].id, label="Visite site et relevés terrain", done=True, date=date(2026,1,18)),
        dict(project_id=projects[0].id, label="Spécifications techniques TEGIS", done=True, date=date(2026,2,5)),
        dict(project_id=projects[0].id, label="Chiffrage matériel (Schneider, Citelum)", done=False, date=date(2026,2,25)),
        dict(project_id=projects[0].id, label="Validation cahier des charges client", done=False, date=date(2026,3,10)),
        dict(project_id=projects[0].id, label="Lancement consultation fournisseurs", done=False, date=date(2026,3,20)),
        dict(project_id=projects[2].id, label="Préparation supports module 1-2", done=True, date=date(2026,1,28)),
        dict(project_id=projects[2].id, label="Animation jours 1-2 (réseaux)", done=True, date=date(2026,2,15)),
        dict(project_id=projects[2].id, label="Animation jours 3-5 (cybersécurité)", done=False, date=date(2026,2,18)),
        dict(project_id=projects[2].id, label="Évaluation finale + attestations", done=False, date=date(2026,2,19)),
        dict(project_id=projects[1].id, label="Réception matériel Schneider", done=True, date=date(2026,1,10)),
        dict(project_id=projects[1].id, label="Pose et raccordement 6 bornes", done=True, date=date(2026,1,20)),
        dict(project_id=projects[1].id, label="PV de réception et facturation", done=True, date=date(2026,1,25)),
    ]
    for t in tasks_data:
        db.add(Task(**t))
    db.commit()

    # --------- INVOICES ---------
    invoices_data = [
        dict(number="F2026-001", client_id=clients[3].id, project_id=projects[1].id,
             date=date(2026,1,25), due_date=date(2026,2,24), amount=18900, paid=18900, status="payée"),
        dict(number="F2026-002", client_id=clients[1].id, project_id=projects[2].id,
             date=date(2026,2,1), due_date=date(2026,3,3), amount=6250, paid=0, status="envoyée"),
        dict(number="F2026-003", client_id=clients[0].id, project_id=projects[0].id,
             date=date(2026,2,10), due_date=date(2026,3,12), amount=14400, paid=14400, status="payée"),
        dict(number="F2026-004", client_id=clients[1].id, project_id=projects[2].id,
             date=date(2026,2,20), due_date=date(2026,3,22), amount=6250, paid=0, status="en retard"),
    ]
    for i in invoices_data:
        db.add(Invoice(**i))
    db.commit()

    # --------- TRAININGS ---------
    trainings_data = [
        dict(title="Réseaux & Cybersécurité Niv. 2", client_id=clients[1].id,
             start_date=date(2026,2,15), end_date=date(2026,2,19), duration=5, daily_rate=1100,
             location="CCI Lomé", mode="intra", status="en cours", qualiopi=False,
             funder="Client direct", notes="1ère session — capitaliser pour Qualiopi"),
        dict(title="Domotique KNX & Home Assistant", client_id=None,
             start_date=date(2026,4,5), end_date=date(2026,4,7), duration=3, daily_rate=950,
             location="Coworking Lomé", mode="inter", status="planifiée", qualiopi=False,
             funder="OPCO", notes="Min. 4 participants pour ouverture"),
        dict(title="Éclairage public intelligent & TEGIS", client_id=clients[7].id,
             start_date=date(2026,5,12), end_date=date(2026,5,13), duration=2, daily_rate=950,
             location="Mairie Kourou", mode="intra", status="planifiée", qualiopi=False,
             funder="Client direct", notes="Pour agents techniques municipaux"),
    ]
    trainings = []
    for t in trainings_data:
        obj = Training(**t)
        db.add(obj); trainings.append(obj)
    db.commit()
    for t in trainings: db.refresh(t)

    # --------- TRAINEES ---------
    trainees_data = [
        dict(training_id=trainings[0].id, firstname="Marc", lastname="Dupont",
             email="m.dupont@cci-guyane.fr", company="CCI Togo", attendance=100, evaluation=15, certified=True),
        dict(training_id=trainings[0].id, firstname="Sarah", lastname="Aboubacar",
             email="s.aboubacar@cci-guyane.fr", company="CCI Togo", attendance=100, evaluation=17, certified=True),
        dict(training_id=trainings[0].id, firstname="Jean-Luc", lastname="Beaupré",
             email="jl.beaupre@cci-guyane.fr", company="CCI Togo", attendance=80, evaluation=12, certified=False),
        dict(training_id=trainings[0].id, firstname="Aïcha", lastname="Mendes",
             email="a.mendes@cci-guyane.fr", company="CCI Togo", attendance=100, evaluation=16, certified=True),
    ]
    for t in trainees_data:
        db.add(Trainee(**t))
    db.commit()

    # --------- STOCK ---------
    stock_data = [
        dict(sku="IRVE-SCH22", name="Borne IRVE Schneider EVlink 22kVA", category="IRVE",
             unit="unité", quantity=2, min_quantity=1, unit_cost=1850, unit_price=2800,
             supplier="Rexel Togo", location="Dépôt Lomé"),
        dict(sku="RFID-CARD", name="Carte RFID Mifare (lot 10)", category="IRVE",
             unit="lot", quantity=5, min_quantity=2, unit_cost=45, unit_price=85,
             supplier="Rexel Togo", location="Dépôt Lomé"),
        dict(sku="LED-50W", name="Luminaire LED routier 50W", category="Éclairage",
             unit="unité", quantity=15, min_quantity=10, unit_cost=180, unit_price=320,
             supplier="Philips Lighting", location="Dépôt Lomé"),
        dict(sku="TEGIS-NODE", name="Nœud de télégestion TEGIS", category="TEGIS",
             unit="unité", quantity=8, min_quantity=5, unit_cost=420, unit_price=750,
             supplier="Citelum", location="Dépôt Lomé"),
        dict(sku="CABLE-3G25", name="Câble U-1000 R2V 3G2.5 (m)", category="Câblage",
             unit="m", quantity=250, min_quantity=100, unit_cost=2.8, unit_price=5.5,
             supplier="Rexel Togo", location="Dépôt Lomé"),
        dict(sku="ARM-MOD12", name="Armoire électrique modulaire 12 modules", category="Tableautique",
             unit="unité", quantity=3, min_quantity=2, unit_cost=145, unit_price=280,
             supplier="Schneider Electric", location="Dépôt Lomé"),
        dict(sku="MULT-FLUKE", name="Multimètre Fluke 87V", category="Outillage",
             unit="unité", quantity=1, min_quantity=1, unit_cost=520, unit_price=0,
             supplier="RS Components", location="Mobile (camion)"),
        dict(sku="CAM-IP-VPU", name="Caméra IP VPU urbain Hikvision", category="VPU",
             unit="unité", quantity=4, min_quantity=2, unit_cost=380, unit_price=650,
             supplier="ADI Global", location="Dépôt Lomé"),
    ]
    extra_stock = [
        dict(sku="OND-SOL3", name="Onduleur solaire 3 kW", category="ENR", unit="unité", quantity=3,
             min_quantity=1, unit_cost=420000, unit_price=580000, supplier="Solar Togo", location="Dépôt Lomé"),
        dict(sku="PAN-450W", name="Panneau solaire 450 Wc", category="ENR", unit="unité", quantity=24,
             min_quantity=10, unit_cost=85000, unit_price=125000, supplier="Solar Togo", location="Dépôt Lomé"),
        dict(sku="COMPT-TEG", name="Compteur communicant TEGIS", category="TEGIS", unit="unité", quantity=12,
             min_quantity=5, unit_cost=95000, unit_price=145000, supplier="Citelum", location="Dépôt Lomé"),
        dict(sku="DISJ-63A", name="Disjoncteur modulaire 63A", category="Tableautique", unit="unité", quantity=20,
             min_quantity=8, unit_cost=12000, unit_price=22000, supplier="Schneider Electric", location="Dépôt Lomé"),
    ]
    for s in stock_data + extra_stock:
        db.add(StockItem(**s))
    db.commit()

    # --------- EXTENSION VOLUME (factures, devis, deals) ---------
    extra_invoices = [
        dict(number="F2026-005", client_id=clients[6].id, date=date(2026,2,28), due_date=date(2026,3,30),
             amount=22000, paid=0, status="envoyée"),
        dict(number="F2026-006", client_id=clients[4].id, date=date(2026,3,1), due_date=date(2026,4,1),
             amount=8200, paid=4100, status="envoyée"),
        dict(number="F2026-007", client_id=clients[7].id, date=date(2026,3,5), due_date=date(2026,4,5),
             amount=14500, paid=0, status="brouillon"),
        dict(number="F2026-008", client_id=clients[2].id, date=date(2026,1,18), due_date=date(2026,2,18),
             amount=5500, paid=0, status="en retard"),
    ]
    for i in extra_invoices:
        db.add(Invoice(**i))
    for q in [
        dict(number="Q2026-007", client_id=clients[6].id, date=date(2026,3,1), valid_until=date(2026,4,1),
             amount=22000, status="envoyé", title="Co-traitance éclairage Macouria"),
        dict(number="Q2026-008", client_id=clients[5].id, date=date(2026,3,8), valid_until=date(2026,5,8),
             amount=85000, status="brouillon", title="Dossier FEDER smart-lighting"),
    ]:
        db.add(Quote(**q))
    for d in [
        dict(title="Maintenance TEGIS annuelle", client_id=clients[0].id, stage="qualified", amount=12000, probability=40, pole="Consulting"),
        dict(title="Extension IRVE parking CEET", client_id=clients[2].id, stage="proposal", amount=35000, probability=55, pole="Installations"),
    ]:
        db.add(Deal(**d))
    db.commit()

    for t in [
        dict(training_id=trainings[0].id, firstname="Kodjo", lastname="Amouzou", email="k.amouzou@demo.tg", company="CCI Togo", attendance=100, evaluation=14, certified=True),
        dict(training_id=trainings[0].id, firstname="Fatou", lastname="Diallo", email="f.diallo@demo.tg", company="CCI Togo", attendance=90, evaluation=13, certified=True),
        dict(training_id=trainings[1].id, firstname="Mensah", lastname="Kpakpo", email="m.kpakpo@demo.tg", company="Indépendant", attendance=0, evaluation=0, certified=False),
    ]:
        db.add(Trainee(**t))
    db.commit()

    from app.demo_seed_common import finalize_demo_dataset
    finalize_demo_dataset(db)
