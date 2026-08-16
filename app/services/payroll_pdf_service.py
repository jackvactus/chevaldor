"""Bulletins de paie PDF et export CNSS (Togo)."""
from __future__ import annotations

import csv
import io
from datetime import date

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer
from sqlalchemy.orm import Session

from app.models_accounting import PayrollRun, SalaryLine
from app.models_erp import Employee
from app.services.pdf_theme import build_platypus_report, data_table, fmt_money, _styles


def _emp_name(emp: Employee) -> str:
    return f"{emp.firstname or ''} {emp.lastname or ''}".strip() or emp.matricule or f"#{emp.id}"


def payroll_run_pdf(db: Session, run_id: int) -> bytes:
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not run:
        raise ValueError("Bulletin de paie introuvable")

    employees = {e.id: e for e in db.query(Employee).all()}
    lines = db.query(SalaryLine).filter(SalaryLine.payroll_run_id == run_id).all()
    period = f"{run.period_month:02d}/{run.period_year}"
    st = _styles()

    story = [
        Paragraph(f"Période : {period} — Statut : {run.status}", st["note"]),
        Spacer(1, 6 * mm),
        data_table(
            ["Salarié", "Brut", "Net", "Charges sal.", "Charges pat."],
            [
                [
                    (_emp_name(employees.get(ln.employee_id)) if employees.get(ln.employee_id) else f"#{ln.employee_id}"),
                    fmt_money(ln.gross_salary),
                    fmt_money(ln.net_salary),
                    fmt_money(ln.employee_charges),
                    fmt_money(ln.employer_charges),
                ]
                for ln in lines
            ],
            col_widths=[55 * mm, 28 * mm, 28 * mm, 28 * mm, 28 * mm],
        ),
        Spacer(1, 8 * mm),
        Paragraph(
            f"Totaux — Brut {fmt_money(run.total_gross)} · Net {fmt_money(run.total_net)} · Charges {fmt_money(run.total_charges)}",
            st["section"],
        ),
    ]
    kpis = [
        {"title": "Brut total", "value": fmt_money(run.total_gross)},
        {"title": "Net total", "value": fmt_money(run.total_net)},
        {"title": "Effectif", "value": str(len(lines))},
    ]
    return build_platypus_report(f"Bulletins de paie {period}", date.today().strftime("%d/%m/%Y"), story, kpis=kpis)


def cnss_export_csv(db: Session, run_id: int) -> str:
    """Export déclaration CNSS simplifiée (CSV)."""
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not run:
        raise ValueError("Bulletin introuvable")

    employees = {e.id: e for e in db.query(Employee).all()}
    lines = db.query(SalaryLine).filter(SalaryLine.payroll_run_id == run_id).all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([
        "periode", "matricule", "nom", "brut", "cotisation_salariale",
        "cotisation_patronale", "net", "cnss_numero",
    ])
    period = f"{run.period_year}-{run.period_month:02d}"
    for ln in lines:
        emp = employees.get(ln.employee_id)
        w.writerow([
            period,
            (emp.matricule if emp else "") or f"EMP{ln.employee_id}",
            (_emp_name(emp) if emp else ""),
            round(ln.gross_salary or 0, 2),
            round(ln.employee_charges or 0, 2),
            round(ln.employer_charges or 0, 2),
            round(ln.net_salary or 0, 2),
            "",
        ])
    return buf.getvalue()
