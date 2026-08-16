"""Validateurs métier réutilisables — schémas Pydantic."""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Optional

from pydantic import Field, field_validator

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^\+?[\d\s().-]{8,20}$")
FORBIDDEN_TEXT = re.compile(r"[<>{}\[\]\\]")


def clean_text(value: str, *, min_len: int = 0, max_len: int = 500, upper: bool = False) -> str:
    v = (value or "").strip()
    if FORBIDDEN_TEXT.search(v):
        raise ValueError("Caractères interdits dans le texte")
    if len(v) < min_len:
        raise ValueError(f"Minimum {min_len} caractères")
    if len(v) > max_len:
        raise ValueError(f"Maximum {max_len} caractères")
    return v.upper() if upper else v


def clean_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    if not EMAIL_RE.match(v):
        raise ValueError("Email invalide")
    return v


def clean_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    digits = re.sub(r"\D", "", v)
    if len(digits) < 8:
        raise ValueError("Numéro de téléphone invalide")
    if not PHONE_RE.match(v) and len(digits) >= 8:
        return v
    if not PHONE_RE.match(v):
        raise ValueError("Numéro de téléphone invalide")
    return v


def validate_due_after_invoice(due: Optional[date], invoice: Optional[date]) -> Optional[date]:
    if due and invoice and due < invoice:
        raise ValueError("La date d'échéance ne peut pas être avant la date de facture")
    return due


MoneyAmount = Annotated[float, Field(ge=0)]
PercentRate = Annotated[float, Field(ge=0, le=100)]
PositiveQty = Annotated[float, Field(ge=0)]
