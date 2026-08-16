"""API logistique & transport — flotte, livraisons, tournées, analytics."""
from __future__ import annotations

from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.database import get_db
from app.models import User
from app.models_enterprise_ops import (
    LogisticsCarrier, LogisticsDriver, LogisticsRoute, LogisticsShipment, LogisticsVehicle,
)
from app import schemas_enterprise_ops as se
from app.services.logistics_pdf_service import render_shipment_pdf, render_logistics_report_pdf

router = APIRouter(prefix="/api/erp/logistics", tags=["logistics-advanced"])


def _get(model, pk, db):
    obj = db.query(model).filter(model.id == pk).first()
    if not obj:
        raise HTTPException(404)
    return obj


@router.get("/analytics")
def logistics_analytics(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    vehicles = db.query(LogisticsVehicle).all()
    shipments = db.query(LogisticsShipment).all()
    routes = db.query(LogisticsRoute).all()
    vstatus = Counter(v.status for v in vehicles)
    sstatus = Counter(s.status for s in shipments)
    total_cost = sum(float(s.cost or 0) for s in shipments)
    delivered = len([s for s in shipments if (s.status or "") in ("livré", "delivered", "terminé")])
    delivery_rate = round(delivered / max(len(shipments), 1) * 100, 1)
    fuel_cost = sum(float(v.mileage or 0) * float(v.cost_per_km or 0) for v in vehicles) / max(len(vehicles), 1)
    util_labels = [v.plate or f"V{v.id}" for v in vehicles[:10]]
    util_values = [float(v.mileage or 0) for v in vehicles[:10]]
    cost_by_month: dict[str, float] = {}
    for s in shipments:
        if s.scheduled_date:
            key = f"{s.scheduled_date.month:02d}/{s.scheduled_date.year}"
            cost_by_month[key] = cost_by_month.get(key, 0) + float(s.cost or 0)
    months = sorted(cost_by_month.keys())[-8:]
    return {
        "vehicles_total": len(vehicles),
        "vehicles_active": len([v for v in vehicles if v.status == "disponible"]),
        "drivers_total": db.query(LogisticsDriver).count(),
        "shipments_total": len(shipments),
        "shipments_in_progress": len([s for s in shipments if s.status in ("en cours", "planifié")]),
        "delivery_rate": delivery_rate,
        "total_cost": round(total_cost, 0),
        "avg_fuel_cost": round(fuel_cost, 0),
        "routes_count": len(routes),
        "vehicle_status": {"labels": list(vstatus.keys()), "values": list(vstatus.values())},
        "shipment_status": {"labels": list(sstatus.keys()), "values": list(sstatus.values())},
        "fleet_utilization": {"labels": util_labels, "values": util_values},
        "cost_evolution": {"labels": months, "values": [cost_by_month.get(m, 0) for m in months]},
    }


@router.get("/shipments/{pk}/pdf")
def shipment_pdf(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    ship = _get(LogisticsShipment, pk, db)
    pdf = render_shipment_pdf(ship, db)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="livraison-{ship.reference}.pdf"'})


@router.get("/report/pdf")
def logistics_report_pdf(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    pdf = render_logistics_report_pdf(db)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="rapport-logistique.pdf"'})


# ——— Véhicules ———
@router.get("/vehicles", response_model=List[se.LogisticsVehicleOut])
def list_vehicles(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return db.query(LogisticsVehicle).order_by(LogisticsVehicle.plate).all()


@router.post("/vehicles", response_model=se.LogisticsVehicleOut)
def create_vehicle(data: se.LogisticsVehicleIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    obj = LogisticsVehicle(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/vehicles/{pk}", response_model=se.LogisticsVehicleOut)
def update_vehicle(pk: int, data: se.LogisticsVehicleIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "update"))):
    obj = _get(LogisticsVehicle, pk, db)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/vehicles/{pk}")
def delete_vehicle(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "delete"))):
    obj = _get(LogisticsVehicle, pk, db)
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ——— Chauffeurs ———
@router.get("/drivers", response_model=List[se.LogisticsDriverOut])
def list_drivers(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return db.query(LogisticsDriver).order_by(LogisticsDriver.name).all()


@router.post("/drivers", response_model=se.LogisticsDriverOut)
def create_driver(data: se.LogisticsDriverIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    obj = LogisticsDriver(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/drivers/{pk}", response_model=se.LogisticsDriverOut)
def update_driver(pk: int, data: se.LogisticsDriverIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "update"))):
    obj = _get(LogisticsDriver, pk, db)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/drivers/{pk}")
def delete_driver(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "delete"))):
    obj = _get(LogisticsDriver, pk, db)
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ——— Transporteurs ———
@router.get("/carriers", response_model=List[se.LogisticsCarrierOut])
def list_carriers(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return db.query(LogisticsCarrier).order_by(LogisticsCarrier.name).all()


@router.post("/carriers", response_model=se.LogisticsCarrierOut)
def create_carrier(data: se.LogisticsCarrierIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    obj = LogisticsCarrier(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/carriers/{pk}", response_model=se.LogisticsCarrierOut)
def update_carrier(pk: int, data: se.LogisticsCarrierIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "update"))):
    obj = _get(LogisticsCarrier, pk, db)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/carriers/{pk}")
def delete_carrier(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "delete"))):
    obj = _get(LogisticsCarrier, pk, db)
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ——— Expéditions / livraisons ———
@router.get("/shipments", response_model=List[se.LogisticsShipmentOut])
def list_shipments(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return db.query(LogisticsShipment).order_by(LogisticsShipment.id.desc()).all()


@router.post("/shipments", response_model=se.LogisticsShipmentOut)
def create_shipment(data: se.LogisticsShipmentIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    obj = LogisticsShipment(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/shipments/{pk}", response_model=se.LogisticsShipmentOut)
def update_shipment(pk: int, data: se.LogisticsShipmentIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "update"))):
    obj = _get(LogisticsShipment, pk, db)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/shipments/{pk}")
def delete_shipment(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "delete"))):
    obj = _get(LogisticsShipment, pk, db)
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ——— Tournées ———
@router.get("/routes", response_model=List[se.LogisticsRouteOut])
def list_routes(db: Session = Depends(get_db), _: User = Depends(require_action("stock", "view"))):
    return db.query(LogisticsRoute).order_by(LogisticsRoute.name).all()


@router.post("/routes", response_model=se.LogisticsRouteOut)
def create_route(data: se.LogisticsRouteIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "create"))):
    obj = LogisticsRoute(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/routes/{pk}", response_model=se.LogisticsRouteOut)
def update_route(pk: int, data: se.LogisticsRouteIn, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "update"))):
    obj = _get(LogisticsRoute, pk, db)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/routes/{pk}")
def delete_route(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("stock", "delete"))):
    obj = _get(LogisticsRoute, pk, db)
    db.delete(obj)
    db.commit()
    return {"ok": True}
