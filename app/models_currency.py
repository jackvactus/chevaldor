"""Devises et taux de change."""
from sqlalchemy import Column, Integer, String, Float, Boolean, Text
from app.database import Base


class Currency(Base):
    __tablename__ = "currencies"
    id = Column(Integer, primary_key=True)
    code = Column(String(8), unique=True, nullable=False, index=True)
    name = Column(String, default="")
    symbol = Column(String, default="")
    rate_to_base = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    decimals = Column(Integer, default=0)


class ExchangeRateHistory(Base):
    __tablename__ = "exchange_rate_history"
    id = Column(Integer, primary_key=True)
    currency_code = Column(String(8), index=True)
    rate = Column(Float, default=1.0)
    recorded_at = Column(String, default="")
    source = Column(String, default="manual")
