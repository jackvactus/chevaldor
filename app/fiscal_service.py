"""Exercices fiscaux — clôture et verrouillage des écritures."""
import json
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models_prefs import SystemSettings


def _closed_years(db: Session) -> set[int]:
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if not row:
        return set()
    raw = getattr(row, "closed_fiscal_years_json", None) or "[]"
    try:
        data = json.loads(raw)
        return {int(y) for y in data if y is not None}
    except Exception:
        return set()


def is_fiscal_year_closed(db: Session, fiscal_year: int | None) -> bool:
    if not fiscal_year:
        return False
    return int(fiscal_year) in _closed_years(db)


def assert_fiscal_year_open(db: Session, fiscal_year: int | None):
    if is_fiscal_year_closed(db, fiscal_year):
        raise HTTPException(400, f"L'exercice {fiscal_year} est clôturé. Réouverture requise en paramètres.")


def close_fiscal_year(db: Session, year: int) -> list[int]:
    closed = _closed_years(db)
    closed.add(int(year))
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if not row:
        raise HTTPException(500, "Paramètres système introuvables")
    row.closed_fiscal_years_json = json.dumps(sorted(closed))
    return sorted(closed)


def reopen_fiscal_year(db: Session, year: int) -> list[int]:
    closed = _closed_years(db)
    closed.discard(int(year))
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if not row:
        raise HTTPException(500, "Paramètres système introuvables")
    row.closed_fiscal_years_json = json.dumps(sorted(closed))
    return sorted(closed)


def list_closed_fiscal_years(db: Session) -> list[int]:
    return sorted(_closed_years(db))


def get_default_vat_rate(db: Session) -> float:
    """Taux TVA par défaut depuis Paramètres > Comptabilité (0 % si non configuré)."""
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if row and row.taxes_json:
        try:
            taxes = json.loads(row.taxes_json)
            for t in taxes:
                if t.get("default"):
                    return float(t.get("rate", 0) or 0)
            if taxes:
                return float(taxes[0].get("rate", 0) or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return 0.0


def resolve_vat_rate(
    db: Session,
    *,
    line_rate: float | None = None,
    doc_rate: float | None = None,
) -> float:
    """Taux TVA ligne > document > paramètres système (jamais de valeur codée en dur)."""
    for raw in (line_rate, doc_rate):
        if raw is None or raw == "":
            continue
        try:
            v = float(raw)
            if v >= 0:
                return v
        except (TypeError, ValueError):
            continue
    return get_default_vat_rate(db)


def amounts_from_ht(ht: float, vat_rate: float) -> tuple[float, float, float]:
    """Calcule (HT, TVA, TTC) — le montant documentaire est toujours HT."""
    base = round(float(ht or 0), 2)
    rate = float(vat_rate or 0)
    tva = round(base * rate / 100, 2)
    return base, tva, round(base + tva, 2)
