"""PDF logistique — bordereau livraison, rapport flotte (thème marque Peya, cohérent avec devis/factures)."""
from __future__ import annotations

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from app.models_enterprise_ops import LogisticsShipment, LogisticsVehicle
from app.services.pdf_theme import PeyaBrand, build_platypus_report, data_table, fmt_money


def _info_table(rows: list[list[str]]) -> Table:
    t = Table(rows, colWidths=[50 * mm, 110 * mm])
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


def render_shipment_pdf(ship: LogisticsShipment, db) -> bytes:
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>Référence :</b> {ship.reference}", styles["Normal"]),
        Paragraph(f"<b>Trajet :</b> {ship.origin or '—'} → {ship.destination or '—'}", styles["Normal"]),
        Paragraph(f"<b>Statut :</b> {ship.status}", styles["Normal"]),
        Spacer(1, 10),
    ]
    rows = [
        ["Poids (kg)", f"{float(ship.weight_kg or 0):,.0f}".replace(",", " ")],
        ["Coût transport", fmt_money(ship.cost)],
        ["Date prévue", str(ship.scheduled_date or "—")],
        ["Date livraison", str(ship.delivered_date or "—")],
    ]
    if ship.vehicle_id:
        v = db.query(LogisticsVehicle).filter(LogisticsVehicle.id == ship.vehicle_id).first()
        if v:
            rows.append(["Véhicule", f"{v.plate} — {v.brand} {v.model}"])
    story.append(_info_table(rows))
    return build_platypus_report("Bordereau de livraison", ship.reference or "", story)


def render_logistics_report_pdf(db) -> bytes:
    from collections import Counter

    vehicles = db.query(LogisticsVehicle).all()
    shipments = db.query(LogisticsShipment).all()
    vstat = Counter(v.status for v in vehicles)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Flotte : <b>{len(vehicles)}</b> véhicules — Livraisons : <b>{len(shipments)}</b>", styles["Normal"]),
        Spacer(1, 14),
        Paragraph("<b>État de la flotte</b>", styles["Heading3"]),
        Spacer(1, 4),
    ]
    drows = [[k, str(v)] for k, v in vstat.items()]
    story.append(data_table(["Statut", "Nombre"], drows, col_widths=[80 * mm, 40 * mm], numeric_from=1))
    return build_platypus_report("Rapport logistique", f"{len(vehicles)} véhicule(s) · {len(shipments)} livraison(s)", story)
