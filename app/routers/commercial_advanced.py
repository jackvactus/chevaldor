"""API CRM commercial — leads, activités, campagnes, analytics pipeline."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.database import get_db
from app.models import Client, Deal, Invoice, Quote, User
from app.models_enterprise_ops import CrmActivity, CrmCampaign, CrmLead
from app import schemas_enterprise_ops as se
from app.tenant_service import filter_by_company, get_company_id, get_entity_or_404, stamp_company

router = APIRouter(prefix="/api/erp/commercial", tags=["commercial-advanced"])


def _get(model, pk, db, company_id: int, label: str = "Élément"):
    return get_entity_or_404(db, model, pk, company_id, label)


@router.get("/analytics")
def commercial_analytics(db: Session = Depends(get_db), user: User = Depends(require_action("deals", "view"))):
    company_id = get_company_id(db, user)
    deals = filter_by_company(db.query(Deal), Deal, company_id).all()
    invoices = [i for i in filter_by_company(db.query(Invoice), Invoice, company_id).all() if not getattr(i, "is_archived", False)]
    quotes = filter_by_company(db.query(Quote), Quote, company_id).all()
    leads = filter_by_company(db.query(CrmLead), CrmLead, company_id).all()
    stages = Counter((d.stage or "prospection") for d in deals)
    pipeline_amount = defaultdict(float)
    for d in deals:
        pipeline_amount[d.stage or "prospection"] += float(d.amount or 0)
    stage_order = ["prospection", "qualification", "proposition", "négociation", "signature", "gagné", "perdu"]
    funnel_labels, funnel_values, funnel_amounts = [], [], []
    for s in stage_order:
        if s in stages or s in pipeline_amount:
            funnel_labels.append(s.capitalize())
            funnel_values.append(stages.get(s, 0))
            funnel_amounts.append(round(pipeline_amount.get(s, 0), 0))
    ca_by_month: dict[str, float] = defaultdict(float)
    for inv in invoices:
        if inv.status in ("brouillon", "annulée"):
            continue
        dt = inv.date or date.today()
        key = f"{dt.month:02d}/{dt.year}"
        ca_by_month[key] += float(inv.amount or 0)
    sorted_months = sorted(ca_by_month.keys(), key=lambda x: (int(x.split("/")[1]), int(x.split("/")[0])))[-12:]
    top_clients: dict[str, float] = defaultdict(float)
    for inv in invoices:
        if inv.client_id:
            c = db.query(Client).filter(Client.id == inv.client_id).first()
            if c:
                top_clients[c.name] += float(inv.amount or 0)
    top_sorted = sorted(top_clients.items(), key=lambda x: -x[1])[:8]
    won = len([d for d in deals if (d.stage or "") in ("gagné", "won", "clôturé")])
    conv = round(won / max(len(deals), 1) * 100, 1)
    return {
        "deals_count": len(deals),
        "quotes_count": len(quotes),
        "invoices_count": len(invoices),
        "leads_count": len(leads),
        "pipeline_total": round(sum(float(d.amount or 0) for d in deals), 0),
        "ca_total": round(sum(ca_by_month.values()), 0),
        "conversion_rate": conv,
        "funnel": {"labels": funnel_labels, "values": funnel_values, "amounts": funnel_amounts},
        "ca_evolution": {"labels": sorted_months, "values": [ca_by_month[m] for m in sorted_months]},
        "top_clients": {"labels": [x[0] for x in top_sorted], "values": [x[1] for x in top_sorted]},
        "lead_stages": {
            "labels": list(Counter(l.stage for l in leads).keys()),
            "values": list(Counter(l.stage for l in leads).values()),
        },
    }


# ——— Leads ———
@router.get("/leads", response_model=List[se.CrmLeadOut])
def list_leads(db: Session = Depends(get_db), user: User = Depends(require_action("deals", "view"))):
    return filter_by_company(db.query(CrmLead), CrmLead, get_company_id(db, user)).order_by(CrmLead.id.desc()).all()


@router.post("/leads", response_model=se.CrmLeadOut)
def create_lead(data: se.CrmLeadIn, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "create"))):
    obj = CrmLead(**data.model_dump())
    stamp_company(obj, get_company_id(db, user))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/leads/{pk}", response_model=se.CrmLeadOut)
def update_lead(pk: int, data: se.CrmLeadIn, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "update"))):
    obj = _get(CrmLead, pk, db, get_company_id(db, user), "Lead")
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/leads/{pk}")
def delete_lead(pk: int, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "delete"))):
    obj = _get(CrmLead, pk, db, get_company_id(db, user), "Lead")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ——— Activités ———
@router.get("/activities", response_model=List[se.CrmActivityOut])
def list_activities(db: Session = Depends(get_db), user: User = Depends(require_action("deals", "view"))):
    return filter_by_company(db.query(CrmActivity), CrmActivity, get_company_id(db, user)).order_by(CrmActivity.due_date.desc()).all()


@router.post("/activities", response_model=se.CrmActivityOut)
def create_activity(data: se.CrmActivityIn, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "create"))):
    obj = CrmActivity(**data.model_dump())
    stamp_company(obj, get_company_id(db, user))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/activities/{pk}", response_model=se.CrmActivityOut)
def update_activity(pk: int, data: se.CrmActivityIn, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "update"))):
    obj = _get(CrmActivity, pk, db, get_company_id(db, user), "Activité")
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/activities/{pk}")
def delete_activity(pk: int, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "delete"))):
    obj = _get(CrmActivity, pk, db, get_company_id(db, user), "Activité")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ——— Campagnes ———
@router.get("/campaigns", response_model=List[se.CrmCampaignOut])
def list_campaigns(db: Session = Depends(get_db), user: User = Depends(require_action("deals", "view"))):
    return filter_by_company(db.query(CrmCampaign), CrmCampaign, get_company_id(db, user)).order_by(CrmCampaign.id.desc()).all()


@router.post("/campaigns", response_model=se.CrmCampaignOut)
def create_campaign(data: se.CrmCampaignIn, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "create"))):
    obj = CrmCampaign(**data.model_dump())
    stamp_company(obj, get_company_id(db, user))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/campaigns/{pk}", response_model=se.CrmCampaignOut)
def update_campaign(pk: int, data: se.CrmCampaignIn, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "update"))):
    obj = _get(CrmCampaign, pk, db, get_company_id(db, user), "Campagne")
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/campaigns/{pk}")
def delete_campaign(pk: int, db: Session = Depends(get_db), user: User = Depends(require_action("deals", "delete"))):
    obj = _get(CrmCampaign, pk, db, get_company_id(db, user), "Campagne")
    db.delete(obj)
    db.commit()
    return {"ok": True}
