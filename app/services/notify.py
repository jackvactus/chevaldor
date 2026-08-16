"""Création de notifications in-app + push WebSocket (thread dédié)."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models_prefs import AppNotification
from app.services.notification_hub import hub


def _push_ws_async(user_id: int, payload: dict) -> None:
    def _run() -> None:
        import asyncio

        try:
            asyncio.run(hub.push(user_id, payload))
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def create_app_notification(
    db: Session,
    *,
    user_id: int,
    type_: str,
    title: str,
    message: str,
    category: str = "system",
    channel: str = "in_app",
) -> AppNotification:
    row = AppNotification(
        user_id=user_id,
        type=type_,
        title=title,
        message=message,
        created_at=datetime.now().isoformat(timespec="seconds"),
        category=category,
        channel=channel,
    )
    db.add(row)
    db.flush()
    _push_ws_async(
        user_id,
        {
            "id": row.id,
            "type": row.type,
            "title": row.title,
            "message": row.message,
            "category": row.category,
            "created_at": row.created_at,
        },
    )
    return row


def notify_admins(
    db: Session,
    *,
    type_: str,
    title: str,
    message: str,
    category: str = "system",
) -> None:
    from app.models import User

    admins = db.query(User).filter(User.is_active == True, User.role == "admin").all()
    for admin in admins:
        create_app_notification(
            db,
            user_id=admin.id,
            type_=type_,
            title=title,
            message=message,
            category=category,
        )
