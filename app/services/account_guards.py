"""Garde-fous suppression comptes PCG."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models_erp import JournalLine


def assert_account_deletable(db: Session, account_code: str):
    used = (
        db.query(JournalLine.id)
        .filter(JournalLine.account_code == account_code)
        .limit(1)
        .first()
    )
    if used:
        raise HTTPException(
            400,
            f"Le compte {account_code} est utilisé dans des écritures comptables et ne peut pas être supprimé.",
        )
