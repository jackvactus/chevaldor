"""Phase 2B — réceptions, avoirs fournisseur, relevés bancaires, cessions, paiements."""
from datetime import date

import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.api_guards import require_action
from app.models import User
from app.services.goods_receipt_service import (
    create_goods_receipt, validate_goods_receipt, list_goods_receipts,
)
from app.services.supplier_credit_service import create_supplier_credit_note
from app.services.bank_statement_service import (
    import_bank_csv, match_statement_line, auto_match_statement,
    list_statements, statement_lines,
)
from app.services.asset_disposal_service import dispose_fixed_asset
from app.services.payment_gateway_service import (
    initiate_payment,
    handle_webhook,
    verify_webhook_signature,
    PROVIDERS,
)
from app.services.purchase_workflow_service import (
    create_purchase_request,
    approve_purchase_request,
    create_purchase_order_from_request,
    approve_purchase_order,
    evaluate_three_way_match,
    create_goods_receipt_from_order,
    record_supplier_payment,
)
from app.models_erp import PurchaseRequest, PurchaseRequestLine, PurchaseOrder, PurchaseOrderLine

router = APIRouter(prefix="/api/erp/operations", tags=["operations-advanced"])


# ——— Workflow achats (DA -> BC -> Réception -> Facture) ———

@router.get("/purchase-requests")
def get_purchase_requests(db: Session = Depends(get_db), _: User = Depends(require_action("purchases", "view"))):
    rows = db.query(PurchaseRequest).order_by(PurchaseRequest.date.desc()).all()
    out = []
    for r in rows:
        lines = db.query(PurchaseRequestLine).filter(PurchaseRequestLine.purchase_request_id == r.id).all()
        out.append({
            "id": r.id, "number": r.number, "supplier_id": r.supplier_id,
            "date": str(r.date) if r.date else "", "status": r.status,
            "lines_count": len(lines), "notes": r.notes or "",
        })
    return out


@router.post("/purchase-requests")
def post_purchase_request(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "create")),
):
    if body.get("date") and isinstance(body["date"], str):
        body["date"] = date.fromisoformat(body["date"][:10])
    row = create_purchase_request(db, body, user_id=user.id)
    return {"ok": True, "id": row.id, "number": row.number, "status": row.status}


@router.post("/purchase-requests/{request_id}/approve")
def post_approve_purchase_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "approve")),
):
    try:
        row = approve_purchase_request(db, request_id, user.id)
        return {"ok": True, "id": row.id, "status": row.status}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/purchase-requests/{request_id}/to-order")
def post_request_to_order(
    request_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "approve")),
):
    body = body or {}
    expected = body.get("expected_date")
    expected_date = date.fromisoformat(expected[:10]) if isinstance(expected, str) and expected else None
    try:
        po = create_purchase_order_from_request(db, request_id, expected_date=expected_date, user_id=user.id)
        return {"ok": True, "purchase_order_id": po.id, "number": po.number, "status": po.status}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/purchase-orders")
def get_purchase_orders(db: Session = Depends(get_db), _: User = Depends(require_action("purchases", "view"))):
    rows = db.query(PurchaseOrder).order_by(PurchaseOrder.date.desc()).all()
    out = []
    for r in rows:
        lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == r.id).all()
        total = sum(float((ln.quantity or 0) * (ln.unit_cost or 0)) for ln in lines)
        out.append({
            "id": r.id, "number": r.number, "supplier_id": r.supplier_id,
            "purchase_request_id": r.purchase_request_id, "status": r.status,
            "date": str(r.date) if r.date else "", "expected_date": str(r.expected_date) if r.expected_date else "",
            "lines_count": len(lines), "total": total,
        })
    return out


@router.post("/purchase-orders/{order_id}/approve")
def post_approve_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "approve")),
):
    try:
        row = approve_purchase_order(db, order_id, user.id)
        return {"ok": True, "id": row.id, "status": row.status}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/purchase-orders/{order_id}/to-receipt")
def post_purchase_order_to_receipt(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "create")),
):
    try:
        gr = create_goods_receipt_from_order(db, order_id)
        from app.services.audit_log import log_audit
        log_audit(
            db, "create", "achats", "goods_receipt", gr.id, gr.number or "",
            user.id, user.email or "", "",
        )
        db.commit()
        return {"ok": True, "goods_receipt_id": gr.id, "number": gr.number, "status": gr.status}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/supplier-invoices/{invoice_id}/pay")
def post_supplier_invoice_payment(
    invoice_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("treasury", "create")),
):
    try:
        amount = float(body.get("amount") or 0)
        result = record_supplier_payment(
            db,
            invoice_id,
            amount,
            user_id=user.id,
            movement_type=body.get("type") or "banque_sortie",
            bank_account_id=body.get("bank_account_id"),
            reference=body.get("reference") or "",
        )
        from app.services.audit_log import log_audit
        ip = request.client.host if request.client else ""
        log_audit(
            db, "pay", "achats", "supplier_invoice", invoice_id,
            f"Paiement {result['paid_amount']:.0f}", user.id, user.email or "", ip,
        )
        db.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/supplier-invoices/{invoice_id}/three-way-match")
