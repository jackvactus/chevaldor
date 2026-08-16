"""Génération PDF professionnelles pour devis, factures et écritures comptables."""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Quote, Invoice, Client
from app.models_erp import JournalEntry, JournalLine
from app.services.pdf_theme import PeyaBrand, draw_canvas_header, fmt_money, _styles


def _fmt_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _coerce_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _line_rows(lines, fallback_amount: float = 0, fallback_vat: float = 0, fallback_desc: str = "Prestation"):
    rows = []
    sub_ht = 0.0
    total_tva = 0.0
    for ln in lines or []:
        qty = _coerce_float(getattr(ln, "quantity", None) or 0)
        pu = _coerce_float(getattr(ln, "unit_price", None) or 0)
        disc = _coerce_float(getattr(ln, "discount_pct", None) or 0)
        vat = _coerce_float(getattr(ln, "vat_rate", None) or 0)
        ht = qty * pu * (1 - disc / 100)
        tva = ht * vat / 100
        sub_ht += ht
        total_tva += tva
        rows.append([
            (getattr(ln, "description", None) or "—")[:70],
            f"{qty:g}",
            fmt_money(pu),
            f"{disc:g}%" if disc else "—",
            f"{vat:g}%",
            fmt_money(ht),
        ])
    if not rows:
        ht = float(fallback_amount or 0)
        rows.append([fallback_desc[:70], "1", fmt_money(ht), "—", f"{fallback_vat:g}%", fmt_money(ht)])
        sub_ht = ht
    return rows, sub_ht, total_tva


def _build_info_table(doc_title, number, doc_date, client_name, *, due_date=None, status=None, extra=None):
    st = _styles()
    data = [
        [Paragraph("<b>Document</b>", st["cell"]), Paragraph(doc_title, st["cell"])],
        [Paragraph("<b>Numéro</b>", st["cell"]), Paragraph(number or "—", st["cell"])],
        [Paragraph("<b>Date</b>", st["cell"]), Paragraph(_fmt_date(doc_date), st["cell"])],
        [Paragraph("<b>Client</b>", st["cell"]), Paragraph(client_name or "—", st["cell"])],
    ]
    if due_date:
        data.append([Paragraph("<b>Échéance</b>", st["cell"]), Paragraph(_fmt_date(due_date), st["cell"])])
    if status:
        data.append([Paragraph("<b>Statut</b>", st["cell"]), Paragraph(str(status), st["cell"])])
    if extra:
        for k, v in extra.items():
            data.append([Paragraph(f"<b>{k}</b>", st["cell"]), Paragraph(str(v), st["cell"])])
    table = Table(data, colWidths=[34 * mm, 120 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFAF8")),
        ("GRID", (0, 0), (-1, -1), 0.4, PeyaBrand.GREY_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _lines_table(lines, fallback_amount=0, fallback_vat=0, fallback_desc="Prestation"):
    st = _styles()
    body, sub_ht, total_tva = _line_rows(lines, fallback_amount, fallback_vat, fallback_desc)
    headers = ["Désignation", "Qté", "PU HT", "Rem.", "TVA", "Total HT"]
    data = [[Paragraph(f"<b>{h}</b>", st["cell_bold"]) for h in headers]]
    for row in body:
        data.append([Paragraph(str(c), st["cell"]) for c in row])

    ttc = sub_ht + total_tva
    data.append([
        Paragraph("<b>Sous-total HT</b>", st["cell"]),
        "", "", "", "",
        Paragraph(f"<b>{fmt_money(sub_ht)}</b>", st["cell"]),
    ])
    data.append([
        Paragraph("<b>TVA</b>", st["cell"]),
        "", "", "", "",
        Paragraph(f"<b>{fmt_money(total_tva)}</b>", st["cell"]),
    ])
    data.append([
        Paragraph("<b>Total TTC</b>", st["cell_total"]),
        "", "", "", "",
        Paragraph(f"<b>{fmt_money(ttc)}</b>", st["cell_total"]),
    ])

    tbl = Table(
        data,
        colWidths=[72 * mm, 14 * mm, 24 * mm, 14 * mm, 14 * mm, 28 * mm],
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PeyaBrand.BROWN),
        ("TEXTCOLOR", (0, 0), (-1, 0), PeyaBrand.WHITE),
        ("GRID", (0, 0), (-1, -4), 0.4, PeyaBrand.GREY_LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -4), [PeyaBrand.WHITE, PeyaBrand.GREY_BG]),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, -3), (-1, -2), PeyaBrand.CREAM),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ECFDF5")),
        ("TEXTCOLOR", (0, -1), (-1, -1), PeyaBrand.BROWN),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("SPAN", (0, -3), (4, -3)),
        ("SPAN", (0, -2), (4, -2)),
        ("SPAN", (0, -1), (4, -1)),
    ]))
    return tbl, ttc


