"""Paie OHADA simplifiée — bulletins mensuels."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models_erp import Employee, JournalEntry, JournalLine
from app.models_accounting import PayrollRun, SalaryLine
from app.fiscal_service import assert_fiscal_year_open
from app.services.accounting_reports import validate_entry_balance


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def generate_payroll_run(db: Session, year: int, month: int) -> PayrollRun:
    assert_fiscal_year_open(db, year)
    existing = db.query(PayrollRun).filter(
        PayrollRun.period_year == year,
        PayrollRun.period_month == month,
    ).first()
    if existing and existing.status != "draft":
        return existing
    if existing:
        db.query(SalaryLine).filter(SalaryLine.payroll_run_id == existing.id).delete()
        run = existing
    else:
        run = PayrollRun(period_year=year, period_month=month, status="draft")
        db.add(run)
        db.flush()

    employees = db.query(Employee).filter(Employee.status == "actif").all()
    total_gross = total_net = total_charges = 0.0
    for emp in employees:
        gross = float(emp.salary_base or 0)
        emp_charges = round(gross * 0.18, 2)
        emp_tax = round(gross * 0.10, 2)
        employer = round(gross * 0.22, 2)
        net = round(gross - emp_charges - emp_tax, 2)
        db.add(SalaryLine(
            payroll_run_id=run.id,
            employee_id=emp.id,
            gross_salary=gross,
            net_salary=net,
            employee_charges=emp_charges,
            employer_charges=employer,
            withholding_tax=emp_tax,
        ))
        total_gross += gross
        total_net += net
        total_charges += emp_charges + employer

    run.total_gross = round(total_gross, 2)
    run.total_net = round(total_net, 2)
    run.total_charges = round(total_charges, 2)
    db.commit()
    db.refresh(run)
    return run


def validate_payroll_run(db: Session, run_id: int) -> dict:
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not run:
        raise ValueError("Bulletin de paie introuvable")
    if run.status == "validated":
        return {"ok": True, "journal_entry_id": run.journal_entry_id}

    lines_db = db.query(SalaryLine).filter(SalaryLine.payroll_run_id == run.id).all()
    journal_lines = []
    total_gross = 0.0
    total_net = 0.0
    total_social = 0.0
    total_withholding = 0.0
    for ln in lines_db:
        g = float(ln.gross_salary or 0)
        n = float(ln.net_salary or 0)
        ec = float(ln.employee_charges or 0)
        er = float(ln.employer_charges or 0)
        tax = float(ln.withholding_tax or 0)
        total_gross += g
        total_net += n
        total_social += ec + er
        total_withholding += tax
        journal_lines.append({
            "account_code": ln.account_expense or "661100",
            "debit": round(g + er, 2),
            "credit": 0,
            "label": f"Salaire {ln.employee_id}",
        })

    journal_lines.append({
        "account_code": "422000",
        "debit": 0,
        "credit": round(total_net, 2),
        "label": "Rémunérations dues",
    })
    journal_lines.append({
        "account_code": "431100",
        "debit": 0,
        "credit": round(total_social, 2),
        "label": "Charges sociales",
    })
    if total_withholding > 0:
        journal_lines.append({
            "account_code": "447000",
            "debit": 0,
            "credit": round(total_withholding, 2),
            "label": "Retenue à la source salaires",
        })

    if not validate_entry_balance(journal_lines):
        raise ValueError("Écriture de paie non équilibrée")

    ed = date(run.period_year, run.period_month, 28)
    entry = JournalEntry(
        date=ed,
        journal="OD",
        reference=f"PAIE-{run.period_year}-{run.period_month:02d}",
        label=f"Paie {run.period_month:02d}/{run.period_year}",
        status="validée",
        fiscal_year=run.period_year,
        period=run.period_month,
        source_type="payroll",
        source_id=run.id,
    )
    db.add(entry)
    db.flush()
    for jl in journal_lines:
        db.add(JournalLine(
            entry_id=entry.id,
            account_code=jl["account_code"],
            debit=jl["debit"],
            credit=jl["credit"],
            label=jl["label"],
        ))
    run.status = "validated"
    run.journal_entry_id = entry.id
    run.validated_at = _now()
    db.commit()
    return {"ok": True, "journal_entry_id": entry.id, "total_gross": total_gross, "total_net": total_net}
