"""API devises et taux de change."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_permission
from app.database import get_db
from app.models import User
from app.models_currency import Currency, ExchangeRateHistory
from app.seed_currencies import DEFAULT_CURRENCIES
from app.services.audit_log import log_audit

router = APIRouter(prefix="/api/currencies", tags=["currencies"])


class CurrencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    symbol: str
    rate_to_base: float
    is_active: bool
    is_default: bool
    decimals: int


class CurrencyIn(BaseModel):
    code: str
    name: str = ""
    symbol: str = ""
    rate_to_base: float = 1.0
    is_active: bool = True
    decimals: int = 2


class CurrencyUpdate(BaseModel):
    name: Optional[str] = None
    symbol: Optional[str] = None
    rate_to_base: Optional[float] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    decimals: Optional[int] = None


def ensure_currencies_seeded(db: Session):
    if db.query(Currency).count() > 0:
        return
    for code, name, symbol, rate, decimals, active in DEFAULT_CURRENCIES:
        is_def = code == "XOF"
        db.add(Currency(
            code=code, name=name, symbol=symbol, rate_to_base=rate,
            decimals=decimals, is_active=active, is_default=is_def,
        ))
    db.commit()


@router.get("", response_model=List[CurrencyOut])
def list_currencies(
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ensure_currencies_seeded(db)
    q = db.query(Currency).order_by(Currency.is_default.desc(), Currency.code)
    if active_only:
        q = q.filter(Currency.is_active == True)
    return q.all()


@router.post("", response_model=CurrencyOut)
def create_currency(
    data: CurrencyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("currencies.manage")),
):
    ensure_currencies_seeded(db)
    code = data.code.strip().upper()
    if db.query(Currency).filter(Currency.code == code).first():
        raise HTTPException(400, "Code devise déjà utilisé")
    obj = Currency(
        code=code,
        name=data.name,
        symbol=data.symbol,
        rate_to_base=data.rate_to_base,
        is_active=data.is_active,
        decimals=data.decimals,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    log_audit(db, "create", "paramètres", "currency", obj.id, code, user.id, user.email, old_value="", new_value=code)
    return obj


@router.put("/{currency_id}", response_model=CurrencyOut)
def update_currency(
    currency_id: int,
    data: CurrencyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("currencies.manage")),
):
    obj = db.query(Currency).filter(Currency.id == currency_id).first()
    if not obj:
        raise HTTPException(404, "Devise introuvable")
    old_rate = obj.rate_to_base
    if data.name is not None:
        obj.name = data.name
    if data.symbol is not None:
        obj.symbol = data.symbol
    if data.rate_to_base is not None:
        obj.rate_to_base = data.rate_to_base
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        db.add(ExchangeRateHistory(
            currency_code=obj.code,
            rate=data.rate_to_base,
            recorded_at=now,
            source="manual",
        ))
    if data.is_active is not None:
        obj.is_active = data.is_active
    if data.decimals is not None:
        obj.decimals = data.decimals
    if data.is_default:
        db.query(Currency).update({Currency.is_default: False})
        obj.is_default = True
    db.commit()
    db.refresh(obj)
    if data.rate_to_base is not None and data.rate_to_base != old_rate:
        log_audit(
            db, "update", "paramètres", "currency", obj.id, obj.code,
            user.id, user.email,
            old_value=f"{old_rate}", new_value=f"{obj.rate_to_base}",
        )
    return obj


@router.get("/{code}/history")
def rate_history(
    code: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (
        db.query(ExchangeRateHistory)
        .filter(ExchangeRateHistory.currency_code == code.upper())
        .order_by(ExchangeRateHistory.id.desc())
        .limit(limit)
        .all()
    )
    return [{"rate": r.rate, "recorded_at": r.recorded_at, "source": r.source} for r in rows]