def post_three_way_match(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("purchases", "approve")),
):
    try:
        return evaluate_three_way_match(db, invoice_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ——— Réceptions marchandises ———

@router.get("/goods-receipts")
def get_goods_receipts(db: Session = Depends(get_db), _: User = Depends(require_action("purchases", "view"))):
    return list_goods_receipts(db)


@router.post("/goods-receipts")
def post_goods_receipt(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "create")),
):
    if not body.get("supplier_id"):
        raise HTTPException(400, "Fournisseur requis")
    if body.get("date") and isinstance(body["date"], str):
        body["date"] = date.fromisoformat(body["date"][:10])
    row = create_goods_receipt(db, body)
    return {"ok": True, "id": row.id, "number": row.number}


@router.post("/goods-receipts/{receipt_id}/validate")
def post_validate_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_action("purchases", "approve")),
):
    try:
        return validate_goods_receipt(db, receipt_id, user_id=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ——— Avoir fournisseur ———

@router.post("/supplier-invoices/{invoice_id}/credit-note")
def post_supplier_credit_note(
    invoice_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("purchases", "create")),
):
    body = body or {}
    try:
        cn = create_supplier_credit_note(
            db, invoice_id,
            amount=body.get("amount"),
            notes=body.get("notes") or "",
        )
        return {"ok": True, "id": cn.id, "number": cn.number, "amount": cn.amount}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ——— Relevés bancaires ———

@router.get("/bank-statements")
def get_bank_statements(db: Session = Depends(get_db), _: User = Depends(require_action("treasury", "view"))):
    return list_statements(db)


@router.get("/bank-statements/{statement_id}/lines")
def get_statement_lines(
    statement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "view")),
):
    return statement_lines(db, statement_id)


@router.post("/bank-statements/import-csv")
async def post_import_bank_csv(
    bank_account_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "create")),
):
    content = (await file.read()).decode("utf-8", errors="replace")
    try:
        return import_bank_csv(db, bank_account_id, content, filename=file.filename or "releve.csv")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/bank-statements/{statement_id}/auto-match")
def post_auto_match(
    statement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "approve")),
):
    try:
        return auto_match_statement(db, statement_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/bank-statements/lines/{line_id}/match")
def post_match_line(
    line_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("treasury", "approve")),
):
    try:
        return match_statement_line(db, line_id, treasury_movement_id=body.get("treasury_movement_id"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ——— Cession immobilisation ———

@router.post("/fixed-assets/{asset_id}/dispose")
def post_dispose_asset(
    asset_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("journal", "create")),
):
    d = body.get("date")
    if d and isinstance(d, str):
        d = date.fromisoformat(d[:10])
    try:
        row = dispose_fixed_asset(
            db, asset_id,
            disposal_date=d,
            proceeds=float(body.get("proceeds") or 0),
            notes=body.get("notes") or "",
        )
        return {"ok": True, "disposal_id": row.id, "journal_entry_id": row.journal_entry_id, "gain_loss": row.gain_loss}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ——— Paiements mobiles ———

@router.get("/payments/providers")
def get_payment_providers(_: User = Depends(require_action("invoices", "view"))):
    return [{"id": p, "label": p.upper()} for p in PROVIDERS]


@router.post("/payments/initiate")
def post_initiate_payment(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_action("invoices", "create")),
):
    try:
        intent = initiate_payment(
            db,
            provider=body.get("provider") or "fedapay",
            invoice_id=int(body["invoice_id"]),
            amount=body.get("amount"),
            currency=body.get("currency") or "XOF",
        )
        return {
            "ok": True,
            "intent_id": intent.id,
            "external_id": intent.external_id,
            "checkout_url": intent.checkout_url,
            "status": intent.status,
        }
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@router.post("/payments/webhook/{provider}")
async def post_payment_webhook(provider: str, request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    sig = (
        request.headers.get("x-webhook-signature")
        or request.headers.get("x-signature")
        or request.headers.get("x-signature-sha256")
    )
    if not verify_webhook_signature(provider, raw, sig):
        raise HTTPException(401, "Signature webhook invalide")
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(400, "Payload webhook invalide") from exc
    return handle_webhook(db, provider, body)


@router.get("/payments/checkout/{external_id}")
def get_checkout_page(external_id: str, db: Session = Depends(get_db)):
    from app.models_erp import PaymentIntent
    intent = db.query(PaymentIntent).filter(PaymentIntent.external_id == external_id).first()
    if not intent:
        raise HTTPException(404, "Paiement introuvable")
    return {
        "external_id": intent.external_id,
        "provider": intent.provider,
        "amount": intent.amount,
        "currency": intent.currency,
        "status": intent.status,
        "message": "Page de paiement — configurez la clé API du fournisseur pour activer le flux réel.",
    }
