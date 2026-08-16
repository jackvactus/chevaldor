"""PDF — Business Intelligence, états comptables et exports Peya Company."""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer
from sqlalchemy.orm import Session

from app.services.accounting_reports import (
    balance_generale,
    bilan_simplifie,
    compte_de_resultat,
    financial_ratios,
    flux_tresorerie,
    grand_livre,
)
from app.syscohada.reports import bilan_ohada, compte_resultat_ohada, tafire_simplifie
from app.services.pdf_theme import (
    PeyaBrand,
    bar_chart_flowable,
    build_platypus_report,
    data_table,
    fmt_money,
    _styles,
)


def _fy_label(fiscal_year: Optional[int] = None) -> str:
    fy = fiscal_year or date.today().year
    return f"Exercice {fy} · {date.today().strftime('%d/%m/%Y')}"


def balance_pdf(db: Session, fiscal_year: int = None) -> bytes:
    balance = balance_generale(db, fiscal_year=fiscal_year)
    rows = [
        [r["account_code"], (r["label"] or "")[:42], f"{r['debit']:,.2f}", f"{r['credit']:,.2f}", f"{r['balance']:,.2f}"]
        for r in balance
    ]
    if not rows:
        rows = [["—", "Aucune écriture validée", "", "", ""]]

    total_d = sum(r["debit"] for r in balance)
    total_c = sum(r["credit"] for r in balance)
    kpis = [
        {"title": "Total débits", "value": fmt_money(total_d), "hint": _fy_label(fiscal_year)},
        {"title": "Total crédits", "value": fmt_money(total_c), "hint": f"{len(balance)} comptes"},
        {
            "title": "Écart",
            "value": fmt_money(abs(total_d - total_c)),
            "hint": "Équilibre comptable",
            "progress": min(1.0, 1.0 - min(abs(total_d - total_c) / max(total_d, 1), 1.0)),
        },
    ]
    st = _styles()
    story = [
        Paragraph("Balance générale", st["section"]),
        data_table(
            ["Compte", "Libellé", "Débit", "Crédit", "Solde"],
            rows,
            col_widths=[22 * mm, 58 * mm, 28 * mm, 28 * mm, 28 * mm],
            numeric_from=2,
        ),
    ]
    return build_platypus_report("Balance générale", _fy_label(fiscal_year), story, kpis=kpis)


def _compte_resultat_rows(cr: dict) -> list[list]:
    lines = cr.get("lines", [])
    rows = [[l["label"], f"{l['amount']:,.2f}"] for l in lines]
    net = cr.get("net_result", 0)
    has_net = any("résultat" in str(l.get("label", "")).lower() for l in lines)
    if not has_net:
        rows.append(["Résultat net", f"{net:,.2f}"])
    return rows


def compte_resultat_pdf(db: Session, fiscal_year: int = None) -> bytes:
    cr = compte_de_resultat(db, fiscal_year=fiscal_year)
    lines = cr.get("lines", [])
    rows = _compte_resultat_rows(cr)
    net = cr.get("net_result", 0)

    products = sum(l["amount"] for l in lines if l.get("amount", 0) > 0)
    charges = abs(sum(l["amount"] for l in lines if l.get("amount", 0) < 0))
    kpis = [
        {"title": "Produits", "value": fmt_money(products), "hint": "Cumul période"},
        {"title": "Charges", "value": fmt_money(charges), "hint": "Cumul période"},
        {
            "title": "Résultat net",
            "value": fmt_money(net),
            "hint": "Compte de résultat",
            "progress": 0.85 if net >= 0 else 0.25,
        },
    ]

    chart_labels = [(l["label"] or "?")[:14] for l in lines[:6]]
    chart_vals = [abs(l.get("amount", 0) or 0) for l in lines[:6]]

    st = _styles()
    story = []
    if chart_labels and any(chart_vals):
        story.append(Paragraph("Répartition des postes", st["section"]))
        story.append(bar_chart_flowable(chart_labels, [("Montant", chart_vals, PeyaBrand.BLUE)], width=280, height=130))
        story.append(Spacer(1, 12))
    story.append(Paragraph("Détail du compte de résultat", st["section"]))
    if not lines:
        story.append(Paragraph(
            "Aucune écriture comptable validée — montants issus des transactions enregistrées.",
            st["note"],
        ))
        story.append(Spacer(1, 6))
    story.append(data_table(["Poste", "Montant"], rows, col_widths=[118 * mm, 52 * mm], numeric_from=1))

    return build_platypus_report("Compte de résultat", _fy_label(fiscal_year), story, kpis=kpis)


