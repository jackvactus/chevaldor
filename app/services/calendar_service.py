"""Agrégation calendrier ERP — événements multi-modules."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    Deal,
    Invoice,
    Project,
    Quote,
    Task,
    Training,
)
from app.models_calendar import CalendarEvent
from app.models_erp import JournalEntry, LeaveRequest, SupplierInvoice, TreasuryMovement

CATEGORIES = {
    "compta": {"label": "Comptabilité", "color": "#2874a6"},
    "ventes": {"label": "Ventes", "color": "#c97a18"},
    "achats": {"label": "Achats", "color": "#c45a2a"},
    "stock": {"label": "Stocks", "color": "#7b5ea7"},
    "rh": {"label": "Ressources humaines", "color": "#2a9d8f"},
    "admin": {"label": "Administration", "color": "#6b7280"},
    "direction": {"label": "Direction", "color": "#2d8a45"},
}


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _in_range(ev_start: date, ev_end: date, start: date, end: date) -> bool:
    return ev_start <= end and ev_end >= start


def _event(
    *,
    eid: str,
    source: str,
    source_id: int,
    title: str,
    start: date,
    end: Optional[date] = None,
    category: str = "admin",
    event_type: str = "task",
    priority: str = "normal",
    owner: str = "",
    status: str = "planifié",
    description: str = "",
    all_day: bool = True,
    start_time: str = "09:00",
    end_time: str = "17:00",
    editable: bool = True,
    extended: Optional[dict] = None,
) -> dict:
    end_d = end or start
    overdue = end_d < date.today() and status not in ("payée", "terminé", "terminée", "won", "done", "approuvé")
    return {
        "id": eid,
        "source": source,
        "source_id": source_id,
        "title": title,
        "start": _iso(start),
        "end": _iso(end_d),
        "all_day": all_day,
        "start_time": start_time,
        "end_time": end_time,
        "category": category,
        "category_label": CATEGORIES.get(category, {}).get("label", category),
        "color": CATEGORIES.get(category, {}).get("color", "#6b7280"),
        "event_type": event_type,
        "priority": priority,
        "owner": owner or "—",
        "status": status,
        "description": description,
        "editable": editable,
        "overdue": overdue,
        "attachments": (extended or {}).get("attachments", []),
        "participants": (extended or {}).get("participants", []),
        "comments": (extended or {}).get("comments", []),
        "history": (extended or {}).get("history", []),
    }


def _custom_to_event(row: CalendarEvent) -> dict:
    end = row.end_date or row.start_date
    ext = {
        "attachments": json.loads(row.attachments_json or "[]"),
        "participants": json.loads(row.participants_json or "[]"),
        "comments": json.loads(row.comments_json or "[]"),
        "history": [{"at": _iso(row.created_at), "action": "Création"}],
    }
    return _event(
        eid=f"custom-{row.id}",
        source="custom",
        source_id=row.id,
        title=row.title,
        start=row.start_date,
        end=end,
        category=row.category or "admin",
        event_type=row.event_type or "meeting",
        priority=row.priority or "normal",
        owner=row.owner or "",
        status=row.status or "planifié",
        description=row.description or "",
        all_day=bool(row.all_day),
        start_time=row.start_time or "09:00",
        end_time=row.end_time or "10:00",
        editable=True,
        extended=ext,
    )


def collect_events(
    db: Session,
    start: date,
    end: date,
    categories: Optional[List[str]] = None,
    search: str = "",
) -> List[dict]:
    events: List[dict] = []
    today = date.today()

    invoices = db.query(Invoice).filter(
        or_(
            and_(Invoice.due_date.isnot(None), Invoice.due_date >= start, Invoice.due_date <= end),
            and_(Invoice.date.isnot(None), Invoice.date >= start, Invoice.date <= end),
        )
    ).all()
    for inv in invoices:
        if inv.due_date and _in_range(inv.due_date, inv.due_date, start, end):
            balance = (inv.amount or 0) - (inv.paid or 0)
            pr = "critical" if inv.status == "en retard" else ("high" if balance > 0 else "normal")
            events.append(_event(
                eid=f"invoice-{inv.id}",
                source="invoice",
                source_id=inv.id,
                title=f"Échéance facture {inv.number}",
                start=inv.due_date,
                category="ventes",
                event_type="invoice_due",
                priority=pr,
                owner="Comptabilité",
                status=inv.status or "envoyée",
                description=f"Montant {inv.amount:,.0f} FCFA — solde {balance:,.0f}",
                editable=True,
            ))
        if inv.date and _in_range(inv.date, inv.date, start, end):
            events.append(_event(
                eid=f"invoice-date-{inv.id}",
                source="invoice",
                source_id=inv.id,
                title=f"Facture {inv.number}",
                start=inv.date,
                category="compta",
                event_type="payment",
                priority="normal",
                owner="Comptabilité",
                status=inv.status or "brouillon",
                description="Date d'émission",
                editable=False,
            ))

    for si in db.query(SupplierInvoice).filter(
        SupplierInvoice.due_date.isnot(None),
        SupplierInvoice.due_date >= start,
        SupplierInvoice.due_date <= end,
    ).all():
        if si.due_date and _in_range(si.due_date, si.due_date, start, end):
            events.append(_event(
                eid=f"supplier-inv-{si.id}",
                source="supplier_invoice",
                source_id=si.id,
                title=f"Échéance fournisseur {si.number or si.id}",
                start=si.due_date,
                category="achats",
                event_type="invoice_due",
                priority="high" if si.status == "en retard" else "normal",
                owner="Achats",
                status=si.status or "validée",
                description=f"Montant {si.amount:,.0f} FCFA",
                editable=True,
            ))

    # Devis réellement enregistrés (émission + validité) — pas de pipeline deals prévisionnel
    for q in db.query(Quote).filter(
        or_(
            and_(Quote.valid_until.isnot(None), Quote.valid_until >= start, Quote.valid_until <= end),
            and_(Quote.date.isnot(None), Quote.date >= start, Quote.date <= end),
        )
    ).all():
        if q.date and _in_range(q.date, q.date, start, end):
            events.append(_event(
                eid=f"quote-date-{q.id}",
                source="quote",
                source_id=q.id,
                title=f"Devis {q.number}",
                start=q.date,
                category="ventes",
                event_type="reminder",
                priority="normal",
                owner="Commercial",
                status=q.status or "envoyé",
                description=q.title or "",
                editable=False,
            ))
        if q.valid_until and _in_range(q.valid_until, q.valid_until, start, end):
            events.append(_event(
                eid=f"quote-{q.id}",
                source="quote",
                source_id=q.id,
                title=f"Validité devis {q.number}",
                start=q.valid_until,
                category="ventes",
                event_type="reminder",
                priority="normal",
                owner="Commercial",
                status=q.status or "envoyé",
                description=q.title or "",
                editable=True,
            ))

    # Écritures comptables réellement saisies / importées
    for je in db.query(JournalEntry).filter(
        JournalEntry.date.isnot(None),
        JournalEntry.date >= start,
        JournalEntry.date <= end,
    ).all():
        if je.date and _in_range(je.date, je.date, start, end):
            events.append(_event(
                eid=f"journal-{je.id}",
                source="journal_entry",
                source_id=je.id,
                title=f"Écriture {je.journal or 'OD'} — {je.reference or je.id}",
                start=je.date,
                category="compta",
                event_type="payment",
                priority="normal",
                owner="Comptabilité",
                status=je.status or "brouillon",
                description=je.label or "",
                editable=False,
            ))

    projects = db.query(Project).filter(
        or_(
            and_(
                Project.start_date.isnot(None),
                Project.end_date.isnot(None),
                Project.start_date <= end,
                Project.end_date >= start,
            ),
            and_(Project.end_date.isnot(None), Project.end_date >= start, Project.end_date <= end),
        )
    ).all()
    for p in projects:
        if p.start_date and p.end_date and _in_range(p.start_date, p.end_date, start, end):
            events.append(_event(
                eid=f"project-{p.id}",
                source="project",
                source_id=p.id,
                title=p.name,
                start=p.start_date,
                end=p.end_date,
                category="direction",
                event_type="task",
                priority="normal",
                owner=p.manager or "Chef de projet",
                status=p.status or "planifié",
                description=p.description or "",
                editable=True,
            ))
        elif p.end_date and _in_range(p.end_date, p.end_date, start, end):
            events.append(_event(
                eid=f"project-end-{p.id}",
                source="project",
                source_id=p.id,
                title=f"Fin projet {p.name}",
                start=p.end_date,
                category="direction",
                event_type="reminder",
                priority="high",
                owner=p.manager or "",
                status=p.status or "",
                editable=True,
            ))

    for t in db.query(Training).filter(
        Training.start_date.isnot(None),
        Training.start_date <= end,
        or_(Training.end_date.is_(None), Training.end_date >= start),
    ).all():
        if t.start_date:
            te = t.end_date or t.start_date
            if _in_range(t.start_date, te, start, end):
                events.append(_event(
                    eid=f"training-{t.id}",
                    source="training",
                    source_id=t.id,
                    title=t.title,
                    start=t.start_date,
                    end=te,
                    category="rh",
                    event_type="meeting",
                    priority="normal",
                    owner="Formation",
                    status=t.status or "planifiée",
                    description=f"{t.location or ''} · {t.mode or ''}".strip(),
                    editable=True,
                ))

    for lv in db.query(LeaveRequest).filter(
        LeaveRequest.start_date.isnot(None),
        LeaveRequest.end_date.isnot(None),
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    ).all():
        if lv.start_date and lv.end_date and _in_range(lv.start_date, lv.end_date, start, end):
            events.append(_event(
                eid=f"leave-{lv.id}",
                source="leave",
                source_id=lv.id,
                title=f"Congé ({lv.type})",
                start=lv.start_date,
                end=lv.end_date,
                category="rh",
                event_type="absence",
                priority="normal",
                owner="RH",
                status=lv.status or "en attente",
                description=lv.notes or "",
                editable=False,
            ))

    for tm in db.query(TreasuryMovement).filter(
        TreasuryMovement.date.isnot(None),
        TreasuryMovement.date >= start,
        TreasuryMovement.date <= end,
    ).all():
        if tm.date and _in_range(tm.date, tm.date, start, end):
            events.append(_event(
                eid=f"treasury-{tm.id}",
                source="treasury",
                source_id=tm.id,
                title=tm.label or "Mouvement trésorerie",
                start=tm.date,
                category="compta",
                event_type="payment",
                priority="normal",
                owner="Trésorerie",
                status="enregistré",
                description=f"{tm.type} — {tm.amount:,.0f} FCFA",
                editable=False,
            ))

    for task in db.query(Task).filter(
        Task.date.isnot(None),
        Task.date >= start,
        Task.date <= end,
    ).all():
        if task.date and _in_range(task.date, task.date, start, end):
            events.append(_event(
                eid=f"task-{task.id}",
                source="task",
                source_id=task.id,
                title=task.label,
                start=task.date,
                category="direction",
                event_type="task",
                priority="high" if not task.done and task.date < today else "normal",
                owner=task.assignee or "",
                status="terminé" if task.done else "en attente",
                description="",
                editable=True,
            ))

    for act in db.query(Activity).filter(
        Activity.date.isnot(None),
        Activity.date >= start,
        Activity.date <= end,
    ).all():
        if act.date and _in_range(act.date, act.date, start, end):
            cat = "ventes" if act.type in ("call", "email", "meeting", "deal") else "admin"
            events.append(_event(
                eid=f"activity-{act.id}",
                source="activity",
                source_id=act.id,
                title=act.subject or act.type,
                start=act.date,
                category=cat,
                event_type=act.type or "meeting",
                priority="normal",
                owner=act.user_name or "",
                status="enregistré",
                description=(act.body or "")[:200],
                editable=False,
            ))

    for row in db.query(CalendarEvent).filter(
        CalendarEvent.start_date.isnot(None),
        CalendarEvent.start_date <= end,
        or_(CalendarEvent.end_date.is_(None), CalendarEvent.end_date >= start),
    ).all():
        if row.start_date and _in_range(row.start_date, row.end_date or row.start_date, start, end):
            events.append(_custom_to_event(row))

    if categories:
        events = [e for e in events if e["category"] in categories]
    if search:
        q = search.lower()
        events = [e for e in events if q in (e["title"] or "").lower() or q in (e["description"] or "").lower()]

    events.sort(key=lambda x: (x["start"] or "", x["start_time"] or ""))
    return events


def calendar_stats(db: Session, events: List[dict]) -> dict:
    today = date.today()
    week_end = today + timedelta(days=7)
    month_start = today.replace(day=1)

    today_ev = [e for e in events if e["start"] == today.isoformat()]
    week_ev = [e for e in events if e["start"] and today.isoformat() <= e["start"] <= week_end.isoformat()]
    upcoming = [e for e in events if e["start"] and e["start"] >= today.isoformat()]
    overdue = [e for e in events if e.get("overdue")]
    done = [e for e in events if (e.get("status") or "").lower() in ("terminé", "terminée", "payée", "done", "won")]
    pending = [e for e in events if e not in done and not e.get("overdue")]
    critical = [e for e in events if e.get("priority") == "critical" or e.get("overdue")]

    by_cat: Dict[str, int] = {}
    for e in events:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + 1

    week_buckets = [0] * 7
    for e in events:
        d = _parse_date(e.get("start"))
        if d and today <= d <= week_end:
            week_buckets[(d - today).days] += 1

    month_buckets: Dict[str, int] = {}
    for e in events:
        d = _parse_date(e.get("start"))
        if d and d >= month_start:
            key = d.strftime("%Y-%m")
            month_buckets[key] = month_buckets.get(key, 0) + 1

    total = len(events) or 1
    completion = round(len(done) / total * 100, 1)

    return {
        "today": len(today_ev),
        "week": len(week_ev),
        "upcoming": len(upcoming),
        "overdue": len(overdue),
        "critical": len(critical),
        "completion_rate": completion,
        "by_category": [{"category": k, "label": CATEGORIES.get(k, {}).get("label", k), "count": v} for k, v in by_cat.items()],
        "week_activity": week_buckets,
        "month_trend": [{"month": k, "count": v} for k, v in sorted(month_buckets.items())],
        "occupation_rate": min(100, round(len(events) / max(1, (week_end - today).days + 1) * 8, 1)),
    }


def move_event(
    db: Session,
    payload: dict,
    *,
    user_id: int = None,
    user_email: str = "",
    ip: str = "",
) -> dict:
    from app.services.audit_log import log_audit

    source = payload.get("source")
    source_id = int(payload.get("source_id") or 0)
    new_start = _parse_date(payload.get("start"))
    new_end = _parse_date(payload.get("end")) or new_start
    if not new_start:
        raise ValueError("Date invalide")

    def _audit(entity_type: str, entity_id: int, field: str, old_value, label: str = "") -> None:
        log_audit(
            db, "move", "calendar", entity_type, entity_id,
            detail=f"Déplacement calendrier — {field}" + (f" ({label})" if label else ""),
            user_id=user_id, user_email=user_email, ip=ip,
            old_value=_iso(old_value) if old_value else "",
            new_value=_iso(new_start),
        )

    if source == "deal":
        d = db.query(Deal).get(source_id)
        if d:
            old = d.close_date
            d.close_date = new_start
            db.commit()
            _audit("deal", d.id, "close_date", old, d.title if hasattr(d, "title") else "")
    elif source == "invoice":
        inv = db.query(Invoice).get(source_id)
        if inv:
            eid = str(payload.get("id") or "")
            if "invoice-date" in eid:
                old = inv.date
                inv.date = new_start
                field = "date"
            else:
                old = inv.due_date
                inv.due_date = new_start
                field = "due_date"
            db.commit()
            _audit("invoice", inv.id, field, old, inv.number or "")
    elif source == "supplier_invoice":
        si = db.query(SupplierInvoice).get(source_id)
        if si:
            old = si.due_date
            si.due_date = new_start
            db.commit()
            _audit("supplier_invoice", si.id, "due_date", old)
    elif source == "training":
        t = db.query(Training).get(source_id)
        if t:
            old = t.start_date
            t.start_date = new_start
            t.end_date = new_end
            db.commit()
            _audit("training", t.id, "start_date/end_date", old)
    elif source == "project":
        p = db.query(Project).get(source_id)
        if p:
            if "project-end" in str(payload.get("id", "")):
                old = p.end_date
                p.end_date = new_start
                field = "end_date"
            else:
                old = p.start_date
                p.start_date = new_start
                p.end_date = new_end
                field = "start_date/end_date"
            db.commit()
            _audit("project", p.id, field, old, p.name if hasattr(p, "name") else "")
    elif source == "quote":
        q = db.query(Quote).get(source_id)
        if q:
            old = q.valid_until
            q.valid_until = new_start
            db.commit()
            _audit("quote", q.id, "valid_until", old, q.number or "")
    elif source == "task":
        task = db.query(Task).get(source_id)
        if task:
            old = task.date
            task.date = new_start
            db.commit()
            _audit("task", task.id, "date", old)
    elif source == "custom":
        row = db.query(CalendarEvent).get(source_id)
        if row:
            old = row.start_date
            row.start_date = new_start
            row.end_date = new_end
            db.commit()
            _audit("calendar_event", row.id, "start_date/end_date", old, row.title or "")
    else:
        raise ValueError("Source non déplaçable")

    return {"ok": True, "start": _iso(new_start), "end": _iso(new_end)}
