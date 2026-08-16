"""Journal d'audit avec horodatage précis."""
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session
from app.models_erp import AuditLog


def log_audit(
    db: Session,
    action: str,
    module: str,
    entity_type: str = "",
    entity_id: int = None,
    detail: str = "",
    user_id: int = None,
    user_email: str = "",
    ip: str = "",
    old_value: str = "",
    new_value: str = "",
    user_agent: str = "",
):
    now = datetime.now(timezone.utc).astimezone()
    logged = now.strftime("%Y-%m-%dT%H:%M:%S")
    if user_agent:
        ua = str(user_agent)[:250]
        detail = f"{detail} | UA: {ua}" if detail else f"UA: {ua}"

    db.add(AuditLog(
        created_at=date.today(),
        logged_at=logged,
        user_id=user_id,
        user_email=user_email or "",
        action=action,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail[:2000] if detail else "",
        old_value=(old_value or "")[:4000],
        new_value=(new_value or "")[:4000],
        ip_address=ip or "",
    ))
    db.flush()
