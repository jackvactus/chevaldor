"""Thème PDF Peya Company — en-tête logo, KPI, tableaux et graphiques professionnels."""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.charts.barcharts import VerticalBarChart


class PeyaBrand:
    BROWN = colors.HexColor("#5C3D2E")
    ORANGE = colors.HexColor("#E8A317")
    GREEN = colors.HexColor("#4A7C4E")
    GREEN_LIGHT = colors.HexColor("#8BC34A")
    CREAM = colors.HexColor("#F8F5F0")
    GREY_BG = colors.HexColor("#F0F0EB")
    GREY_LINE = colors.HexColor("#D8D8D0")
    TEXT = colors.HexColor("#333333")
    TEXT_DIM = colors.HexColor("#666666")
    WHITE = colors.white
    BLUE = colors.HexColor("#2E5A88")
    BLUE_LIGHT = colors.HexColor("#A8C5E0")
    RED = colors.HexColor("#C45C4A")


def logo_path(db=None) -> Optional[Path]:
    from app.services.pdf_branding import get_active_logo_path, get_current_db
    return get_active_logo_path(db or get_current_db())


def fmt_money(n: float, suffix: str = " FCFA", *, compact: bool = False) -> str:
    """Montants FCFA entiers (espace milliers). compact=True pour rapports KPI (15 k)."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    if compact:
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:,.1f} M{suffix}".replace(",", " ")
        if abs(v) >= 1_000:
            return f"{v / 1_000:,.0f} k{suffix}".replace(",", " ")
    # Documents commerciaux : toujours le montant complet (ex. 15 000 FCFA)
    formatted = f"{abs(v):,.0f}".replace(",", " ")
    if v < 0:
        formatted = f"-{formatted}"
    return f"{formatted}{suffix}"


def _styles():
    base = getSampleStyleSheet()
    return {
        "section": ParagraphStyle(
            "PeyaSection",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=PeyaBrand.BROWN,
            spaceBefore=16,
            spaceAfter=10,
            borderPadding=0,
        ),
        "kpi_label": ParagraphStyle(
            "KpiLabel",
            parent=base["Normal"],
            fontSize=8,
            textColor=PeyaBrand.TEXT_DIM,
            leading=11,
        ),
        "kpi_value": ParagraphStyle(
            "KpiValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=PeyaBrand.BROWN,
            leading=20,
        ),
        "kpi_hint": ParagraphStyle(
            "KpiHint",
            parent=base["Normal"],
            fontSize=7,
            textColor=PeyaBrand.TEXT_DIM,
            leading=9,
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontSize=9,
            textColor=PeyaBrand.TEXT,
            leading=11,
        ),
        "cell_bold": ParagraphStyle(
            "CellBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=PeyaBrand.WHITE,
            leading=11,
        ),
        "cell_total": ParagraphStyle(
            "CellTotal",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=PeyaBrand.BROWN,
            leading=12,
        ),
        "note": ParagraphStyle(
            "PeyaNote",
            parent=base["Normal"],
            fontSize=8,
            textColor=PeyaBrand.TEXT_DIM,
            leading=10,
        ),
    }


def logo_flowable(width: float = 50 * mm, height: float = 22 * mm):
    lp = logo_path()
    if not lp:
        return None
    try:
        img = Image(str(lp), width=width, height=height)
        img.hAlign = "LEFT"
        return img
    except Exception:
        return None


def draw_brand_block(
    c: canvas.Canvas,
    logo_x: float,
    logo_y: float,
    *,
    logo_w: float = 24 * mm,
    logo_h: float = 24 * mm,
) -> dict:
    """
    Bloc marque Peya : logo carré (le PNG inclut déjà PEYA COMPANY).
    Sans logo : initiale + libellé PEYA / COMPANY en secours.
    logo_y = bord inférieur du logo. Retourne positions pour aligner le reste de l'en-tête.
    """
    lp = logo_path()
    has_logo = False
    if lp:
        try:
            c.drawImage(
                str(lp),
                logo_x,
                logo_y,
                width=logo_w,
                height=logo_h,
                preserveAspectRatio=True,
                mask="auto",
            )
            has_logo = True
        except Exception:
            lp = None

    cx = logo_x + logo_w / 2
    if has_logo:
        bottom_y = logo_y - 2 * mm
    else:
        c.setFillColor(PeyaBrand.BROWN)
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(cx, logo_y + logo_h * 0.38, "P")

        y_peya = logo_y - 3.5 * mm
        c.setFillColor(PeyaBrand.BROWN)
        c.setFont("Helvetica-Bold", 11.5)
        c.drawCentredString(cx, y_peya, "PEYA")

        y_company = y_peya - 4.5 * mm
        c.setFillColor(PeyaBrand.ORANGE)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString(cx, y_company, "COMPANY")

        y_line1 = y_company - 2.8 * mm
        c.setStrokeColor(PeyaBrand.ORANGE)
        c.setLineWidth(1.4)
        c.line(cx - 12 * mm, y_line1, cx + 12 * mm, y_line1)
        y_line2 = y_line1 - 1.1 * mm
        c.setLineWidth(0.4)
        c.line(cx - 10 * mm, y_line2, cx + 10 * mm, y_line2)
        bottom_y = y_line2 - 2 * mm

    return {
        "cx": cx,
        "bottom_y": bottom_y,
        "block_width": logo_w + 2 * mm,
        "text_x": logo_x + logo_w + 6 * mm,
    }


def draw_header_separator_line(
    c: canvas.Canvas,
    w: float,
    brand: dict,
    *,
    x_margin: float = 15 * mm,
    gap: float = 5 * mm,
) -> float:
    """Ligne orange pleine largeur, placée sous le bloc marque avec marge."""
    sep_y = brand["bottom_y"] - gap
    c.setStrokeColor(PeyaBrand.ORANGE)
    c.setLineWidth(2)
    c.line(x_margin, sep_y, w - x_margin, sep_y)
    return sep_y


def _header_footer(canvas_obj, doc, report_title: str, subtitle: str = ""):
    from app.services.pdf_branding import company_header_lines, get_branding_bundle, get_current_db

    canvas_obj.saveState()
    w, h = A4
    db = get_current_db()
    bundle = get_branding_bundle(db) if db else None
    footer_legal = (bundle.footer_legal if bundle else "") or "Peya Company ERP — Document confidentiel"
    company_lines = company_header_lines(db) if db else ["Peya Company"]

    canvas_obj.setFillColor(PeyaBrand.CREAM)
    canvas_obj.rect(0, h - 52 * mm, w, 52 * mm, fill=1, stroke=0)

    logo_x = 15 * mm
    logo_y = h - 36 * mm
    brand = draw_brand_block(canvas_obj, logo_x, logo_y)

    text_x = brand["text_x"]
    canvas_obj.setFillColor(PeyaBrand.BROWN)
    canvas_obj.setFont("Helvetica-Bold", 11)
    canvas_obj.drawString(text_x, h - 20 * mm, company_lines[0][:40].upper())

    if len(company_lines) > 1:
        canvas_obj.setFillColor(PeyaBrand.TEXT_DIM)
        canvas_obj.setFont("Helvetica", 7)
        y_co = h - 26 * mm
        for line in company_lines[1:3]:
            canvas_obj.drawString(text_x, y_co, line[:70])
            y_co -= 9

    canvas_obj.setFillColor(PeyaBrand.BROWN)
    canvas_obj.setFont("Helvetica-Bold", 13)
    canvas_obj.drawRightString(w - 15 * mm, h - 18 * mm, report_title)

    canvas_obj.setFillColor(PeyaBrand.TEXT_DIM)
    canvas_obj.setFont("Helvetica", 8)
    pdf_sub = (bundle.pdf_settings.get("header_subtitle") if bundle else "") or ""
    sub = subtitle or pdf_sub or (bundle.tagline if bundle and bundle.tagline else f"{company_lines[0]} · {date.today().strftime('%d/%m/%Y')}")
    canvas_obj.drawRightString(w - 15 * mm, h - 26 * mm, sub[:90])

    draw_header_separator_line(canvas_obj, w, brand)

    canvas_obj.setFillColor(PeyaBrand.TEXT_DIM)
    canvas_obj.setFont("Helvetica", 7)
    canvas_obj.drawString(15 * mm, 10 * mm, footer_legal[:120])
    canvas_obj.drawRightString(w - 15 * mm, 10 * mm, f"Page {canvas_obj.getPageNumber()}")
    canvas_obj.restoreState()


def _gauge_bar(progress: float, width: float = 120) -> Drawing:
    progress = max(0.0, min(float(progress or 0), 1.2))
    d = Drawing(width, 12)
    d.add(Rect(0, 2, width, 7, fillColor=PeyaBrand.GREY_LINE, strokeColor=None))
    fill_w = min(width, width * progress)
    if progress >= 1.0:
        fill_color = PeyaBrand.GREEN
    elif progress >= 0.6:
        fill_color = PeyaBrand.GREEN_LIGHT
    elif progress >= 0.35:
        fill_color = PeyaBrand.ORANGE
    else:
        fill_color = PeyaBrand.RED
    if fill_w > 0:
        d.add(Rect(0, 2, fill_w, 7, fillColor=fill_color, strokeColor=None))
    return d


def kpi_cards_table(kpis: list[dict]) -> Table:
    st = _styles()
    cells = []
    for k in kpis[:3]:
        title = k.get("title", "")
        value = k.get("value", "—")
        hint = k.get("hint", k.get("target_label", ""))
        prog = k.get("progress")
        parts = [
            [Paragraph(title, st["kpi_label"])],
            [Paragraph(str(value), st["kpi_value"])],
        ]
        if prog is not None:
            parts.append([_gauge_bar(prog)])
        if hint:
            parts.append([Paragraph(str(hint), st["kpi_hint"])])
        inner = Table(parts, colWidths=[56 * mm])
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PeyaBrand.WHITE),
            ("BOX", (0, 0), (-1, -1), 1, PeyaBrand.ORANGE),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        cells.append(inner)
    while len(cells) < 3:
        cells.append(Spacer(1, 1))
    row = Table([cells], colWidths=[61 * mm, 61 * mm, 61 * mm])
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), PeyaBrand.CREAM),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return row


def bar_chart_flowable(
    labels: list[str],
    series: list[tuple[str, list[float], Any]],
    width: float = 170 * mm,
    height: float = 55 * mm,
) -> Drawing | Paragraph:
    if not labels or not series or not any(any(v > 0 for v in s[1]) for s in series):
        st = _styles()
        return Paragraph(
            "<i>Aucune donnée graphique pour cette période.</i>",
            st["note"],
        )
    try:
        d = Drawing(width, height + 8 * mm)
        bc = VerticalBarChart()
        bc.x = 50
        bc.y = 22
        bc.height = height - 28 * mm
        bc.width = width - 65 * mm
        bc.data = [s[1] for s in series]
        bc.categoryNames = [str(l)[:14] for l in labels]
        bc.bars[0].fillColor = PeyaBrand.BLUE
        if len(series) > 1:
            bc.bars[1].fillColor = PeyaBrand.BLUE_LIGHT
        bc.valueAxis.valueMin = 0
        bc.barWidth = 12
        bc.groupSpacing = 18
        bc.barSpacing = 4
        d.add(bc)
        return d
    except Exception:
        st = _styles()
        return Paragraph("<i>Graphique non disponible.</i>", st["note"])


def data_table(headers: list[str], rows: list[list], col_widths: Optional[list] = None, *, numeric_from: int = -1) -> Table:
    st = _styles()
    hdr = [Paragraph(f"<b>{h}</b>", st["cell_bold"]) for h in headers]
    body = []
    for row in rows:
        body.append([Paragraph(str(c).replace("\n", "<br/>"), st["cell"]) for c in row])
    data = [hdr] + body
    t = Table(data, colWidths=col_widths, repeatRows=1)
    num_start = numeric_from if numeric_from >= 0 else max(1, len(headers) - 1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), PeyaBrand.BROWN),
        ("TEXTCOLOR", (0, 0), (-1, 0), PeyaBrand.WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, PeyaBrand.GREY_LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PeyaBrand.WHITE, PeyaBrand.GREY_BG]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, PeyaBrand.GREY_LINE),
        ("ALIGN", (num_start, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
    ]
    if rows:
        last_lbl = str(rows[-1][0]).lower()
        if "résultat" in last_lbl or "total" in last_lbl:
            style_cmds.append(("BACKGROUND", (0, -1), (-1, -1), PeyaBrand.ORANGE))
            style_cmds.append(("TEXTCOLOR", (0, -1), (-1, -1), PeyaBrand.WHITE))
            style_cmds.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
    t.setStyle(TableStyle(style_cmds))
    return t


def build_platypus_report(
    report_title: str,
    subtitle: str,
    story_extra: list,
    *,
    kpis: Optional[list[dict]] = None,
) -> bytes:
    buf = BytesIO()
    top_margin = 50 * mm

    def on_page(c, d):
        _header_footer(c, d, report_title, subtitle)

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=top_margin,
        bottomMargin=16 * mm,
    )
    story: list = [Spacer(1, 4)]
    if kpis:
        story.append(kpi_cards_table(kpis))
        story.append(Spacer(1, 16))
    story.extend(story_extra)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def draw_canvas_header(
    c: canvas.Canvas,
    doc_title: str,
    doc_number: str = "",
    doc_date=None,
    client_name: str = "",
    right_title: str = "",
):
    """En-tête facture / devis — logo + nom d'entreprise mis en avant."""
    w, h = A4

    c.setFillColor(PeyaBrand.CREAM)
    c.rect(0, h - 52 * mm, w, 52 * mm, fill=1, stroke=0)

    from app.services.pdf_branding import company_header_lines, get_current_db
    from app.region_config import REGION

    logo_x = 15 * mm
    logo_y = h - 36 * mm
    brand = draw_brand_block(c, logo_x, logo_y, logo_w=22 * mm, logo_h=22 * mm)

    lines = company_header_lines(get_current_db())
    company_name = (lines[0] if lines else REGION.get("company_name", "PEYA COMPANY")).strip()
    # Nom court sans forme juridique pour l'accroche visuelle
    name_hero = company_name.split("·")[0].strip().upper() or "PEYA COMPANY"
    text_x = brand["text_x"]

    # Nom d'entreprise — signal hero à côté du logo
    c.setFillColor(PeyaBrand.BROWN)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(text_x, h - 18 * mm, name_hero[:36])

    c.setFillColor(PeyaBrand.ORANGE)
    c.setFont("Helvetica-Bold", 8)
    tag = REGION.get("tagline") or "ERP — Togo · SYSCOHADA"
    c.drawString(text_x, h - 23.5 * mm, str(tag)[:50])

    c.setFillColor(PeyaBrand.TEXT_DIM)
    c.setFont("Helvetica", 7.5)
    addr = lines[1] if len(lines) > 1 else f"{REGION.get('address_default', '')} · {REGION.get('country', '')}"
    c.drawString(text_x, h - 28.5 * mm, (addr or "")[:78])
    if len(lines) > 2:
        c.drawString(text_x, h - 32.5 * mm, lines[2][:78])

    title = right_title or doc_title
    c.setFillColor(PeyaBrand.BROWN)
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(w - 15 * mm, h - 18 * mm, title)
    c.setFont("Helvetica", 10)
    c.setFillColor(PeyaBrand.TEXT)
    if doc_number:
        c.drawRightString(w - 15 * mm, h - 26 * mm, str(doc_number))
    if doc_date:
        from datetime import date as date_cls, datetime as datetime_cls
        dtxt = doc_date
        if isinstance(doc_date, (date_cls, datetime_cls)):
            dtxt = doc_date.strftime("%d/%m/%Y")
        c.drawRightString(w - 15 * mm, h - 32 * mm, f"Date : {dtxt}")

    if client_name:
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(PeyaBrand.BROWN)
        c.drawString(15 * mm, h - 48 * mm, (client_name or "—")[:60])
        draw_header_separator_line(c, w, {"bottom_y": h - 52 * mm}, gap=2 * mm)
    else:
        draw_header_separator_line(c, w, brand)
