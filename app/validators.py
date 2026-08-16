"""Validateurs Pydantic — montants XOF (entiers) et dates FR."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import BeforeValidator, Field

from app.field_validators import clean_email, clean_phone, clean_text, validate_due_after_invoice

_DATE_FR = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def parse_montant_xof(value: Any, *, allow_negative: bool = False) -> int:
    """Normalise un montant FCFA en entier (sans centimes)."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError("Montant invalide")
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        n = int(round(value))
    elif isinstance(value, str):
        s = value.replace("\u00a0", "").replace(" ", "")
        if not s:
            return 0
        if re.search(r"[.,]\d{1,2}$", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(".", "").replace(",", "")
        try:
            n = int(round(float(s)))
        except ValueError as e:
            raise ValueError("Montant FCFA invalide") from e
    else:
        raise ValueError("Montant FCFA invalide")
    if not allow_negative and n < 0:
        raise ValueError("Le montant ne peut pas être négatif")
    return n


def parse_date_input(value: Any) -> Optional[date]:
    """Accepte ISO, JJ/MM/AAAA, None, ''."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    m = _DATE_FR.match(s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError as e:
            raise ValueError("Date invalide (JJ/MM/AAAA)") from e
    try:
        return date.fromisoformat(s[:10])
    except ValueError as e:
        raise ValueError("Date invalide — utilisez JJ/MM/AAAA ou AAAA-MM-JJ") from e


def _montant_validator(v: Any) -> int:
    return parse_montant_xof(v, allow_negative=False)


def _qty_validator(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, str):
        v = v.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    n = float(v)
    if n < 0:
        raise ValueError("La quantité ne peut pas être négative")
    return n


MontantXOF = Annotated[int, BeforeValidator(_montant_validator), Field(ge=0)]
QuantitePos = Annotated[float, BeforeValidator(_qty_validator), Field(ge=0)]
DateFR = Annotated[Optional[date], BeforeValidator(parse_date_input)]

__all__ = [
    "MontantXOF",
    "QuantitePos",
    "DateFR",
    "parse_montant_xof",
    "parse_date_input",
    "clean_text",
    "clean_email",
    "clean_phone",
    "validate_due_after_invoice",
]
