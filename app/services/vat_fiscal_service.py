"""Journal fiscal TVA et historique des déclarations."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models_accounting import VatDeclaration, VatPeriod
from app.models_erp import JournalEntry, JournalLine


VAT_PREFIXES = ("443", "445", "444")


def list_vat_declarations(db: Session, limit: int = 48) -> list[dict]:
    rows = (
        db.query(VatDeclaration, VatPeriod)
        .join(VatPeriod, VatPeriod.id == VatDeclaration.vat_period_id)
        .order_by(VatPeriod.year.desc(), VatPeriod.period.desc())
        .limit(limit)
        .all()
    )
    out = []
    for decl, period in rows:
        out.append({
            "id": decl.id,
            "year": period.year,
            "period": period.period,
            "period_type": period.period_type,
            "status": period.status,
            "collected": decl.collected_amount,
            "deductible": decl.deductible_amount,
            "net": decl.net_amount,
            "position": decl.position,
            "declared_at": decl.declared_at,
            "journal_entry_id": period.journal_entry_id,
        })
    return out


def vat_fiscal_journal(
    db: Session,
    *,
    fiscal_year: int | None = None,
    period: int | None = None,
) -> dict:
    """Lignes journal sur comptes 443, 445, 444."""
    q = (
        db.query(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalEntry.status == "validée")
    )
    if fiscal_year:
        q = q.filter(JournalEntry.fiscal_year == fiscal_year)
    if period:
        q = q.filter(JournalEntry.period == period)

    lines = []
    totals = {p: {"debit": 0.0, "credit": 0.0} for p in VAT_PREFIXES}

    for ln, ent in q.order_by(JournalEntry.date, JournalLine.id).all():
        code = ln.account_code or ""
        if not any(code.startswith(p) for p in VAT_PREFIXES):
            continue
        prefix = code[:3]
        lines.append({
            "date": str(ent.date) if ent.date else "",
            "journal": ent.journal,
            "reference": ent.reference,
            "account_code": code,
            "label": ln.label or ent.label,
            "debit": ln.debit or 0,
            "credit": ln.credit or 0,
        })
        if prefix in totals:
            totals[prefix]["debit"] += ln.debit or 0
            totals[prefix]["credit"] += ln.credit or 0

    return {
        "fiscal_year": fiscal_year,
        "period": period,
        "lines": lines,
        "totals": {
            k: {
                "debit": round(v["debit"], 2),
                "credit": round(v["credit"], 2),
                "balance": round(v["debit"] - v["credit"], 2),
            }
            for k, v in totals.items()
        },
        "line_count": len(lines),
    }
