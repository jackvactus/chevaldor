"""Groupes de diffusion e-mail (employés + utilisateurs)."""
from __future__ import annotations

import json
import re
from typing import List

from sqlalchemy.orm import Session

from app.models import User
from app.models_erp import Employee
from app.models_enterprise import UserGroup, UserGroupMember

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_extra_emails(raw: str) -> List[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [e.strip().lower() for e in data if isinstance(e, str) and EMAIL_RE.match(e.strip())]
        except json.JSONDecodeError:
            pass
    return [e.strip().lower() for e in re.split(r"[,;\s]+", raw) if EMAIL_RE.match(e.strip())]


def group_recipient_emails(db: Session, group: UserGroup) -> List[str]:
    emails: set[str] = set(parse_extra_emails(group.extra_emails or ""))
    members = db.query(UserGroupMember).filter(UserGroupMember.group_id == group.id).all()
    for m in members:
        if m.user_id:
            u = db.query(User).filter(User.id == m.user_id, User.is_active == True).first()
            if u and u.email:
                emails.add(u.email.strip().lower())
        if m.employee_id:
            emp = db.query(Employee).filter(Employee.id == m.employee_id).first()
            if emp and emp.email:
                emails.add(emp.email.strip().lower())
    return sorted(emails)
