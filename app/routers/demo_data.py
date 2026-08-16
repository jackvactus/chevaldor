"""API jeux de démonstration et remise à zéro."""
from typing import List, Optional
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.database import get_db
from app.models import Client
from app.server_config import is_production

router = APIRouter(prefix="/api", tags=["demo"])


def _assert_demo_enabled() -> None:
    if not is_production():
        return
    allow = (os.environ.get("PEYA_ALLOW_DEMO_DATA", "") or "").strip().lower()
    if allow not in ("1", "true", "yes"):
        raise HTTPException(403, "Routes démo désactivées en production")


class DemoSeedIn(BaseModel):
    dataset: str = "peya_energy"
    wipe_first: bool = True


class ResetIn(BaseModel):
    full: bool = True


@router.get("/demo-datasets")
def list_demo_datasets(
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("data.reset")),
):
    """Catalogue des jeux de démonstration disponibles."""
    _assert_demo_enabled()
    from app.demo_datasets import list_datasets

    items = []
    for d in list_datasets():
        items.append({
            **d,
            "has_data": db.query(Client).count() > 0,
        })
    return {"datasets": items, "current_clients": db.query(Client).count()}


@router.post("/seed")
def seed_database(
    body: DemoSeedIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("data.reset")),
):
    """Charge un jeu de démonstration au choix."""
    _assert_demo_enabled()
    from app.demo_datasets import get_dataset, load_dataset
    from app.reset_service import reset_business_data

    try:
        meta = get_dataset(body.dataset)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.wipe_first:
        reset_business_data(db)
    stats = load_dataset(db, body.dataset)
    return {
        "ok": True,
        "message": f"Jeu « {meta['name']} » chargé avec succès.",
        "stats": stats,
    }


@router.post("/reset")
def reset_database(
    body: ResetIn = ResetIn(),
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("data.reset")),
):
    """Remise à zéro — tous les utilisateurs sont conservés."""
    _assert_demo_enabled()
    from app.reset_service import reset_application_full, reset_business_data

    if body.full:
        result = reset_application_full(db)
    else:
        result = reset_business_data(db)
        pass
    return {"ok": True, **result}
