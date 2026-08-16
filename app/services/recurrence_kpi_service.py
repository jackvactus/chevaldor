"""
Service pour les KPIs des récurrences et collections.
Calcule statistiques, performances, et indicateurs clés.
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from app.models_recurring_advanced import PaymentRecurrence, PaymentCollection, CollectionPaymentDetail
from app.models import Client


class RecurrenceKPIService:
    """Calcule les KPIs pour les récurrences et collections."""
    
    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
    
    def get_recurrence_kpis(self) -> Dict:
        """Obtenir les KPIs globaux des récurrences."""
        
        # Totaux par statut
        statuses = self.db.query(
            PaymentRecurrence.status,
            func.count(PaymentRecurrence.id).label('count'),
        ).filter_by(company_id=self.company_id).group_by(PaymentRecurrence.status).all()
        
        status_dict = {s[0]: s[1] for s in statuses}
        total_recurrences = sum([v for k, v in status_dict.items()])
        
        # Montants et fréquences
        freq_data = self.db.query(
            PaymentRecurrence.frequency_code,
            func.count(PaymentRecurrence.id).label('count'),
        ).filter_by(company_id=self.company_id, is_active=True).group_by(
            PaymentRecurrence.frequency_code
        ).all()
        
        frequency_dict = {f[0]: f[1] for f in freq_data}
        
        # Total mensuel attendu
        today = date.today()
        monthly_expected = self.db.query(
            func.sum(PaymentRecurrence.amount)
        ).filter(
            PaymentRecurrence.company_id == self.company_id,
            PaymentRecurrence.status == "active",
            PaymentRecurrence.start_date <= today,
            or_(PaymentRecurrence.end_date.is_(None), PaymentRecurrence.end_date >= today)
        ).scalar() or 0
        
        # Collecte YTD
        year_start = date(today.year, 1, 1)
        ytd_collected = self.db.query(
            func.sum(CollectionPaymentDetail.payment_amount)
        ).join(
            PaymentCollection,
            CollectionPaymentDetail.collection_id == PaymentCollection.id
        ).filter(
            PaymentCollection.company_id == self.company_id,
            PaymentCollection.collection_date >= year_start,
            CollectionPaymentDetail.status == "completed"
        ).scalar() or 0
        
        ytd_collection_rate = (ytd_collected / monthly_expected / 12) * 100 if monthly_expected > 0 else 0
        
        # Paiements en retard
        overdue = self.db.query(
            func.count(PaymentRecurrence.id).label('count'),
            func.sum(PaymentRecurrence.amount).label('amount'),
        ).filter(
            PaymentRecurrence.company_id == self.company_id,
            PaymentRecurrence.status == "active",
            PaymentRecurrence.next_due_date < today,
        ).first()
        
        # Top clients
        top_clients = self.db.query(
            Client.id,
            Client.name,
            func.sum(PaymentRecurrence.amount).label('total_amount'),
            func.count(PaymentRecurrence.id).label('count'),
        ).join(
            PaymentRecurrence,
            PaymentRecurrence.client_id == Client.id
        ).filter(
            PaymentRecurrence.company_id == self.company_id,
            PaymentRecurrence.status == "active"
        ).group_by(Client.id, Client.name).order_by(
            func.sum(PaymentRecurrence.amount).desc()
        ).limit(3).all()
        
        return {
            "total_recurrences": total_recurrences,
            "active_count": status_dict.get("active", 0),
            "suspended_count": status_dict.get("suspended", 0),
            "terminated_count": status_dict.get("terminated", 0),
            "cancelled_count": status_dict.get("cancelled", 0),
            
            "financial": {
                "total_monthly_expected": float(monthly_expected),
                "total_ytd_collected": float(ytd_collected),
                "ytd_collection_rate": round(min(ytd_collection_rate, 100), 2),
                "average_payment_value": float(monthly_expected / (status_dict.get("active", 1) or 1)),
                "overdue_amount": float(overdue[1] or 0) if overdue else 0,
                "overdue_count": overdue[0] if overdue else 0,
            },
            
            "by_frequency": frequency_dict,
            
            "by_client": {
                "top_3": [
                    {
                        "client_id": c[0],
                        "name": c[1],
                        "amount": float(c[2]),
                        "recurrence_count": c[3],
                    }
                    for c in top_clients
                ]
            },
            
            "health": {
                "on_schedule": status_dict.get("active", 0) - (overdue[0] if overdue else 0),
                "slightly_late": (overdue[0] if overdue else 0) if (overdue[1] or 0) < monthly_expected * 0.3 else 0,
                "very_late": (overdue[0] if overdue else 0) if (overdue[1] or 0) >= monthly_expected * 0.3 else 0,
            }
        }
    
    def get_collection_kpis(self, date_from: Optional[date] = None, date_to: Optional[date] = None) -> Dict:
        """Obtenir les KPIs des collections."""
        
        if not date_from:
            date_from = date.today() - timedelta(days=30)
        if not date_to:
            date_to = date.today()
        
        # Collection d'aujourd'hui
        today = date.today()
        today_collection = self.db.query(
            func.sum(CollectionPaymentDetail.expected_amount).label('expected'),
            func.sum(CollectionPaymentDetail.payment_amount).label('collected'),
            func.count(CollectionPaymentDetail.id).label('count'),
            func.count(func.distinct(CollectionPaymentDetail.client_id)).label('clients'),
        ).join(
            PaymentCollection,
            CollectionPaymentDetail.collection_id == PaymentCollection.id
        ).filter(
            PaymentCollection.company_id == self.company_id,
            PaymentCollection.collection_date == today,
        ).first()
        
        today_expected = float(today_collection[0] or 0) if today_collection else 0
        today_collected = float(today_collection[1] or 0) if today_collection else 0
        today_completion_rate = (today_collected / today_expected * 100) if today_expected > 0 else 0
        
        # Performance agents
        best_agent = self.db.query(
            PaymentCollection.agent_id,
            func.sum(CollectionPaymentDetail.payment_amount).label('total'),
        ).join(
            PaymentCollection,
            CollectionPaymentDetail.collection_id == PaymentCollection.id
        ).filter(
            PaymentCollection.company_id == self.company_id,
            PaymentCollection.collection_date >= date_from,
            PaymentCollection.collection_date <= date_to,
        ).group_by(
            PaymentCollection.agent_id
        ).order_by(
            func.sum(CollectionPaymentDetail.payment_amount).desc()
        ).first()
        
        # Best client
        best_client = self.db.query(
            Client.id,
            Client.name,
            func.sum(CollectionPaymentDetail.payment_amount).label('total'),
        ).join(
            CollectionPaymentDetail,
            CollectionPaymentDetail.client_id == Client.id
        ).join(
            PaymentCollection,
            CollectionPaymentDetail.collection_id == PaymentCollection.id
        ).filter(
            PaymentCollection.company_id == self.company_id,
            PaymentCollection.collection_date >= date_from,
            PaymentCollection.collection_date <= date_to,
        ).group_by(
            Client.id, Client.name
        ).order_by(
            func.sum(CollectionPaymentDetail.payment_amount).desc()
        ).first()
        
        # Delays
        delayed = self.db.query(func.count(PaymentRecurrence.id)).filter(
            PaymentRecurrence.company_id == self.company_id,
            PaymentRecurrence.next_due_date < today,
            PaymentRecurrence.status == "active",
        ).scalar() or 0
        
        return {
            "today": {
                "collection_date": str(today),
                "expected_amount": today_expected,
                "collected_amount": today_collected,
                "completion_rate": round(min(today_completion_rate, 100), 2),
                "payment_count": today_collection[2] if today_collection else 0,
                "clients_involved": today_collection[3] if today_collection else 0,
            },
            
            "performance": {
                "best_agent": {
                    "agent_id": best_agent[0] if best_agent else None,
                    "amount": float(best_agent[1]) if best_agent else 0,
                },
                "best_client": {
                    "name": best_client[1] if best_client else None,
                    "amount": float(best_client[2]) if best_client else 0,
                }
            },
            
            "delays": {
                "today_overdue": 0,  # À calculer en fonction de la date
                "this_month_overdue": delayed,
            }
        }


# Importer sqlalchemy or_ pour les requêtes
from sqlalchemy import or_