def flux_tresorerie_pdf(db: Session) -> bytes:
    flux = flux_tresorerie(db)
    enc = flux.get("encaissements_clients", 0)
    dec = flux.get("decaissements_fournisseurs", 0)
    net = flux.get("flux_net", 0)
    mov = flux.get("mouvements_tresorerie", 0)

    kpis = [
        {"title": "Encaissements clients", "value": fmt_money(enc), "hint": "Cumul factures payées"},
        {"title": "Décaissements fourn.", "value": fmt_money(dec), "hint": "Cumul achats payés"},
        {
            "title": "Flux net",
            "value": fmt_money(net),
            "hint": f"Mouvements trésorerie {fmt_money(mov)}",
            "progress": 0.85 if net >= 0 else 0.3,
        },
    ]

    labels = ["Encaissements", "Décaissements", "Mouvements", "Flux net"]
    vals = [enc, dec, abs(mov), abs(net)]

    st = _styles()
    story = [
        Paragraph("Synthèse des flux", st["section"]),
        bar_chart_flowable(labels, [("Montant", vals, PeyaBrand.BLUE)], width=280, height=130),
        Spacer(1, 10),
        data_table(
            ["Libellé", "Montant"],
            [
                ["Encaissements clients", f"{enc:,.2f}"],
                ["Décaissements fournisseurs", f"{dec:,.2f}"],
                ["Mouvements trésorerie", f"{mov:,.2f}"],
                ["Flux net", f"{net:,.2f}"],
            ],
            col_widths=[100 * mm, 65 * mm],
            numeric_from=1,
        ),
    ]
    return build_platypus_report("Flux de trésorerie", _fy_label(), story, kpis=kpis)


def grand_livre_pdf(db: Session, account_code: Optional[str] = None) -> bytes:
    rows_data = grand_livre(db, account_code=account_code)
    total_d = sum(r.get("debit", 0) or 0 for r in rows_data)
    total_c = sum(r.get("credit", 0) or 0 for r in rows_data)
    display = rows_data[:400]
    rows = [
        [
            str(r.get("date", ""))[:10],
            (r.get("journal") or "")[:8],
            (r.get("reference") or "")[:12],
            r.get("account_code", ""),
            (r.get("label") or "")[:28],
            f"{r.get('debit', 0):,.2f}",
            f"{r.get('credit', 0):,.2f}",
        ]
        for r in display
    ]
    if not rows:
        rows = [["—", "—", "—", "—", "Aucune écriture validée", "", ""]]

    subtitle = f"Compte {account_code}" if account_code else "Tous les comptes"
    if len(rows_data) > len(display):
        subtitle += f" · {len(display)} / {len(rows_data)} lignes affichées"

    kpis = [
        {"title": "Lignes", "value": str(len(rows_data)), "hint": subtitle},
        {"title": "Total débits", "value": fmt_money(total_d), "hint": _fy_label()},
        {"title": "Total crédits", "value": fmt_money(total_c), "hint": "Écritures validées"},
    ]

    st = _styles()
    story = [
        Paragraph("Grand livre", st["section"]),
        data_table(
            ["Date", "Jnl", "Réf.", "Compte", "Libellé", "Débit", "Crédit"],
            rows,
            col_widths=[22 * mm, 14 * mm, 22 * mm, 20 * mm, 48 * mm, 26 * mm, 26 * mm],
            numeric_from=5,
        ),
    ]
    return build_platypus_report("Grand livre", subtitle, story, kpis=kpis)


