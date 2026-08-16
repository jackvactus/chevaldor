"""
Service de gestion des paiements récurrents.
Logique métier : fréquences, génération automatique, calendrier.
"""

from datetime import date, timedelta, datetime
from sqlalchemy.orm import Session
from typing import List, Optional, Tuple
from dateutil.relativedelta import relativedelta
from app.models_recurring_advanced import (
    PaymentRecurrence, RecurrenceGeneration, RecurrenceHistory,
    PaymentCollection, CollectionPaymentDetail, CollectionPaymentHistory
)
from app.models import Invoice, Client
import json


class FrequencyCalculator:
    """Calcule la prochaine date d'échéance selon la fréquence."""
    
    FREQUENCY_DAYS = {
        "daily": 1,
        "weekly": 7,
        "biweekly": 14,
        "monthly": 30,  # approx
        "quarterly": 90,
        "semiannually": 180,
        "annually": 365,
    }
    
    @staticmethod
    def next_occurrence(
        last_date: date,
        frequency: str,
        custom_days: Optional[int] = None,
        weekdays: Optional[str] = None,
        month_day: Optional[int] = None,
    ) -> date:
        """
        Calcule la prochaine occurrence basée sur fréquence.
        
        Args:
            last_date: date de référence
            frequency: type de fréquence (daily, weekly, monthly, etc.)
            custom_days: intervalle personnalisé en jours
            weekdays: "1,3,5" pour lun/mer/ven
            month_day: jour du mois (15, -1 pour dernier)
        """
        
        if frequency == "custom" and custom_days:
            return last_date + timedelta(days=custom_days)
        
        if frequency == "weekly" and weekdays:
            return FrequencyCalculator._next_specific_weekday(last_date, weekdays)
        
        if frequency == "monthly" and month_day:
            return FrequencyCalculator._next_specific_month_day(last_date, month_day)
        
        # Fréquences standards
        if frequency == "daily":
            return last_date + timedelta(days=1)
        elif frequency == "weekly":
            return last_date + timedelta(weeks=1)
        elif frequency == "biweekly":
            return last_date + timedelta(days=14)
        elif frequency == "monthly":
            return last_date + relativedelta(months=1)
        elif frequency == "quarterly":
            return last_date + relativedelta(months=3)
        elif frequency == "semiannually":
            return last_date + relativedelta(months=6)
        elif frequency == "annually":
            return last_date + relativedelta(years=1)
        
        return last_date
    
    @staticmethod
    def _next_specific_weekday(ref_date: date, weekdays_str: str) -> date:
        """Prochain jour spécifique de la semaine."""
        weekdays = list(map(int, weekdays_str.split(",")))  # [1,3,5]
        current_date = ref_date + timedelta(days=1)
        
        for _ in range(14):  # chercher dans les 2 prochaines semaines max
            if current_date.weekday() + 1 in weekdays:  # +1 car Python: lun=0
                return current_date
            current_date += timedelta(days=1)
        
        return ref_date + timedelta(weeks=1)
    
    @staticmethod
    def _next_specific_month_day(ref_date: date, day_of_month: int) -> date:
        """Prochain jour spécifique du mois."""
        if day_of_month == -1:  # dernier jour du mois
            next_month = ref_date + relativedelta(months=1)
            return next_month + relativedelta(day=31)
        
        next_month = ref_date + relativedelta(months=1)
        try:
            return next_month.replace(day=day_of_month)
        except ValueError:
            # Jour n'existe pas (ex: 31 février), retourner dernier jour
            return next_month + relativedelta(day=31)


