"""
Migrations pour le module des paiements récurrents.
Ajoute les nouvelles tables à la BD existante.
"""

from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from datetime import datetime
import json

def migrate_add_recurrence_tables(engine):
    """
    Ajoute toutes les tables nécessaires pour le module des récurrences.
    Appelée au démarrage si les tables n'existent pas.
    """
    
    from app.models_recurring_advanced import (
        RecurrenceFrequency,
        PaymentRecurrence,
        RecurrenceGeneration,
        RecurrenceHistory,
        PaymentCollection,
        CollectionPaymentDetail,
        CollectionPaymentHistory,
    )
    
    from app.database import Base
    
    # Créer toutes les tables
    Base.metadata.create_all(bind=engine)
    
    # Initialiser les fréquences de base
    initialize_frequencies(engine)
    
    print("[Migration] Tables des récurrences créées avec succès")


def initialize_frequencies(engine):
    """Initialise les fréquences de base."""
    
    frequencies = [
        ("daily", "Quotidienne", 1),
        ("weekly", "Hebdomadaire", 7),
        ("biweekly", "Bihebdomadaire", 14),
        ("monthly", "Mensuelle", 30),
        ("quarterly", "Trimestrielle", 90),
        ("semiannually", "Semestrielle", 180),
        ("annually", "Annuelle", 365),
        ("custom", "Personnalisée", -1),
    ]
    
    with engine.begin() as conn:
        # Vérifier si les fréquences existent déjà
        result = conn.execute(text("SELECT COUNT(*) FROM recurrence_frequencies"))
        if result.scalar() == 0:
            for code, label, days_interval in frequencies:
                conn.execute(text("""
                    INSERT INTO recurrence_frequencies (code, label, days_interval, description)
                    VALUES (:code, :label, :days_interval, '')
                """), {"code": code, "label": label, "days_interval": days_interval})
            print("[Migration] Fréquences de base initialisées")


def ensure_recurring_schema_compatibility(engine):
    """
    Vérifie et ajoute les colonnes manquantes aux tables existantes.
    Utile si on change les modèles.
    """
    
    insp = inspect(engine)
    
    # Colonnes à ajouter si manquantes
    checks = [
        # (table_name, column_name, column_type, default_value)
        ("payment_recurrences", "balance", "FLOAT", "0"),
        ("payment_recurrences", "custom_interval_days", "INTEGER", "NULL"),
        ("payment_recurrences", "weekdays", "TEXT", "''"),
        ("payment_recurrences", "month_day", "INTEGER", "NULL"),
    ]
    
    with engine.begin() as conn:
        for table_name, col_name, col_type, default in checks:
            if table_name not in insp.get_table_names():
                continue
            
            cols = insp.get_columns(table_name)
            if not any(c['name'] == col_name for c in cols):
                try:
                    conn.execute(text(f"""
                        ALTER TABLE {table_name}
                        ADD COLUMN {col_name} {col_type} DEFAULT {default}
                    """))
                    print(f"[Migration] Colonne ajoutée: {table_name}.{col_name}")
                except Exception as e:
                    print(f"[Migration] Impossible d'ajouter {table_name}.{col_name}: {str(e)}")


def create_sample_data(engine):
    """
    Crée quelques données d'exemple pour test.
    (À utiliser uniquement en dev)
    """
    
    from app.database import SessionLocal
    from app.models_recurring_advanced import PaymentRecurrence
    from app.models import Client, Company
    from datetime import date, timedelta
    
    db = SessionLocal()
    
    try:
        # Vérifier s'il y a déjà des récurrences
        if db.query(PaymentRecurrence).count() > 0:
            print("[Migration] Données d'exemple déjà présentes, skip")
            return
        
        # Récupérer une companie et un client
        company = db.query(Company).first()
        client = db.query(Client).first()
        
        if not company or not client:
            print("[Migration] Companie ou client non trouvé, skip données d'exemple")
            return
        
        # Créer des récurrences d'exemple
        today = date.today()
        
        recurrences = [
            PaymentRecurrence(
                company_id=company.id,
                created_by=1,
                updated_by=1,
                name="Paiement mensuel client A",
                description="Facture récurrente du client A",
                client_id=client.id,
                category="recoulement",
                amount=500000,
                currency_code="XOF",
                vat_rate=18,
                frequency_code="monthly",
                start_date=today,
                next_due_date=today + timedelta(days=15),
                status='active',
                is_active=True,
                auto_generate=True,
                auto_notify=True,
                draft_days_before=3,
            ),
            PaymentRecurrence(
                company_id=company.id,
                created_by=1,
                updated_by=1,
                name="Paiement bimensuel client B",
                description="Facture bimensuelle du client B",
                client_id=client.id,
                category="recoulement",
                amount=250000,
                currency_code="XOF",
                frequency_code="biweekly",
                start_date=today,
                next_due_date=today + timedelta(days=7),
                status='active',
                is_active=True,
                auto_generate=True,
                auto_notify=True,
            ),
        ]
        
        for rec in recurrences:
            db.add(rec)
        
        db.commit()
        print(f"[Migration] {len(recurrences)} récurrences d'exemple créées")
        
    except Exception as e:
        print(f"[Migration] Erreur création données d'exemple: {str(e)}")
        db.rollback()
    finally:
        db.close()


def run_all_migrations(engine):
    """
    Exécute toutes les migrations dans l'ordre.
    À appeler au démarrage de l'application.
    """
    
    print("\n" + "="*60)
    print("Migration: Module des Paiements Récurrents")
    print("="*60)
    
    try:
        # 1. Créer les tables
        migrate_add_recurrence_tables(engine)
        
        # 2. Vérifier/ajouter colonnes manquantes
        ensure_recurring_schema_compatibility(engine)
        
        # 3. Initialiser fréquences (appelé par migrate_add_recurrence_tables)
        
        print("\n✓ Migrations complètes")
        
    except Exception as e:
        print(f"\n✗ Erreur migration: {str(e)}")
        raise


# Fonction d'export pour app startup
def init_recurrence_module(engine):
    """Initialise le module des récurrences."""
    run_all_migrations(engine)
