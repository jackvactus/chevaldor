"""Canaux SMS / WhatsApp (webhook ou simulation)."""
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models_enterprise import NotificationOutbox


def queue_message(db: Session, channel: str, recipient: str, body: str) -> NotificationOutbox:
    row = NotificationOutbox(
        channel=channel,
        recipient=recipient,
        body=body[:2000],
        status="pending",
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    db.add(row)
    db.flush()
    _try_send(row)
    if row.status == "pending":
        row.status = "sent"
        row.sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.commit()
    db.refresh(row)
    return row


def _try_send(row: NotificationOutbox):
    webhook = ""
    if row.channel == "sms":
        webhook = os.environ.get("PEYA_SMS_WEBHOOK", "")
    elif row.channel == "whatsapp":
        webhook = os.environ.get("PEYA_WHATSAPP_WEBHOOK", "")
    if not webhook:
        row.status = "simulated"
        return
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            webhook,
            data=json.dumps({"to": row.recipient, "body": row.body}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        row.status = "sent"
        row.sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as e:
        row.status = "error"
        row.error = str(e)[:500]
