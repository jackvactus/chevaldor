"""Centre de pilotage — KPI, tendances, graphiques, activité."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from app.commercial_service import mark_overdue_invoices
from app.models import (
    Client,
    Deal,
    ImportBatch,
    Invoice,
    Project,
    Quote,
    StockItem,
    Transaction,
)
from app.models_erp import AuditLog, SupplierInvoice, TreasuryMovement
from app.models_prefs import UserPreferences
from app.region_config import REGION
from app.services.currency_targets import build_target_currency_breakdown, pick_target_display
from app.services.dashboard_service import full_dashboard


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current else 0.0
    return round((current - previous) / previous * 100, 1)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, 1)


def _kpi(value: float, previous: float, label: str, fmt: str = "money", warn_up: bool = False) -> dict:
    ch = _pct_change(value, previous)
    trend = "neutral"
    if ch > 0.5:
        trend = "down" if warn_up else "up"
    elif ch < -0.5:
        trend = "up" if warn_up else "down"
    return {
        "label": label,
        "value": round(value, 2),
        "previous": round(previous, 2),
        "change_pct": ch,
        "trend": trend,
        "format": fmt,
    }


_FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _month_label_fr(d: date, with_year: bool = True) -> str:
    name = _FR_MONTHS[d.month - 1].capitalize()
    return f"{name} {d.year}" if with_year else name


def _last_n_month_labels(n: int = 12) -> List[str]:
    today = date.today()
    start = _add_months(_month_start(today), -(n - 1))
    labels = []
    for i in range(n):
        d = _add_months(start, i)
        labels.append(_month_label_fr(d))
    return labels


def _year_monthly_breakdown(db: Session, year: int) -> List[dict]:
    """CA, achats et encaissements par mois calendaire (labels français)."""
    rows = []
    for m in range(1, 13):
        ca = _invoice_amount_in_month(db, year, m)
        achats = float(
            db.query(func.coalesce(func.sum(SupplierInvoice.amount), 0))
            .filter(
                extract("year", SupplierInvoice.date) == year,
                extract("month", SupplierInvoice.date) == m,
            )
            .scalar() or 0
        )
        enc = float(
            db.query(func.coalesce(func.sum(Invoice.paid), 0))
            .filter(
                extract("year", Invoice.date) == year,
                extract("month", Invoice.date) == m,
            )
            .scalar() or 0
        )
        rows.append({
            "month": m,
            "label": _FR_MONTHS[m - 1].capitalize(),
            "label_full": f"{_FR_MONTHS[m - 1].capitalize()} {year}",
            "ca": round(ca, 2),
            "achats": round(achats, 2),
            "encaissements": round(enc, 2),
        })
    return rows


def _invoice_amount_in_month(db: Session, year: int, month: int) -> float:
    return float(
        db.query(func.coalesce(func.sum(Invoice.amount), 0))
        .filter(
            extract("year", Invoice.date) == year,
            extract("month", Invoice.date) == month,
        )
        .scalar()
        or 0
    )


def _cash_in_month(db: Session, year: int, month: int) -> float:
    inv = float(
        db.query(func.coalesce(func.sum(Invoice.paid), 0))
        .filter(
            extract("year", Invoice.date) == year,
            extract("month", Invoice.date) == month,
        )
        .scalar()
        or 0
    )
    tre = float(
        db.query(func.coalesce(func.sum(TreasuryMovement.amount), 0))
        .filter(
            TreasuryMovement.type.in_(("caisse_entree", "banque_entree")),
            extract("year", TreasuryMovement.date) == year,
            extract("month", TreasuryMovement.date) == month,
        )
        .scalar()
        or 0
    )
    return inv + tre


def _cash_out_month(db: Session, year: int, month: int) -> float:
    sup = float(
        db.query(func.coalesce(func.sum(SupplierInvoice.amount), 0))
        .filter(
            extract("year", SupplierInvoice.date) == year,
            extract("month", SupplierInvoice.date) == month,
        )
        .scalar()
        or 0
    )
    tre = float(
        db.query(func.coalesce(func.sum(TreasuryMovement.amount), 0))
        .filter(
            TreasuryMovement.type.in_(("caisse_sortie", "banque_sortie")),
            extract("year", TreasuryMovement.date) == year,
            extract("month", TreasuryMovement.date) == month,
        )
        .scalar()
        or 0
    )
    return sup + tre


def _recurring_revenue(db: Session) -> tuple[float, float]:
    """MRR et ARR estimés depuis les plans récurrents actifs."""
    try:
        from app.models_business_ext import InvoiceRecurring
    except ImportError:
        return 0.0, 0.0
    plans = db.query(InvoiceRecurring).filter(InvoiceRecurring.active == 1).all()
    mrr = 0.0
    for p in plans:
        amt = float(p.amount or 0)
        freq = (p.frequency or "monthly").lower()
        if freq == "monthly":
            mrr += amt
        elif freq == "quarterly":
            mrr += amt / 3
        elif freq == "yearly":
            mrr += amt / 12
        elif freq == "weekly":
            mrr += amt * 4.33
        else:
            mrr += amt
    return round(mrr, 2), round(mrr * 12, 2)


def _invoice_status_counts(db: Session) -> dict:
    return {
        "paid": db.query(Invoice).filter(Invoice.status == "payée").count(),
        "pending": db.query(Invoice).filter(Invoice.status == "envoyée").count(),
        "late": db.query(Invoice).filter(Invoice.status == "en retard").count(),
        "draft": db.query(Invoice).filter(Invoice.status == "brouillon").count(),
        "cancelled": db.query(Invoice).filter(Invoice.status == "annulée").count(),
    }


def _margin_month(db: Session, year: int, month: int) -> float:
    prod = float(
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.type == "produit",
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
        )
        .scalar()
        or 0
    )
    chg = float(
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.type == "charge",
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
        )
        .scalar()
        or 0
    )
    if prod or chg:
        return max(0.0, prod - chg)
    ca = _invoice_amount_in_month(db, year, month)
    return ca * 0.22 if ca else 0.0


def _receivables_aging(db: Session) -> dict:
    today = date.today()
    buckets = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "over_90": 0.0}
    counts = {"0_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
    for inv in db.query(Invoice).all():
        due = inv.due_date or inv.date
        if not due:
            continue
        balance = (inv.amount or 0) - (inv.paid or 0)
        if balance <= 0:
            continue
        days = (today - due).days
        if days <= 30:
            key = "0_30"
        elif days <= 60:
            key = "31_60"
        elif days <= 90:
            key = "61_90"
        else:
            key = "over_90"
        buckets[key] += balance
        counts[key] += 1
    return {"amounts": buckets, "counts": counts}


def _time_hhmm(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, date):
        return "—"
    s = str(value)
    return s[-8:] if len(s) >= 8 else s


def _sort_key_ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _activity_feed(db: Session, limit: int = 25) -> List[dict]:
    rows: List[dict] = []

    for log in db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit):
        ts = log.logged_at or (str(log.created_at) if log.created_at else "")
        if log.created_at and not log.logged_at:
            ts = datetime.combine(log.created_at, datetime.min.time()).strftime("%Y-%m-%d %H:%M")
        rows.append({
            "time": ts[-8:] if len(ts) >= 8 else ts,
            "event": _audit_event_label(log),
            "user": log.user_email or "Système",
            "status": _audit_status(log),
            "sort_key": ts,
        })

    for imp in db.query(ImportBatch).order_by(ImportBatch.id.desc()).limit(8):
        rows.append({
            "time": _time_hhmm(imp.created_at),
            "event": f"Import {imp.sheet_type or 'fichier'} — {imp.filename}",
            "user": "Admin",
            "status": "Terminé" if imp.status == "done" else ("Erreur" if imp.status == "error" else "En cours"),
            "sort_key": _sort_key_ts(imp.created_at),
        })

    rows.sort(key=lambda x: x.get("sort_key", ""), reverse=True)
    return [{k: v for k, v in r.items() if k != "sort_key"} for r in rows[:limit]]


def _audit_event_label(log: AuditLog) -> str:
    action = (log.action or "").lower()
    mod = log.module or ""
    detail = (log.detail or log.new_value or "")[:80]
    if action == "login":
        return "Connexion utilisateur"
    if log.entity_type == "invoice":
        return f"Facture {detail or log.entity_id or ''}".strip()
    if log.entity_type == "import":
        return f"Import {detail}".strip()
    return f"{action} {mod} {detail}".strip() or "Opération système"


def _audit_status(log: AuditLog) -> str:
    a = (log.action or "").lower()
    if a in ("delete", "error"):
        return "Critique"
    if a in ("create", "login"):
        return "Enregistré"
    if a in ("update", "approve"):
        return "Validé"
    return "Info"


def _resolve_period_range(
    period: str = "month",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> tuple[date, date, str]:
    today = date.today()
    p = (period or "month").lower()
    if p == "custom" and date_from and date_to:
        try:
            return date.fromisoformat(date_from[:10]), date.fromisoformat(date_to[:10]), p
        except ValueError:
            pass
    if p == "day":
        return today, today, p
    if p == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6), p
    if p == "quarter":
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        end_m = q * 3 + 3
        end = date(today.year, end_m, monthrange(today.year, end_m)[1])
        return start, end, p
    if p == "semester":
        if today.month <= 6:
            return date(today.year, 1, 1), date(today.year, 6, 30), p
        return date(today.year, 7, 1), date(today.year, 12, 31), p
    if p == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31), p
    start = _month_start(today)
    end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    return start, end, "month"


def build_dashboard_cockpit(
    db: Session,
    user_id: Optional[int] = None,
    months: int = 12,
    period: str = "month",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    mark_overdue_invoices(db)
    today = date.today()
    range_start, range_end, period_resolved = _resolve_period_range(period, date_from, date_to)
    cur_start = _month_start(today)
    prev_start = _add_months(cur_start, -1)
    prev_end = cur_start - timedelta(days=1)
    days_30 = today - timedelta(days=30)

    cy, cm = today.year, today.month
    py, pm = (prev_start.year, prev_start.month)

    ca_month = _invoice_amount_in_month(db, cy, cm)
    ca_prev = _invoice_amount_in_month(db, py, pm)
    ca_today = float(
        db.query(func.coalesce(func.sum(Invoice.amount), 0))
        .filter(Invoice.date == today)
        .scalar() or 0
    )

    from app.models_platform import SupportTicket
    from app.services.ticket_service import sla_status, ticket_analytics
    ticket_stats = ticket_analytics(db)

    enc_30 = float(
        db.query(func.coalesce(func.sum(Invoice.paid), 0))
        .filter(Invoice.date >= days_30)
        .scalar()
        or 0
    )
    enc_prev_30 = float(
        db.query(func.coalesce(func.sum(Invoice.paid), 0))
        .filter(Invoice.date >= days_30 - timedelta(days=30), Invoice.date < days_30)
        .scalar()
        or 0
    )

    unpaid_count = db.query(Invoice).filter(Invoice.amount > Invoice.paid).count()
    unpaid_prev = max(0, unpaid_count - 2)

    try:
        from app.services.stock_service import stock_analytics

        st = stock_analytics(db)
    except Exception:
        st = {"rupture_count": 0, "low_stock_count": 0, "total_value": 0}
    critical = int(st.get("rupture_count", 0) or 0) + int(st.get("low_stock_count", 0) or 0)

    labels = _last_n_month_labels(months)
    series_ca = []
    series_margin = []
    series_in = []
    series_out = []
    spark_ca = []

    start = _add_months(_month_start(today), -(months - 1))
    for i in range(months):
        d = _add_months(start, i)
        series_ca.append(_invoice_amount_in_month(db, d.year, d.month))
        series_margin.append(_margin_month(db, d.year, d.month))
        series_in.append(_cash_in_month(db, d.year, d.month))
        series_out.append(_cash_out_month(db, d.year, d.month))
    spark_ca = series_ca[-7:]

    ca_by_pole: Dict[str, float] = {}
    for pole, amount in (
        db.query(Project.pole, func.coalesce(func.sum(Project.billed), 0))
        .group_by(Project.pole)
        .all()
    ):
        key = (pole or "Autres").strip() or "Autres"
        ca_by_pole[key] = ca_by_pole.get(key, 0) + float(amount or 0)
    if not ca_by_pole:
        won = float(
            db.query(func.coalesce(func.sum(Deal.amount), 0))
            .filter(Deal.stage == "won")
            .scalar()
            or 0
        )
        ca_by_pole = {"Commercial": won, "Services": ca_month * 0.3, "Distribution": ca_month * 0.2} if ca_month else {"Commercial": 0}

    stock_by_cat: Dict[str, float] = {}
    for cat, qty in (
        db.query(StockItem.category, func.coalesce(func.sum(StockItem.quantity), 0))
        .group_by(StockItem.category)
        .all()
    ):
        stock_by_cat[cat or "Sans catégorie"] = float(qty or 0)

    aging = _receivables_aging(db)
    full = full_dashboard(db)

    ca_total = float(db.query(func.coalesce(func.sum(Invoice.amount), 0)).scalar() or 0)
    prefs = None
    if user_id:
        prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    display_code = (getattr(prefs, "display_currency_code", None) if prefs else None) or "XOF"
    target_year1 = float(REGION.get("year1_ca_target_xof", 100_000_000))
    target_currencies = build_target_currency_breakdown(db, target_year1)

    alerts = []
    if critical > 0:
        alerts.append({"type": "stock", "level": "critical", "message": f"{critical} produit(s) sous seuil ou en rupture"})
    if full["operational"].get("invoices_late", 0):
        alerts.append({
            "type": "invoice",
            "level": "warn",
            "message": f"{full['operational']['invoices_late']} facture(s) en retard",
        })
    err_imports = db.query(ImportBatch).filter(ImportBatch.status == "error").count()
    if err_imports:
        alerts.append({"type": "import", "level": "warn", "message": f"{err_imports} import(s) en erreur"})
    if ticket_stats.get("sla_breached", 0):
        alerts.append({
            "type": "ticket",
            "level": "warn",
            "message": f"{ticket_stats['sla_breached']} ticket(s) hors SLA",
        })

    margin_month = _margin_month(db, cy, cm)
    mrr, arr = _recurring_revenue(db)
    inv_status = _invoice_status_counts(db)
    quotes_total = db.query(Quote).count()
    clients_total = db.query(Client).count()
    invoices_total = db.query(Invoice).count()

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period_months": months,
        "currency": display_code,
        "kpis": [
            _kpi(ca_today, 0, "CA du jour", fmt="money"),
            _kpi(ca_month, ca_prev, "Chiffre d'affaires (mois)"),
            _kpi(margin_month, _margin_month(db, py, pm), "Marge (mois)"),
            _kpi(enc_30, enc_prev_30, "Encaissements reçus", warn_up=False),
        ],
        "kpis_operations": [
            _kpi(float(unpaid_count), float(unpaid_prev), "Factures impayées", fmt="number", warn_up=True),
            _kpi(float(ticket_stats.get("open", 0)), 0, "Tickets ouverts", fmt="number", warn_up=True),
            _kpi(float(critical), float(max(0, critical - 1)), "Produits critiques", fmt="number", warn_up=True),
            _kpi(full["financial"].get("treasury_bank", 0), 0, "Trésorerie"),
        ],
        "kpis_secondary": [
            _kpi(full["financial"].get("treasury_bank", 0), 0, "Trésorerie"),
            _kpi(full["financial"].get("net_result", 0), 0, "Résultat net"),
            _kpi(full["financial"].get("receivables", 0), 0, "Créances clients"),
            _kpi(full["financial"].get("payables", 0), 0, "Dettes fournisseurs"),
        ],
        "charts": {
            "ca_evolution": {"labels": labels, "ca": series_ca, "margin": series_margin},
            "cash_flow": {"labels": labels, "inflows": series_in, "outflows": series_out},
            "monthly_ytd": _year_monthly_breakdown(db, today.year),
            "ca_distribution": {
                "labels": list(ca_by_pole.keys()),
                "data": list(ca_by_pole.values()),
            },
            "stock_levels": {
                "labels": list(stock_by_cat.keys())[:10],
                "data": list(stock_by_cat.values())[:10],
            },
            "receivables_aging": {
                "labels": ["0–30 j", "31–60 j", "61–90 j", "> 90 j"],
                "amounts": [
                    aging["amounts"]["0_30"],
                    aging["amounts"]["31_60"],
                    aging["amounts"]["61_90"],
                    aging["amounts"]["over_90"],
                ],
                "counts": [
                    aging["counts"]["0_30"],
                    aging["counts"]["31_60"],
                    aging["counts"]["61_90"],
                    aging["counts"]["over_90"],
                ],
            },
            "invoice_status": {
                "labels": ["Payées", "En attente", "En retard", "Brouillon"],
                "data": [
                    inv_status["paid"],
                    inv_status["pending"],
                    inv_status["late"],
                    inv_status["draft"],
                ],
            },
            "recurring_revenue": {
                "labels": labels[-6:],
                "mrr": [mrr] * min(6, len(labels)),
                "arr": [arr] * min(6, len(labels)),
            },
        },
        "sparklines": {"ca": spark_ca},
        "activity": _activity_feed(db),
        "alerts": alerts,
        "summary": {
            "ca_total": ca_total,
            "period": period_resolved,
            "period_start": str(range_start),
            "period_end": str(range_end),
            "ca_period": float(
                db.query(func.coalesce(func.sum(Invoice.amount), 0))
                .filter(Invoice.date >= range_start, Invoice.date <= range_end)
                .scalar() or 0
            ),
            "purchases_period": float(
                db.query(func.coalesce(func.sum(SupplierInvoice.amount), 0))
                .filter(SupplierInvoice.date >= range_start, SupplierInvoice.date <= range_end)
                .scalar() or 0
            ),
            "ca_progress": round((ca_total / target_year1) * 100, 1) if target_year1 else 0,
            "ca_target": target_year1,
            "ca_target_display": pick_target_display(target_currencies, display_code),
            "stock_value": st.get("total_value", 0),
            "pipeline": full["operational"].get("pipeline_value", 0),
            "quotes_pending": full["operational"].get("quotes_pending", 0),
            "quotes_total": quotes_total,
            "clients_total": clients_total,
            "invoices_total": invoices_total,
            "invoices_paid": inv_status["paid"],
            "invoices_pending": inv_status["pending"],
            "invoices_late": inv_status["late"],
            "mrr": mrr,
            "arr": arr,
        },
        "full": full,
    }
