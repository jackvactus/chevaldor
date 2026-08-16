"""Tableau de bord intelligent — KPI financiers et opérationnels."""
from datetime import date, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Client, Deal, Invoice, Quote, StockItem, Transaction, Project,
)
from app.models_erp import (
    Supplier, SupplierInvoice, TreasuryMovement, BankAccount, Employee,
)
from app.commercial_service import mark_overdue_invoices


def full_dashboard(db: Session) -> dict:
    mark_overdue_invoices(db)
    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    def sum_invoices_since(d):
        return float(db.query(func.coalesce(func.sum(Invoice.amount), 0)).filter(
            Invoice.date >= d
        ).scalar() or 0)

    ca_day = float(db.query(func.coalesce(func.sum(Invoice.amount), 0)).filter(
        Invoice.date == today
    ).scalar() or 0)
    ca_month = sum_invoices_since(month_start)
    ca_year = sum_invoices_since(year_start)

    products = float(db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "produit"
    ).scalar() or 0)
    charges = float(db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "charge"
    ).scalar() or 0)
    result_net = products - charges

    creances = sum(
        (i.amount or 0) - (i.paid or 0)
        for i in db.query(Invoice).all()
        if (i.amount or 0) > (i.paid or 0)
    )
    dettes = sum(
        (i.amount or 0) - (i.paid or 0)
        for i in db.query(SupplierInvoice).all()
        if (i.amount or 0) > (i.paid or 0)
    )

    due_soon = db.query(Invoice).filter(
        Invoice.due_date != None,
        Invoice.due_date <= today + timedelta(days=30),
        Invoice.amount > Invoice.paid,
    ).count()

    tresorerie = float(db.query(func.coalesce(func.sum(BankAccount.balance), 0)).scalar() or 0)
    caisse_net = 0.0
    for m in db.query(TreasuryMovement).all():
        if m.type in ("caisse_entree", "banque_entree"):
            caisse_net += m.amount or 0
        else:
            caisse_net -= m.amount or 0

    stock_low = db.query(StockItem).filter(StockItem.quantity <= StockItem.min_quantity).count()
    stock_items = db.query(StockItem).count()
    clients_actifs = db.query(Client).filter(Client.status == "actif").count()
    suppliers_actifs = db.query(Supplier).filter(Supplier.status == "actif").count()
    employees = db.query(Employee).filter(Employee.status == "actif").count()
    pipeline = float(db.query(func.coalesce(func.sum(Deal.amount), 0)).filter(
        Deal.stage.notin_(["won", "lost"])
    ).scalar() or 0)
    quotes_pending = db.query(Quote).filter(Quote.status == "envoyé").count()
    invoices_late = db.query(Invoice).filter(Invoice.status == "en retard").count()

    top_stock = db.query(StockItem).order_by(StockItem.quantity.desc()).limit(5).all()
    stock_value = sum((s.quantity or 0) * (s.unit_cost or 0) for s in db.query(StockItem).all())
    try:
        from app.services.stock_service import stock_analytics
        stock_stats = stock_analytics(db)
    except Exception:
        stock_stats = {"rupture_count": 0, "low_stock_count": stock_low, "total_value": stock_value}

    return {
        "financial": {
            "ca_daily": ca_day,
            "ca_monthly": ca_month,
            "ca_yearly": ca_year,
            "gross_margin_pct": round((result_net / products * 100) if products else 0, 1),
            "net_result": round(result_net, 2),
            "cash_flow_estimate": round(tresorerie + caisse_net, 2),
            "receivables": creances,
            "payables": dettes,
            "due_within_30d": due_soon,
            "treasury_bank": tresorerie,
            "treasury_cash_movements": round(caisse_net, 2),
        },
        "operational": {
            "sales_count": db.query(Invoice).count(),
            "purchases_count": db.query(SupplierInvoice).count(),
            "active_clients": clients_actifs,
            "active_suppliers": suppliers_actifs,
            "stock_alerts": stock_low,
            "stock_total_items": stock_items,
            "active_employees": employees,
            "pipeline_value": pipeline,
            "quotes_pending": quotes_pending,
            "invoices_late": invoices_late,
            "projects_active": db.query(Project).filter(Project.status == "en cours").count(),
        },
        "top_products": [
            {"name": s.name, "sku": s.sku, "quantity": s.quantity}
            for s in top_stock
        ],
        "stock": stock_stats,
    }
