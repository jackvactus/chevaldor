"""Moteur de notifications métier — événements, canaux, outbox."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Invoice, StockItem, User
from app.models_enterprise import NotificationOutbox
from app.models_platform import NotificationRule
from app.services.notify import create_app_notification, notify_admins

DEFAULT_RULES = [
    {
        "event_type": "invoice_overdue",
        "channels_json": '["in_app","email"]',
        "template_title": "Facture échue",
        "template_body": "La facture {number} ({amount} FCFA) est en retard de {days} jours.",
    },
    {
        "event_type": "stock_low",
        "channels_json": '["in_app"]',
        "template_title": "Stock faible",
        "template_body": "Article {sku} — stock {qty} (seuil {min_qty}).",
    },
    {
        "event_type": "payment_received",
        "channels_json": '["in_app","email"]',
        "template_title": "Paiement reçu",
        "template_body": "Encaissement {amount} FCFA — {reference}.",
    },
    {
        "event_type": "approval_done",
        "channels_json": '["in_app"]',
        "template_title": "Approbation traitée",
        "template_body": "{title} — statut {status}.",
    },
    {
        "event_type": "delivery_delay",
        "channels_json": '["in_app"]',
        "template_title": "Retard livraison",
        "template_body": "Commande {reference} en retard.",
    },
    {
        "event_type": "ticket_opened",
        "channels_json": '["in_app"]',
        "template_title": "Nouveau ticket",
        "template_body": "Ticket {reference} — {subject}",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def seed_notification_rules(db: Session) -> None:
    for r in DEFAULT_RULES:
        if db.query(NotificationRule).filter(NotificationRule.event_type == r["event_type"]).first():
            continue
        db.add(NotificationRule(**r, is_active=True))
    db.commit()


def _format(template: str, ctx: Dict[str, Any]) -> str:
    try:
        return template.format(**ctx)
    except (KeyError, ValueError):
        return template


def _enqueue_outbox(db: Session, channel: str, recipient: str, body: str) -> None:
    db.add(NotificationOutbox(
        channel=channel,
        recipient=recipient,
        body=body,
        status="pending",
        created_at=_now(),
    ))


def emit_event(
    db: Session,
    event_type: str,
    context: Dict[str, Any],
    *,
    user_ids: Optional[List[int]] = None,
) -> None:
    rule = db.query(NotificationRule).filter(
        NotificationRule.event_type == event_type,
        NotificationRule.is_active == True,
    ).first()
    if not rule:
        return
    try:
        channels = json.loads(rule.channels_json or '["in_app"]')
    except json.JSONDecodeError:
        channels = ["in_app"]
    title = _format(rule.template_title or event_type, context)
    message = _format(rule.template_body or "", context)
    targets = user_ids
    if not targets:
        admins = db.query(User).filter(User.is_active == True, User.role == "admin").all()
        targets = [a.id for a in admins[:3]]
    if "in_app" in channels:
        for uid in targets:
            create_app_notification(
                db,
                user_id=uid,
                type_="info",
                title=title,
                message=message,
                category=event_type,
            )
    if "email" in channels:
        for uid in targets:
            u = db.query(User).filter(User.id == uid).first()
            if u and u.email:
                _enqueue_outbox(db, "email", u.email, f"{title}\n{message}")
    if "sms" in channels:
        phone = context.get("phone", "")
        if phone:
            _enqueue_outbox(db, "sms", phone, f"{title}: {message}"[:160])
    if "whatsapp" in channels:
        phone = context.get("phone", "")
        if phone:
            _enqueue_outbox(db, "whatsapp", phone, f"{title}\n{message}")
    db.commit()


def run_scheduled_checks(db: Session) -> Dict[str, int]:
    """Vérifications planifiées — à appeler au démarrage ou via cron."""
    stats = {"invoice_overdue": 0, "stock_low": 0}
    today = date.today()
    overdue = db.query(Invoice).filter(
        Invoice.status.in_(["envoyée", "en retard"]),
        Invoice.due_date < today,
    ).limit(50).all()
    for inv in overdue:
        balance = float(inv.amount or 0) - float(inv.paid or 0)
        if balance <= 0:
            continue
        days = (today - inv.due_date).days if inv.due_date else 0
        emit_event(db, "invoice_overdue", {
            "number": inv.number or inv.id,
            "amount": f"{balance:,.0f}",
            "days": days,
        })
        stats["invoice_overdue"] += 1
    low_stock = db.query(StockItem).filter(
        StockItem.quantity <= StockItem.min_quantity,
        StockItem.min_quantity > 0,
    ).limit(30).all()
    for item in low_stock:
        emit_event(db, "stock_low", {
            "sku": item.sku or item.name,
            "qty": item.quantity or 0,
            "min_qty": item.min_quantity or 0,
        })
        stats["stock_low"] += 1
    return stats


def notify_payment_received(db: Session, amount: float, reference: str, user_id: int | None = None) -> None:
    emit_event(
        db,
        "payment_received",
        {"amount": f"{amount:,.0f}", "reference": reference},
        user_ids=[user_id] if user_id else None,
    )
