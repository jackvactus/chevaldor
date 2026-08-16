"""PDF RH — fiche employé, rapport synthèse (thème marque Peya, cohérent avec devis/factures)."""
from __future__ import annotations

from datetime import date

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from app.models_erp import Employee, LeaveRequest
from app.services.pdf_theme import PeyaBrand, build_platypus_report, data_table, fmt_money


def _info_table(rows: list[list[str]]) -> Table:
    t = Table(rows, colWidths=[45 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PeyaBrand.CREAM),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), PeyaBrand.TEXT),
        ("GRID", (0, 0), (-1, -1), 0.4, PeyaBrand.GREY_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def render_employee_pdf(emp: Employee, db) -> bytes:
    styles = getSampleStyleSheet()
    name = f"{emp.firstname or ''} {emp.lastname or ''}".strip() or emp.matricule
    story = [Paragraph(f"<b>{name}</b> — Matricule {emp.matricule or '—'}", styles["Heading2"]), Spacer(1, 8)]
    story.append(_info_table([
        ["Département", emp.department or "—"],
        ["Poste", emp.position or "—"],
        ["Email", emp.email or "—"],
        ["Téléphone", emp.phone or "—"],
        ["Date embauche", str(emp.hire_date or "—")],
        ["Salaire de base", fmt_money(emp.salary_base)],
        ["Statut", emp.status or "—"],
    ]))
    if emp.notes:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>Notes</b><br/>{emp.notes}", styles["Normal"]))
    leaves = db.query(LeaveRequest).filter(LeaveRequest.employee_id == emp.id).limit(8).all()
    if leaves:
        story.append(Spacer(1, 14))
        story.append(Paragraph("<b>Historique congés récents</b>", styles["Heading3"]))
        story.append(Spacer(1, 4))
        lrows = [
            [f"{l.start_date} → {l.end_date}", l.type or "—", str(l.days or 0), l.status or "—"]
            for l in leaves
        ]
        story.append(data_table(
            ["Période", "Type", "Jours", "Statut"], lrows,
            col_widths=[55 * mm, 35 * mm, 20 * mm, 35 * mm], numeric_from=2,
        ))
    return build_platypus_report("Fiche employé", name, story)


def render_hr_report_pdf(db) -> bytes:
    from collections import Counter
    from app.models_enterprise_ops import HrRecruitment

    employees = db.query(Employee).all()
    active = [e for e in employees if (e.status or "") == "actif"]
    depts = Counter((e.department or "—") for e in active)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Effectif total : <b>{len(employees)}</b> — Actifs : <b>{len(active)}</b>", styles["Normal"]),
        Paragraph(f"Masse salariale : <b>{fmt_money(sum(float(e.salary_base or 0) for e in active))}</b>", styles["Normal"]),
        Paragraph(f"Recrutements ouverts : <b>{db.query(HrRecruitment).filter(HrRecruitment.status == 'ouvert').count()}</b>", styles["Normal"]),
        Spacer(1, 14),
        Paragraph("<b>Répartition par département</b>", styles["Heading3"]),
        Spacer(1, 4),
    ]
    drows = [[name, str(cnt)] for name, cnt in depts.most_common(15)]
    story.append(data_table(["Département", "Effectif"], drows, col_widths=[100 * mm, 40 * mm], numeric_from=1))
    return build_platypus_report("Rapport RH — Synthèse", f"{len(employees)} employé(s) au {date.today().strftime('%d/%m/%Y')}", story)