def _build_commercial_pdf(
    doc_title: str,
    number: str,
    doc_date,
    client_name: str,
    lines: list,
    *,
    due_date=None,
    paid: float = 0,
    amount: float = 0,
    footer: str = "",
    fallback_amount: float = 0,
    fallback_vat: float = 0,
    fallback_desc: str = "Prestation",
    status: str = "",
    extra_info: dict | None = None,
) -> bytes:
    buf = BytesIO()

    def on_page(c, d):
        draw_canvas_header(c, doc_title, number, doc_date, client_name, right_title=doc_title)
        if due_date:
            c.setFont("Helvetica", 9)
            c.setFillColor(PeyaBrand.TEXT_DIM)
            c.drawRightString(195 * mm, 42 * mm, f"Échéance : {_fmt_date(due_date)}")

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=58 * mm,
        bottomMargin=18 * mm,
    )
    st = _styles()
    story = [Spacer(1, 2)]
    story.append(_build_info_table(doc_title, number, doc_date, client_name, due_date=due_date, status=status, extra=extra_info))
    story.append(Spacer(1, 6))
    tbl, ttc = _lines_table(lines, fallback_amount, fallback_vat, fallback_desc)
    story.append(tbl)
    if paid or amount:
        reste = max(0.0, float(amount or ttc) - float(paid or 0))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"Encaissé : <b>{fmt_money(paid)}</b> — Reste dû : <b>{fmt_money(reste)}</b>",
            st["note"],
        ))
    if footer:
        story.append(Spacer(1, 8))
        story.append(Paragraph(footer, st["note"]))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def render_quote_pdf(quote: Quote, client: Client, lines: list) -> bytes:
    return _build_commercial_pdf(
        "DEVIS",
        quote.number,
        quote.date,
        client.name if client else "",
        lines,
        footer="Ce devis est valable jusqu'à la date indiquée — Merci de votre confiance.",
        fallback_amount=quote.amount,
        fallback_vat=quote.vat_rate or 0,
        fallback_desc=quote.title or "Prestation",
        status=getattr(quote, "status", "") or "brouillon",
        extra_info={"Valide jusqu'au": _fmt_date(getattr(quote, "valid_until", None))},
    )


def _invoice_doc_title(invoice: Invoice) -> str:
    dt = (getattr(invoice, "doc_type", None) or "invoice").lower()
    return {
        "invoice": "FACTURE",
        "credit_note": "AVOIR",
        "proforma": "FACTURE PROFORMA",
        "deposit": "FACTURE D'ACOMPTE",
    }.get(dt, "FACTURE")


