"""Relances clients — factures impayées par e-mail."""
from datetime import date
from sqlalchemy.orm import Session

from app.models import Invoice, Client
from app.services.smtp_service import send_email_via_smtp


def send_invoice_reminders(db: Session, *, min_days_overdue: int = 0, limit: int = 50) -> dict:
    """Envoie un rappel pour les factures envoyées / en retard avec solde > 0."""
    today = date.today()
    q = db.query(Invoice).filter(
        Invoice.doc_type != "credit_note",
        Invoice.status.in_(["envoyée", "en retard"]),
    )
    rows = q.order_by(Invoice.due_date).limit(limit).all()
    sent = 0
    skipped = 0
    errors = []
    for inv in rows:
        balance = (inv.amount or 0) - (inv.paid or 0)
        if balance <= 0:
            skipped += 1
            continue
        if inv.due_date and (today - inv.due_date).days < min_days_overdue:
            skipped += 1
            continue
        client = db.query(Client).filter(Client.id == inv.client_id).first() if inv.client_id else None
        to_email = (client.email or "").strip() if client else ""
        if not to_email:
            skipped += 1
            errors.append(f"{inv.number}: pas d'email client")
            continue
        subject = f"Rappel — facture {inv.number} — Peya Company"
        body = (
            f"Bonjour,\n\n"
            f"Nous vous rappelons la facture {inv.number} d'un montant de {balance:,.0f} FCFA "
            f"(échéance : {inv.due_date or '—'}).\n\n"
            f"Merci de régulariser votre situation.\n\n"
            f"Cordialement,\nPeya Company"
        )
        result = send_email_via_smtp(db, to_email=to_email, subject=subject, body=body)
        if result.get("ok"):
            sent += 1
        else:
            errors.append(f"{inv.number}: {result.get('message', 'échec SMTP')}")
    return {"sent": sent, "skipped": skipped, "errors": errors[:20]}