def bilan_pdf(db: Session, fiscal_year: int = None) -> bytes:
    bilan = bilan_simplifie(db, fiscal_year=fiscal_year)
    balance = bilan.get("lines", [])[:50]

    kpis = [
        {"title": "Actif comptable", "value": fmt_money(bilan.get("actif_comptable", 0)), "hint": _fy_label(fiscal_year)},
        {"title": "Créances clients", "value": fmt_money(bilan.get("creances_clients", 0)), "hint": "Postes clients"},
        {
            "title": "Dettes fournisseurs",
            "value": fmt_money(bilan.get("dettes_fournisseurs", 0)),
            "hint": f"Passif {fmt_money(bilan.get('passif_comptable', 0))}",
            "progress": 0.65,
        },
    ]

    bal_rows = [
        [r["account_code"], (r["label"] or "")[:38], f"{r['balance']:,.2f}"]
        for r in balance
    ] or [["—", "Aucune donnée", ""]]

    st = _styles()
    story = [
        Paragraph("Bilan simplifié", st["section"]),
        data_table(
            ["Indicateur", "Montant"],
            [
                ["Actif comptable", f"{bilan.get('actif_comptable', 0):,.2f}"],
                ["Passif comptable", f"{bilan.get('passif_comptable', 0):,.2f}"],
                ["Créances clients", f"{bilan.get('creances_clients', 0):,.2f}"],
                ["Dettes fournisseurs", f"{bilan.get('dettes_fournisseurs', 0):,.2f}"],
            ],
            col_widths=[90 * mm, 75 * mm],
        ),
        Spacer(1, 14),
        Paragraph("Balance (extrait)", st["section"]),
        data_table(["Compte", "Libellé", "Solde"], bal_rows, col_widths=[25 * mm, 95 * mm, 45 * mm]),
    ]
    return build_platypus_report("Bilan simplifié", _fy_label(fiscal_year), story, kpis=kpis)


def bi_dashboard_pdf(db: Session, fiscal_year: int = None) -> bytes:
    """Rapport BI complet — aligné sur l'écran Business Intelligence."""
    ratios = financial_ratios(db)
    flux = flux_tresorerie(db)
    cr = compte_de_resultat(db, fiscal_year=fiscal_year)
    balance = balance_generale(db, fiscal_year=fiscal_year)
    net = cr.get("net_result", 0)

    liq = ratios.get("liquidite")
    liq_disp = ratios.get("liquidite_display", "—")
    endet = ratios.get("endettement_pct", 0)
    renta = ratios.get("rentabilite_pct", 0)
    treso = ratios.get("tresorerie", 0)

    if liq is not None:
        liq_progress = min(1.0, float(liq) / 2.0)
    else:
        liq_progress = 1.0 if ratios.get("liquidite_level") == "aucune_dette" else 0.0

    kpis = [
        {
            "title": "Liquidité",
            "value": liq_disp,
            "hint": f"Trésorerie {fmt_money(treso)} · Disp. {fmt_money(ratios.get('disponibilites', 0))}",
            "progress": liq_progress,
        },
        {
            "title": "Endettement",
            "value": f"{endet} %",
            "hint": f"Dettes {fmt_money(ratios.get('dettes', 0))}",
            "progress": max(0.0, min(1.0, 1.0 - endet / 100)),
        },
        {
            "title": "Résultat net",
            "value": fmt_money(net),
            "hint": f"Rentabilité {renta} %",
            "progress": min(1.0, max(0.0, 0.5 + net / max(abs(net), 1) * 0.3)) if net else 0.0,
        },
    ]

    cr_rows = [[l["label"], fmt_money(l["amount"])] for l in cr.get("lines", [])]
    if not any("résultat" in str(l.get("label", "")).lower() for l in cr.get("lines", [])):
        cr_rows.append(["Résultat net", fmt_money(net)])
    if not cr_rows:
        cr_rows = [["—", "—"]]

    flux_rows = [
        ["Encaissements clients", fmt_money(flux.get("encaissements_clients", 0))],
        ["Décaissements fournisseurs", fmt_money(flux.get("decaissements_fournisseurs", 0))],
        ["Mouvements trésorerie", fmt_money(flux.get("mouvements_tresorerie", 0))],
        ["Flux net", fmt_money(flux.get("flux_net", 0))],
    ]

    flux_vals = [
        flux.get("encaissements_clients", 0),
        flux.get("decaissements_fournisseurs", 0),
        abs(flux.get("mouvements_tresorerie", 0)),
        abs(flux.get("flux_net", 0)),
    ]

    bal_display = balance[:45]
    bal_rows = [
        [r["account_code"], (r["label"] or "")[:32], f"{r['debit']:,.2f}", f"{r['credit']:,.2f}", f"{r['balance']:,.2f}"]
        for r in bal_display
    ]
    if not bal_rows:
        bal_rows = [["—", "Aucune écriture", "", "", ""]]
    bal_note = f"{len(bal_display)} / {len(balance)} comptes" if len(balance) > len(bal_display) else f"{len(balance)} comptes"

    st = _styles()
    story = [
        Paragraph("Ratios financiers", st["section"]),
        data_table(
            ["Indicateur", "Valeur"],
            [
                ["Liquidité", str(liq)],
                ["Endettement", f"{endet} %"],
                ["Rentabilité", f"{renta} %"],
                ["Créances", fmt_money(ratios.get("creances", 0))],
                ["Dettes", fmt_money(ratios.get("dettes", 0))],
            ],
            col_widths=[90 * mm, 75 * mm],
        ),
        Spacer(1, 12),
        Paragraph("Flux de trésorerie", st["section"]),
        bar_chart_flowable(
            ["Encaissements", "Décaissements", "Mouv.", "Flux net"],
            [("Montant", flux_vals, PeyaBrand.BLUE)],
            width=280,
            height=120,
        ),
        Spacer(1, 8),
        data_table(["Libellé", "Montant"], flux_rows, col_widths=[100 * mm, 65 * mm]),
        Spacer(1, 14),
        Paragraph("Compte de résultat", st["section"]),
        data_table(["Poste", "Montant"], cr_rows, col_widths=[100 * mm, 65 * mm]),
        Spacer(1, 14),
        Paragraph(f"Balance générale — {bal_note}", st["section"]),
        data_table(
            ["Compte", "Libellé", "Débit", "Crédit", "Solde"],
            bal_rows,
            col_widths=[20 * mm, 52 * mm, 26 * mm, 26 * mm, 26 * mm],
        ),
    ]

    return build_platypus_report(
        "Business Intelligence",
        _fy_label(fiscal_year),
        story,
        kpis=kpis,
    )


