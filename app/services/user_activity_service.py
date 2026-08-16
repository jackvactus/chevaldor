"""Agrégation activité utilisateurs — surveillance admin."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models_erp import AuditLog


def _parse_ts(log: AuditLog) -> str:
    return log.logged_at or (str(log.created_at) if log.created_at else "")


def user_activity_report(
    db: Session,
    *,
    days: int = 30,
    user_id: Optional[int] = None,
    user_email: Optional[str] = None,
    limit: int = 500,
) -> dict[str, Any]:
    since = date.today() - timedelta(days=max(1, min(days, 365)))
    q = db.query(AuditLog).filter(AuditLog.created_at >= since)
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    if user_email:
        q = q.filter(AuditLog.user_email.ilike(f"%{user_email.strip()}%"))

    logs = q.order_by(AuditLog.id.desc()).limit(min(limit, 3000)).all()

    by_user: dict[str, dict] = {}
    action_counter: Counter = Counter()
    module_counter: Counter = Counter()

    for log in logs:
        key = log.user_email or (f"#{log.user_id}" if log.user_id else "—")
        u = by_user.setdefault(key, {
            "user_email": log.user_email or "",
            "user_id": log.user_id,
            "total": 0,
            "last_at": "",
            "last_action": "",
            "last_module": "",
            "by_action": Counter(),
            "by_module": Counter(),
        })
        u["total"] += 1
        u["by_action"][log.action or "—"] += 1
        u["by_module"][log.module or "—"] += 1
        ts = _parse_ts(log)
        if not u["last_at"] or ts > u["last_at"]:
            u["last_at"] = ts
            u["last_action"] = log.action or ""
            u["last_module"] = log.module or ""
        action_counter[log.action or "—"] += 1
        module_counter[log.module or "—"] += 1

    users = []
    for key, data in by_user.items():
        users.append({
            "user_email": data["user_email"] or key,
            "user_id": data["user_id"],
            "total": data["total"],
            "last_at": data["last_at"],
            "last_action": data["last_action"],
            "last_module": data["last_module"],
            "by_action": dict(data["by_action"]),
            "by_module": dict(data["by_module"]),
        })
    users.sort(key=lambda x: (-x["total"], x["user_email"]))

    timeline = [
        {
            "id": log.id,
            "logged_at": _parse_ts(log),
            "user_email": log.user_email or "",
            "user_id": log.user_id,
            "action": log.action,
            "module": log.module,
            "entity_type": log.entity_type or "",
            "entity_id": log.entity_id,
            "detail": (log.detail or "")[:500],
            "ip_address": log.ip_address or "",
        }
        for log in logs[: min(limit, 800)]
    ]

    return {
        "period_days": days,
        "since": since.isoformat(),
        "total_events": len(logs),
        "users": users,
        "timeline": timeline,
        "stats": {
            "by_action": dict(action_counter.most_common(20)),
            "by_module": dict(module_counter.most_common(20)),
            "active_users": len(users),
        },
    }