def render_invoice_pdf(invoice: Invoice, client: Client, lines: list) -> bytes:
    title = _invoice_doc_title(invoice)
    disc = _coerce_float(getattr(invoice, "discount_pct", 0) or 0)
    ret = _coerce_float(getattr(invoice, "withholding_pct", 0) or 0)
    footer_parts = ["Conditions : paiement selon échéance. Devise FCFA (XOF)."]
    desc = (getattr(invoice, "description", None) or "").strip()
    if desc:
        footer_parts.insert(0, desc.replace("\n", "<br/>"))
    if disc:
        footer_parts.append(f"Remise globale : {disc:g} %.")
    if ret:
        footer_parts.append(f"Retenue à la source : {ret:g} %.")
    if getattr(invoice, "delivery_date", None):
        footer_parts.append(f"Date livraison : {_fmt_date(invoice.delivery_date)}.")
    client_account = (getattr(client, "account_code", None) or "").strip() if client else ""
    extra = {
        "Mode de paiement": getattr(invoice, "payment_terms_days", None) and f"{invoice.payment_terms_days} jours" or "—",
    }
    if client_account:
        extra["Compte client"] = client_account
    # Lignes comptables visibles sur le PDF lorsque des account_code sont présents
    acc_lines = []
    for ln in lines or []:
        code = (getattr(ln, "account_code", None) or "").strip()
        if code:
            acc_lines.append(f"{code} — {getattr(ln, 'description', '') or getattr(ln, 'label', '') or 'Ligne'}")
    if client_account:
        acc_lines.insert(0, f"{client_account} — Client {client.name if client else ''}")
    if acc_lines:
        footer_parts.append("Comptes : " + " · ".join(acc_lines[:6]))
    return _build_commercial_pdf(
        title,
        invoice.number,
        invoice.date,
        client.name if client else "",
        lines,
        due_date=invoice.due_date,
        paid=_coerce_float(getattr(invoice, "paid", None) or 0),
        amount=_coerce_float(getattr(invoice, "amount", None) or 0),
        footer=" ".join(footer_parts),
        fallback_amount=_coerce_float(getattr(invoice, "amount", None) or 0),
        fallback_vat=_coerce_float(getattr(invoice, "vat_rate", None) or 0),
        status=getattr(invoice, "status", "") or "brouillon",
        extra_info=extra,
    )


def render_journal_entry_pdf(entry: JournalEntry, lines: list[JournalLine]) -> bytes:
    buf = BytesIO()

    def on_page(c, d):
        draw_canvas_header(c, "ÉCRITURE COMPTABLE", entry.reference or f"JE-{entry.id}", entry.date, "Saisie comptable", right_title="ÉCRITURE COMPTABLE")

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=58 * mm,
        bottomMargin=18 * mm,
    )
    st = _styles()
    story = [Spacer(1, 2)]
    info = _build_info_table(
        "Écriture comptable",
        entry.reference or f"JE-{entry.id}",
        entry.date,
        entry.label or "—",
        status=entry.status or "brouillon",
        extra={"Journal": entry.journal or "OD", "Période": f"{entry.period or '-'}"},
    )
    story.append(info)
    story.append(Spacer(1, 6))

    data = [[Paragraph("<b>Compte</b>", st["cell_bold"]), Paragraph("<b>Libellé</b>", st["cell_bold"]), Paragraph("<b>Débit</b>", st["cell_bold"]), Paragraph("<b>Crédit</b>", st["cell_bold"])] ]
    total_debit = 0.0
    total_credit = 0.0
    for ln in lines or []:
        total_debit += _coerce_float(getattr(ln, "debit", None) or 0)
        total_credit += _coerce_float(getattr(ln, "credit", None) or 0)
        data.append([
            Paragraph(str(getattr(ln, "account_code", "") or "—"), st["cell"]),
            Paragraph(str(getattr(ln, "label", "") or "—"), st["cell"]),
            Paragraph(fmt_money(getattr(ln, "debit", None) or 0), st["cell"]),
            Paragraph(fmt_money(getattr(ln, "credit", None) or 0), st["cell"]),
        ])
    data.append([
        Paragraph("<b>Total</b>", st["cell_total"]),
        "",
        Paragraph(f"<b>{fmt_money(total_debit)}</b>", st["cell_total"]),
        Paragraph(f"<b>{fmt_money(total_credit)}</b>", st["cell_total"]),
    ])
    table = Table(data, colWidths=[30 * mm, 95 * mm, 28 * mm, 28 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PeyaBrand.BROWN),
        ("TEXTCOLOR", (0, 0), (-1, 0), PeyaBrand.WHITE),
        ("GRID", (0, 0), (-1, -1), 0.4, PeyaBrand.GREY_LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [PeyaBrand.WHITE, PeyaBrand.GREY_BG]),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ECFDF5")),
        ("TEXTCOLOR", (0, -1), (-1, -1), PeyaBrand.BROWN),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(Paragraph("Écriture générée depuis l’ERP Peya — document de contrôle comptable.", st["note"]))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
