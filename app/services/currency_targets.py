"""Conversion objectifs / montants de référence XOF vers les devises actives."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models_currency import Currency

# Devises affichées sous l'objectif An 1 (en plus du FCFA)
TARGET_DISPLAY_CODES = ("EUR", "USD", "GBP", "CAD", "CHF", "CNY", "NGN", "GHS", "XAF")


def _fmt_amount(amount: float, decimals: int, symbol: str, code: str) -> str:
    if decimals <= 0:
        n = int(round(amount))
        body = f"{n:,}".replace(",", " ")
    else:
        body = f"{amount:,.{decimals}f}".replace(",", " ").replace(".", ",")
    if code == "XOF":
        return f"{body} FCFA"
    if symbol and symbol not in body:
        return f"{body} {symbol}".strip()
    return f"{body} {code}".strip()


def convert_xof_to_currency(amount_xof: float, currency: Currency) -> float:
    if currency.code == "XOF" or not currency.rate_to_base:
        return amount_xof
    return amount_xof / float(currency.rate_to_base)


def build_target_currency_breakdown(
    db: Session,
    target_xof: float,
    *,
    display_codes: tuple[str, ...] = TARGET_DISPLAY_CODES,
) -> list[dict]:
    """Montant objectif exprimé dans chaque devise (taux rate_to_base = XOF par unité étrangère)."""
    from app.routers.currencies import ensure_currencies_seeded

    ensure_currencies_seeded(db)
    currencies = (
        db.query(Currency)
        .filter(Currency.is_active == True)
        .order_by(Currency.is_default.desc(), Currency.code)
        .all()
    )
    by_code = {c.code: c for c in currencies}
    out: list[dict] = []

    xof = by_code.get("XOF")
    if xof:
        out.append({
            "code": "XOF",
            "name": xof.name,
            "symbol": "FCFA",
            "amount": float(target_xof),
            "formatted": _fmt_amount(target_xof, 0, "FCFA", "XOF"),
            "is_base": True,
        })

    for code in display_codes:
        if code == "XOF":
            continue
        c = by_code.get(code)
        if not c:
            continue
        amt = convert_xof_to_currency(target_xof, c)
        out.append({
            "code": c.code,
            "name": c.name,
            "symbol": c.symbol or c.code,
            "amount": round(amt, c.decimals),
            "formatted": _fmt_amount(amt, c.decimals, c.symbol or "", c.code),
            "is_base": False,
            "rate_to_base": c.rate_to_base,
        })
    return out


def pick_target_display(breakdown: list[dict], currency_code: str = "XOF") -> dict | None:
    code = (currency_code or "XOF").upper()
    for row in breakdown:
        if row.get("code") == code:
            return row
    return breakdown[0] if breakdown else None
