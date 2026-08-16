"""Garde-fous API : permissions par module et action."""
from fastapi import Depends, HTTPException

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.permissions import has_module_action


def require_action(module: str, action: str):
    """Exige une action sur un module (view, create, update, delete, …)."""

    def checker(
        user: User = Depends(get_current_user),
        db=Depends(get_db),
    ) -> User:
        if not has_module_action(user.role, module, action, db):
            raise HTTPException(403, f"Droits insuffisants ({module}.{action})")
        return user

    return checker
