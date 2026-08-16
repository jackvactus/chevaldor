"""API Trésorerie Phase P1 — dashboard, prévisions, imports relevés."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.database import get_db
from app.models import User
from app.services.bank_statement_service import (
    import_bank_csv,
    import_bank_excel,
    import_bank_ofx,
    auto_match_statement,
    list_statements,
    statement_lines,
)
from app.services.payment_gateway_service import PROVIDERS, initiate_payment
from app.services.treasury_advanced_service import cashflow_forecast, treasury_dashboard

router = APIRouter(prefix="/api/erp/treasury-p1", tags=["treasury-p1"])


@router.get("/dashboard")
def get_treasury_dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "view")),
):
    return treasury_dashboard(db)


@router.get("/cashflow-forecast")
def get_cashflow_forecast(
    days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "view")),
):
    return cashflow_forecast(db, days=days)


@router.get("/payment-providers")
def get_payment_providers(_: User = Depends(require_action("treasury", "view"))):
    return {"providers": list(PROVIDERS), "labels": {
        "fedapay": "FedaPay", "mixx": "Mixx by Yas", "flooz": "Flooz T-Money", "cinetpay": "CinetPay",
    }}


@router.post("/payments/initiate")
def treasury_initiate_payment(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "create")),
):
    try:
        intent = initiate_payment(
            db,
            provider=body.get("provider", "fedapay"),
            invoice_id=int(body["invoice_id"]),
            amount=body.get("amount"),
        )
        return {
            "ok": True,
            "intent_id": intent.id,
            "checkout_url": intent.checkout_url,
            "external_id": intent.external_id,
            "status": intent.status,
        }
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@router.get("/bank-statements")
def treasury_list_statements(db: Session = Depends(get_db), _: User = Depends(require_action("treasury", "view"))):
    return list_statements(db)


@router.get("/bank-statements/{statement_id}/lines")
def treasury_statement_lines(
    statement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "view")),
):
    return statement_lines(db, statement_id)


@router.post("/bank-statements/import")
async def treasury_import_statement(
    bank_account_id: int = Query(...),
    format: str = Query("csv"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "create")),
):
    raw = await file.read()
    fname = file.filename or "releve"
    fmt = (format or "csv").lower()
    try:
        if fmt == "excel" or fname.endswith((".xlsx", ".xls")):
            return import_bank_excel(db, bank_account_id, raw, filename=fname)
        if fmt == "ofx" or fname.endswith(".ofx"):
            return import_bank_ofx(db, bank_account_id, raw.decode("utf-8", errors="replace"), filename=fname)
        return import_bank_csv(db, bank_account_id, raw.decode("utf-8", errors="replace"), filename=fname)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/bank-statements/{statement_id}/auto-match")
def treasury_auto_match(
    statement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "approve")),
):
    try:
        return auto_match_statement(db, statement_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