def dashboard_overview_pdf(db: Session, fiscal_year: int = None) -> bytes:
    """Alias : vue d'ensemble = rapport BI."""
    return bi_dashboard_pdf(db, fiscal_year=fiscal_year)


# Registre pour exports planifiés et API
def liasse_ohada_pdf(db: Session, fiscal_year: int = None) -> bytes:
    """Liasse OHADA — bilan, compte de résultat, TAFIRE (extrait)."""
    year = fiscal_year or date.today().year
    bilan = bilan_ohada(db, year)
    resultat = compte_resultat_ohada(db, year)
    tafire = tafire_simplifie(db, year)

    def _rows(block) -> list[list]:
        lines = block.get("lines", []) if isinstance(block, dict) else (block if isinstance(block, list) else [])
        return [[(r.get("label") or r.get("account") or "—")[:48], fmt_money(r.get("amount", 0))] for r in lines[:20]]

    st = _styles()
    story = [
        Paragraph("Bilan — Actif (extrait)", st["section"]),
        data_table(["Poste", "Montant"], _rows(bilan.get("actif", {}) if isinstance(bilan, dict) else {})),
        Spacer(1, 6 * mm),
        Paragraph("Compte de résultat", st["section"]),
        data_table(["Poste", "Montant"], _rows(resultat)),
        Spacer(1, 6 * mm),
        Paragraph("TAFIRE (flux simplifiés)", st["section"]),
        data_table(["Flux", "Montant"], _rows(tafire)),
    ]
    return build_platypus_report(f"Liasse OHADA {year}", _fy_label(year), story)


PDF_EXPORTS: dict[str, Callable[..., bytes]] = {
    "bi": bi_dashboard_pdf,
    "overview": bi_dashboard_pdf,
    "balance": balance_pdf,
    "compte_resultat": compte_resultat_pdf,
    "flux_tresorerie": flux_tresorerie_pdf,
    "grand_livre": grand_livre_pdf,
    "bilan": bilan_pdf,
    "liasse": liasse_ohada_pdf,
}


def build_pdf_export(
    db: Session,
    report_type: str,
    fiscal_year: Optional[int] = None,
    *,
    user_id: int = None,
    user_email: str = "",
) -> bytes:
    from app.services.pdf_branding import log_pdf_generation, pdf_branding_context

    fn = PDF_EXPORTS.get(report_type)
    if not fn:
        raise ValueError(f"Type PDF inconnu : {report_type}")
    with pdf_branding_context(db):
        if report_type in ("balance", "compte_resultat", "bilan", "bi", "overview"):
            data = fn(db, fiscal_year=fiscal_year)
        elif report_type == "grand_livre":
            data = fn(db)
        else:
            data = fn(db)
    try:
        log_pdf_generation(
            db, report_type, user_id=user_id, user_email=user_email, fiscal_year=fiscal_year,
        )
    except Exception:
        pass
    return data