class PaymentRecurrenceService:
    """Service pour gérer les paiements récurrents."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_recurrence(self, data: dict, company_id: int, user_id: int) -> PaymentRecurrence:
        """Crée une nouvelle récurrence."""
        
        # Calculer first next_due_date
        next_due = FrequencyCalculator.next_occurrence(
            data['start_date'],
            data.get('frequency_code', 'monthly'),
            data.get('custom_interval_days'),
            data.get('weekdays'),
            data.get('month_day'),
        )
        
        recurrence = PaymentRecurrence(
            company_id=company_id,
            created_by=user_id,
            updated_by=user_id,
            name=data['name'],
            description=data.get('description', ''),
            client_id=data['client_id'],
            project_id=data.get('project_id'),
            contract_id=data.get('contract_id'),
            category=data.get('category', ''),
            recurrence_type=data.get('recurrence_type', 'invoice'),
            amount=data['amount'],
            currency_code=data.get('currency_code', 'XOF'),
            vat_rate=data.get('vat_rate', 0),
            discount_pct=data.get('discount_pct', 0),
            balance=data.get('balance', 0),
            frequency_code=data.get('frequency_code', 'monthly'),
            custom_interval_days=data.get('custom_interval_days'),
            weekdays=data.get('weekdays', ''),
            month_day=data.get('month_day'),
            start_date=data['start_date'],
            end_date=data.get('end_date'),
            next_due_date=next_due,
            status='active',
            is_active=True,
            auto_generate=data.get('auto_generate', True),
            auto_notify=data.get('auto_notify', True),
            auto_followup=data.get('auto_followup', False),
            auto_invoice=data.get('auto_invoice', False),
            draft_days_before=data.get('draft_days_before', 3),
        )
        
        self.db.add(recurrence)
        self.db.flush()  # pour avoir l'ID
        
        # Log création
        self._log_history(recurrence.id, 'created', {}, recurrence.to_dict(), user_id)
        
        return recurrence
    
    def update_recurrence(self, recurrence_id: int, data: dict, user_id: int) -> PaymentRecurrence:
        """Met à jour une récurrence."""
        
        recurrence = self.db.query(PaymentRecurrence).filter_by(id=recurrence_id).first()
        if not recurrence:
            raise ValueError(f"Recurrence {recurrence_id} not found")
        
        old_values = recurrence.to_dict()
        
        allowed_fields = {
            'name', 'description', 'client_id', 'project_id', 'contract_id',
            'category', 'recurrence_type', 'amount', 'currency_code', 'vat_rate',
            'discount_pct', 'balance', 'frequency_code', 'custom_interval_days',
            'weekdays', 'month_day', 'start_date', 'end_date', 'status',
            'auto_generate', 'auto_notify', 'auto_followup', 'auto_invoice',
            'draft_days_before',
        }
        for key, value in data.items():
            if key in allowed_fields and value is not None:
                setattr(recurrence, key, value)

        recurrence.updated_by = user_id
        recurrence.updated_at = datetime.utcnow()

        if any(field in data for field in ('frequency_code', 'custom_interval_days', 'weekdays', 'month_day', 'start_date')):
            anchor_date = data.get('start_date', recurrence.start_date)
            if recurrence.next_due_date and anchor_date and recurrence.next_due_date < anchor_date:
                anchor_date = recurrence.start_date
            recurrence.next_due_date = FrequencyCalculator.next_occurrence(
                anchor_date,
                data.get('frequency_code', recurrence.frequency_code),
                data.get('custom_interval_days', recurrence.custom_interval_days),
                data.get('weekdays', recurrence.weekdays),
                data.get('month_day', recurrence.month_day),
            )

        new_values = recurrence.to_dict()
        self._log_history(recurrence_id, 'modified', old_values, new_values, user_id)
        
        return recurrence
    
    def suspend_recurrence(self, recurrence_id: int, reason: str, user_id: int) -> PaymentRecurrence:
        """Suspend une récurrence."""
        recurrence = self.db.query(PaymentRecurrence).filter_by(id=recurrence_id).first()
        if not recurrence:
            raise ValueError(f"Recurrence {recurrence_id} not found")
        
        old_status = recurrence.status
        recurrence.status = 'suspended'
        recurrence.is_active = False
        recurrence.updated_by = user_id
        
        self._log_history(
            recurrence_id, 'suspended',
            {'status': old_status},
            {'status': 'suspended'},
            user_id,
            reason
        )
        
        return recurrence
    
    def resume_recurrence(self, recurrence_id: int, user_id: int) -> PaymentRecurrence:
        """Reprend une récurrence suspendue."""
        recurrence = self.db.query(PaymentRecurrence).filter_by(id=recurrence_id).first()
        if not recurrence:
            raise ValueError(f"Recurrence {recurrence_id} not found")
        
        old_status = recurrence.status
        recurrence.status = 'active'
        recurrence.is_active = True
        recurrence.updated_by = user_id
        
        self._log_history(
            recurrence_id, 'resumed',
            {'status': old_status},
            {'status': 'active'},
            user_id
        )
        
        return recurrence
    
    def terminate_recurrence(self, recurrence_id: int, reason: str, user_id: int) -> PaymentRecurrence:
        """Termine une récurrence."""
        recurrence = self.db.query(PaymentRecurrence).filter_by(id=recurrence_id).first()
        if not recurrence:
            raise ValueError(f"Recurrence {recurrence_id} not found")
        
        recurrence.status = 'terminated'
        recurrence.is_active = False
        recurrence.end_date = date.today()
        recurrence.updated_by = user_id
        
        self._log_history(
            recurrence_id, 'terminated',
            {'status': 'active', 'end_date': str(recurrence.end_date)},
            {'status': 'terminated'},
            user_id,
            reason
        )
        
        return recurrence
    
    def generate_due_invoices(self, target_date: Optional[date] = None) -> List[dict]:
        """
        Génère les factures dues à une date.
        Appelé par scheduler chaque jour.
        Retourne liste des générations effectuées.
        """
        target_date = target_date or date.today()
        results = []
        
        # Récurrences actives avec next_due_date <= today + draft_days_before
        draft_threshold = target_date + timedelta(days=3)
        
        recurrences = self.db.query(PaymentRecurrence).filter(
            PaymentRecurrence.is_active == True,
            PaymentRecurrence.status == 'active',
            PaymentRecurrence.next_due_date <= draft_threshold,
        ).all()
        
        for recurrence in recurrences:
            if recurrence.end_date and recurrence.end_date < target_date:
                # Récurrence terminée
                recurrence.is_active = False
                recurrence.status = 'terminated'
                continue
            
            try:
                # Générer facture draft
                if recurrence.auto_generate or recurrence.draft_days_before > 0:
                    invoice = self._create_draft_invoice(recurrence, target_date)
                    
                    # Logger génération
                    generation = RecurrenceGeneration(
                        recurrence_id=recurrence.id,
                        generated_invoice_id=invoice.id,
                        scheduled_date=recurrence.next_due_date,
                        actual_date=datetime.utcnow(),
                        amount=recurrence.amount,
                        status='success',
                    )
                    self.db.add(generation)
                    
                    # Mettre à jour next_due_date
                    recurrence.next_due_date = FrequencyCalculator.next_occurrence(
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
                        'amount': recurrence.amount,
                    })
                    
            except Exception as e:
                # Logger l'erreur
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
        return results
    
    def _create_draft_invoice(self, recurrence: PaymentRecurrence, date_ref: date) -> Invoice:
        """Crée une facture brouillon à partir d'une récurrence."""
        # Simplifié : créer invoice avec infos de la récurrence
        invoice = Invoice(
            company_id=recurrence.company_id,
            client_id=recurrence.client_id,
            project_id=recurrence.project_id,
            date=date_ref,
            amount=recurrence.amount,
            vat_rate=recurrence.vat_rate,
            discount_pct=recurrence.discount_pct,
            status='draft',
            doc_type='invoice',
            notes=f"Auto-généré par récurrence '{recurrence.name}'",
        )
        self.db.add(invoice)
        self.db.flush()
        return invoice
    
    def _log_history(
        self,
        recurrence_id: int,
        action: str,
        old_values: dict,
        new_values: dict,
        user_id: int,
        reason: str = ""
    ):
        """Enregistre une modification dans l'historique."""
        changed_fields = [k for k in old_values if old_values.get(k) != new_values.get(k)]
        
        history = RecurrenceHistory(
            recurrence_id=recurrence_id,
            action=action,
            old_values=json.dumps(old_values, default=str),
            new_values=json.dumps(new_values, default=str),
            changed_fields=",".join(changed_fields),
            modified_by=user_id,
            reason=reason,
        )
        self.db.add(history)
    
    def get_active_recurrences(self, company_id: int) -> List[PaymentRecurrence]:
        """Récupère toutes les récurrences actives."""
        return self.db.query(PaymentRecurrence).filter(
            PaymentRecurrence.company_id == company_id,
            PaymentRecurrence.is_active == True,
        ).all()
    
    def get_recurrence_calendar(self, company_id: int, year: int, month: int) -> List[dict]:
        """Retourne calendrier des paiements pour un mois."""
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        
        # Récurrences actives
        recurrences = self.get_active_recurrences(company_id)
        
        calendar = {}
        for rec in recurrences:
            current = rec.next_due_date
            while current <= end:
                if current >= start and current <= end:
                    if current not in calendar:
                        calendar[current] = []
                    calendar[current].append({
                        'recurrence_id': rec.id,
                        'client': rec.client_id,
                        'amount': rec.amount,
                        'name': rec.name,
                    })
                
                current = FrequencyCalculator.next_occurrence(
                    current,
                    rec.frequency_code,
                    rec.custom_interval_days,
                    rec.weekdays,
                    rec.month_day,
                )
        
        return [
            {'date': d, 'payments': calendar[d]}
            for d in sorted(calendar.keys())
        ]


