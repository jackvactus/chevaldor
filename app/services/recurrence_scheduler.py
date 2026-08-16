"""
Scheduler pour auto-générer les factures des paiements récurrents.
Peut être appelé par:
- APScheduler (background task)
- Cron job système
- Endpoint API manuel
"""

from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from typing import List, Dict
import logging
from app.database import SessionLocal, engine
from app.models_recurring_advanced import PaymentRecurrence, RecurrenceGeneration
from app.services.recurrence_service import PaymentRecurrenceService

logger = logging.getLogger(__name__)


class RecurrenceScheduler:
    """Scheduler pour auto-génération des factures récurrentes."""
    
    def __init__(self, db: Session = None):
        self.db = db or SessionLocal()
    
    def run_daily(self) -> Dict:
        """Exécuté quotidiennement pour générer les factures dues."""
        try:
            logger.info(f"[Recurrence Scheduler] Running at {datetime.utcnow().isoformat()}")
            
            service = PaymentRecurrenceService(self.db)
            results = service.generate_due_invoices(date.today())
            
            success_count = len([r for r in results if r['status'] == 'success'])
            failed_count = len([r for r in results if r['status'] == 'failed'])
            
            logger.info(f"[Recurrence Scheduler] Generated {success_count} invoices, {failed_count} failed")
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "total": len(results),
                "success": success_count,
                "failed": failed_count,
                "results": results,
            }
        except Exception as e:
            logger.error(f"[Recurrence Scheduler] Error: {str(e)}", exc_info=True)
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "success": False,
            }
    
    def run_with_apsched(self):
        """Wrapper pour APScheduler."""
        from apscheduler.schedulers.background import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        
        # Exécuter chaque jour à 02:00 UTC
        scheduler.add_job(
            self.run_daily,
            'cron',
            hour=2,
            minute=0,
            id='recurrence_generator',
            name='Auto-generate recurring invoices',
        )
        
        scheduler.start()
        logger.info("RecurrenceScheduler started with APScheduler")
        return scheduler
    
    def run_for_company(self, company_id: int, target_date: date = None) -> Dict:
        """Générer pour une companie spécifique."""
        target_date = target_date or date.today()
        
        try:
            draft_threshold = target_date + timedelta(days=3)
            
            recurrences = self.db.query(PaymentRecurrence).filter(
                PaymentRecurrence.company_id == company_id,
                PaymentRecurrence.is_active == True,
                PaymentRecurrence.status == 'active',
                PaymentRecurrence.next_due_date <= draft_threshold,
            ).all()
            
            logger.info(f"[Company {company_id}] Processing {len(recurrences)} recurrences")
            
            service = PaymentRecurrenceService(self.db)
            results = []
            
            for recurrence in recurrences:
                try:
                    invoice = service._create_draft_invoice(recurrence, target_date)
                    
                    generation = RecurrenceGeneration(
                        recurrence_id=recurrence.id,
                        generated_invoice_id=invoice.id,
                        scheduled_date=recurrence.next_due_date,
                        actual_date=datetime.utcnow(),
                        amount=recurrence.amount,
                        status='success',
                    )
                    self.db.add(generation)
                    
                    recurrence.next_due_date = service.FrequencyCalculator.next_occurrence(
                        recurrence.next_due_date,
                        recurrence.frequency_code,
                        recurrence.custom_interval_days,
                        recurrence.weekdays,
                        recurrence.month_day,
                    )
                    recurrence.last_generated_at = datetime.utcnow().isoformat()
                    
                    results.append({
                        'recurrence_id': recurrence.id,
                        'invoice_id': invoice.id,
                        'status': 'success',
                    })
                except Exception as e:
                    logger.error(f"Failed to generate invoice for recurrence {recurrence.id}: {str(e)}")
                    
                    generation = RecurrenceGeneration(
                        recurrence_id=recurrence.id,
                        scheduled_date=recurrence.next_due_date,
                        actual_date=datetime.utcnow(),
                        amount=recurrence.amount,
                        status='failed',
                        error_message=str(e),
                    )
                    self.db.add(generation)
                    
                    results.append({
                        'recurrence_id': recurrence.id,
                        'status': 'failed',
                        'error': str(e),
                    })
            
            self.db.commit()
            
            return {
                "company_id": company_id,
                "target_date": target_date.isoformat(),
                "total": len(results),
                "success": len([r for r in results if r['status'] == 'success']),
                "failed": len([r for r in results if r['status'] == 'failed']),
                "results": results,
            }
        except Exception as e:
            logger.error(f"[Company {company_id}] Error: {str(e)}", exc_info=True)
            return {
                "company_id": company_id,
                "error": str(e),
                "success": False,
            }
    
    def close(self):
        """Fermer la session."""
        if self.db:
            self.db.close()


# Fonctions de module pour utilisation directe
def schedule_generation_with_apsched():
    """Configurer APScheduler pour auto-génération."""
    scheduler = RecurrenceScheduler().run_with_apsched()
    return scheduler


def trigger_generation(company_id: int = None, target_date: date = None) -> Dict:
    """Déclencher une génération manuelle."""
    db = SessionLocal()
    try:
        sched = RecurrenceScheduler(db)
        
        if company_id:
            return sched.run_for_company(company_id, target_date)
        else:
            return sched.run_daily()
    finally:
        sched.close()


# API Endpoint pour déclencher la génération
async def trigger_generation_api(
    company_id: int = None,
    target_date: str = None,
) -> Dict:
    """
    Endpoint pour déclencher manuellement la génération.
    Peut être appelé via GET /api/recurrence/scheduler/trigger?company_id=1&target_date=2024-01-15
    """
    if target_date:
        target_date = date.fromisoformat(target_date)
    
    return trigger_generation(company_id, target_date)
