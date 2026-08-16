"""Relevés bancaires — import CSV et rapprochement."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models_erp import BankStatement, BankStatementLine, TreasuryMovement, BankAccount


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def import_bank_csv(
    db: Session,
    bank_account_id: int,
    content: str,
    *,
    filename: str = "releve.csv",
    delimiter: str = ";",
) -> dict:
    bank = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not bank:
        raise ValueError("Compte bancaire introuvable")

    stmt = BankStatement(
        bank_account_id=bank_account_id,
        filename=filename,
        imported_at=_now(),
        status="imported",
    )
    db.add(stmt)
    db.flush()

    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        raise ValueError("Fichier CSV vide")

    header = [c.lower().strip() for c in rows[0]]
    data_rows = rows[1:] if any(k in "".join(header) for k in ("date", "montant", "amount", "libelle")) else rows

    def col(names: list[str], row: list[str], default="") -> str:
        for name in names:
            if name in header:
                idx = header.index(name)
                if idx < len(row):
                    return row[idx]
        return default

    imported = 0
    dates: list[date] = []
    for row in data_rows:
        if not row or all(not str(c).strip() for c in row):
            continue
        d_raw = col(["date", "date_operation", "date opération"], row, row[0] if row else "")
        label = col(["libelle", "libellé", "label", "description"], row, row[1] if len(row) > 1 else "")
        amt_raw = col(["montant", "amount", "credit", "debit"], row, row[-1] if row else "0")
        ref = col(["reference", "référence", "ref"], row, "")
        try:
            amt = float(str(amt_raw).replace(" ", "").replace(",", "."))
        except ValueError:
            continue
        d = _parse_date(d_raw) or date.today()
        dates.append(d)
        db.add(BankStatementLine(
            statement_id=stmt.id,
            line_date=d,
            label=label[:200],
            amount=amt,
            reference=ref[:80],
        ))
        imported += 1

    if dates:
        stmt.period_start = min(dates)
        stmt.period_end = max(dates)
    db.commit()
    return {"ok": True, "statement_id": stmt.id, "lines": imported}


def match_statement_line(
    db: Session,
    line_id: int,
    *,
    treasury_movement_id: int | None = None,
) -> dict:
    line = db.query(BankStatementLine).filter(BankStatementLine.id == line_id).first()
    if not line:
        raise ValueError("Ligne relevé introuvable")
    if treasury_movement_id:
        mov = db.query(TreasuryMovement).filter(TreasuryMovement.id == treasury_movement_id).first()
        if not mov:
            raise ValueError("Mouvement trésorerie introuvable")
        mov.reconciled = True
        line.treasury_movement_id = mov.id
    line.reconciled = True
    db.commit()
    return {"ok": True, "line_id": line.id, "reconciled": True}


def auto_match_statement(db: Session, statement_id: int) -> dict:
    """Rapprochement automatique par montant + référence facture."""
    lines = db.query(BankStatementLine).filter(
        BankStatementLine.statement_id == statement_id,
        BankStatementLine.reconciled == False,  # noqa: E712
    ).all()
    stmt = db.query(BankStatement).filter(BankStatement.id == statement_id).first()
    if not stmt:
        raise ValueError("Relevé introuvable")

    moves = db.query(TreasuryMovement).filter(
        TreasuryMovement.bank_account_id == stmt.bank_account_id,
        TreasuryMovement.reconciled == False,  # noqa: E712
    ).all()
    from app.models import Invoice
    invoices = {inv.number: inv for inv in db.query(Invoice).filter(Invoice.number.isnot(None)).all() if inv.number}
    matched = 0
    for ln in lines:
        if ln.reconciled:
            continue
        ref = (ln.reference or ln.label or "").upper()
        # Match par référence facture dans libellé
        for num, inv in invoices.items():
            if num and num.upper() in ref:
                balance = float(inv.amount or 0) - float(inv.paid or 0)
                if abs(abs(ln.amount or 0) - balance) < 1.01 or abs(abs(ln.amount or 0) - float(inv.amount or 0)) < 1.01:
                    ln.reconciled = True
                    matched += 1
                    break
        if ln.reconciled:
            continue
        for m in moves:
            if m.reconciled:
                continue
            if abs(abs(m.amount or 0) - abs(ln.amount or 0)) < 1.01:
                m.reconciled = True
                ln.reconciled = True
                ln.treasury_movement_id = m.id
                matched += 1
                break
    db.commit()
    return {"ok": True, "matched": matched, "total_lines": len(lines)}


def import_bank_excel(db: Session, bank_account_id: int, content: bytes, *, filename: str = "releve.xlsx") -> dict:
    """Import relevé Excel (.xlsx)."""
    try:
        import openpyxl
    except ImportError:
        raise ValueError("openpyxl requis pour l'import Excel")
    bank = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not bank:
        raise ValueError("Compte bancaire introuvable")
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Fichier Excel vide")
    header = [str(c or "").lower().strip() for c in rows[0]]

    def col(names: list[str], row: tuple, default=""):
        for name in names:
            if name in header:
                idx = header.index(name)
                if idx < len(row):
                    return row[idx]
        return default

    stmt = BankStatement(
        bank_account_id=bank_account_id,
        filename=filename,
        imported_at=_now(),
        status="imported",
    )
    db.add(stmt)
    db.flush()
    imported = 0
    dates: list[date] = []
    for row in rows[1:]:
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        d_raw = col(["date", "date_operation"], row, row[0])
        label = str(col(["libelle", "libellé", "label", "description"], row, row[1] if len(row) > 1 else "") or "")
        amt_raw = col(["montant", "amount", "credit", "debit"], row, row[-1] if row else 0)
        ref = str(col(["reference", "référence", "ref"], row, "") or "")
        try:
            if isinstance(d_raw, datetime):
                d = d_raw.date()
            elif hasattr(d_raw, "year") and hasattr(d_raw, "month"):
                d = d_raw
            else:
                d = _parse_date(str(d_raw)) or date.today()
        except Exception:
            d = date.today()
        try:
            amt = float(str(amt_raw).replace(" ", "").replace(",", "."))
        except (ValueError, TypeError):
            continue
        dates.append(d if isinstance(d, date) else date.today())
        db.add(BankStatementLine(
            statement_id=stmt.id,
            line_date=d if isinstance(d, date) else date.today(),
            label=label[:200],
            amount=amt,
            reference=ref[:80],
        ))
        imported += 1
    if dates:
        stmt.period_start = min(dates)
        stmt.period_end = max(dates)
    db.commit()
    return {"ok": True, "statement_id": stmt.id, "lines": imported, "format": "excel"}


def import_bank_ofx(db: Session, bank_account_id: int, content: str, *, filename: str = "releve.ofx") -> dict:
    """Import relevé OFX (parser simplifié STMTTRN)."""
    import re
    bank = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not bank:
        raise ValueError("Compte bancaire introuvable")
    stmt = BankStatement(
        bank_account_id=bank_account_id,
        filename=filename,
        imported_at=_now(),
        status="imported",
    )
    db.add(stmt)
    db.flush()
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", content, re.DOTALL | re.IGNORECASE)
    imported = 0
    dates: list[date] = []
    for block in blocks:
        def tag(name: str) -> str:
            m = re.search(rf"<{name}>([^<\n]+)", block, re.IGNORECASE)
            return (m.group(1).strip() if m else "")

        d_raw = tag("DTPOSTED")[:8]
        try:
            d = datetime.strptime(d_raw, "%Y%m%d").date() if len(d_raw) >= 8 else date.today()
        except ValueError:
            d = date.today()
        try:
            amt = float(tag("TRNAMT").replace(",", "."))
        except ValueError:
            continue
        label = tag("NAME") or tag("MEMO") or "OFX"
        ref = tag("FITID") or tag("CHECKNUM") or ""
        dates.append(d)
        db.add(BankStatementLine(
            statement_id=stmt.id,
            line_date=d,
            label=label[:200],
            amount=amt,
            reference=ref[:80],
        ))
        imported += 1
    if dates:
        stmt.period_start = min(dates)
        stmt.period_end = max(dates)
    db.commit()
    return {"ok": True, "statement_id": stmt.id, "lines": imported, "format": "ofx"}


def list_statements(db: Session) -> list[dict]:
    banks = {b.id: b.name for b in db.query(BankAccount).all()}
    out = []
    for s in db.query(BankStatement).order_by(BankStatement.id.desc()).limit(50).all():
        cnt = db.query(BankStatementLine).filter(BankStatementLine.statement_id == s.id).count()
        rec = db.query(BankStatementLine).filter(
            BankStatementLine.statement_id == s.id,
            BankStatementLine.reconciled == True,  # noqa: E712
        ).count()
        out.append({
            "id": s.id,
            "bank_account_id": s.bank_account_id,
            "bank_name": banks.get(s.bank_account_id, ""),
            "filename": s.filename,
            "imported_at": s.imported_at,
            "lines": cnt,
            "reconciled": rec,
            "period_start": str(s.period_start) if s.period_start else "",
            "period_end": str(s.period_end) if s.period_end else "",
        })
    return out


def statement_lines(db: Session, statement_id: int) -> list[dict]:
    return [
        {
            "id": ln.id,
            "date": str(ln.line_date) if ln.line_date else "",
            "label": ln.label,
            "amount": ln.amount,
            "reference": ln.reference,
            "reconciled": bool(ln.reconciled),
            "treasury_movement_id": ln.treasury_movement_id,
        }
        for ln in db.query(BankStatementLine).filter(BankStatementLine.statement_id == statement_id).all()
    ]