class PaymentCollectionService:
    """Service pour gérer les fiches de collecte."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_collection(self, collection_date: date, agent_id: Optional[int], company_id: int) -> PaymentCollection:
        """Crée une nouvelle fiche de collecte."""
        collection = PaymentCollection(
            company_id=company_id,
            collection_date=collection_date,
            agent_id=agent_id,
            status='draft',
        )
        self.db.add(collection)
        self.db.flush()
        return collection
    
    def add_payment_to_collection(
        self,
        collection_id: int,
        payment_data: dict,
        user_id: int,
    ) -> CollectionPaymentDetail:
        """Ajoute un paiement à une fiche."""
        payment = CollectionPaymentDetail(
            collection_id=collection_id,
            client_id=payment_data['client_id'],
            recurrence_id=payment_data.get('recurrence_id'),
            payment_amount=payment_data['payment_amount'],
            expected_amount=payment_data.get('expected_amount', payment_data['payment_amount']),
            payment_date=payment_data['payment_date'],
            payment_method=payment_data.get('payment_method', 'cash'),
            payment_reference=payment_data.get('payment_reference', ''),
            agent_id=payment_data.get('agent_id'),
            notes=payment_data.get('notes', ''),
            created_by=user_id,
            status='completed',
            is_partial=payment_data.get('payment_amount', 0) < payment_data.get('expected_amount', payment_data.get('payment_amount', 0)),
        )
        self.db.add(payment)
        self.db.flush()
        return payment
    
    def update_payment(
        self,
        payment_id: int,
        new_amount: Optional[float],
        new_status: Optional[str],
        modification_reason: str,
        user_id: int,
    ) -> CollectionPaymentDetail:
        """Met à jour un paiement et enregistre l'historique."""
        payment = self.db.query(CollectionPaymentDetail).filter_by(id=payment_id).first()
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")
        
        # Enregistrer l'historique
        history = CollectionPaymentHistory(
            payment_detail_id=payment_id,
            old_amount=payment.payment_amount if new_amount else None,
            new_amount=new_amount,
            old_status=payment.status if new_status else None,
            new_status=new_status,
            modified_by=user_id,
            modification_reason=modification_reason,
        )
        self.db.add(history)
        
        # Mettre à jour
        if new_amount is not None:
            payment.payment_amount = new_amount
        if new_status:
            payment.status = new_status
        
        return payment
