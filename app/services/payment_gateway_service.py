"""Connecteurs paiement UEMOA — FedaPay, Mixx by Yas, Flooz (T-Money)."""
from __future__ import annotations

import json
import os
import uuid
import hmac
import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Invoice
from app.models_erp import PaymentIntent
from app.server_config import is_production


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


PROVIDERS = ("fedapay", "mixx", "flooz", "cinetpay")


def _provider_config(provider: str) -> dict:
    key = provider.upper()
    return {
        "api_key": os.getenv(f"{key}_API_KEY", ""),
        "webhook_secret": os.getenv(f"{key}_WEBHOOK_SECRET", ""),
        "sandbox": os.getenv(f"{key}_SANDBOX", "true").lower() == "true",
    }


def verify_webhook_signature(provider: str, raw_body: bytes, signature: str | None) -> bool:
    """Valide la signature HMAC SHA256 du webhook."""
    cfg = _provider_config(provider)
    secret = (cfg.get("webhook_secret") or "").strip()
    sig = (signature or "").strip()
    if not secret:
        return not is_production()
    if not sig:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.lower())


def initiate_payment(
    db: Session,
    *,
    provider: str,
    invoice_id: int,
    amount: float | None = None,
    currency: str = "XOF",
) -> PaymentIntent:
    provider = (provider or "").lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Fournisseur inconnu : {provider}")

    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise ValueError("Facture introuvable")

    amt = float(amount if amount is not None else (inv.amount or 0) - (inv.paid or 0))
    if amt <= 0:
        raise ValueError("Montant à encaisser invalide")

    cfg = _provider_config(provider)
    ext_id = f"{provider}-{uuid.uuid4().hex[:12]}"
    base_url = os.getenv("PUBLIC_APP_URL", "http://localhost:8000")
    checkout = f"{base_url}/api/erp/operations/payments/checkout/{ext_id}"

    if cfg["api_key"]:
        # Intégration réelle : appeler l'API du fournisseur ici
        pass

    intent = PaymentIntent(
        provider=provider,
        external_id=ext_id,
        invoice_id=invoice_id,
        amount=amt,
        currency=currency,
        status="pending",
        checkout_url=checkout,
        metadata_json=json.dumps({"invoice_number": inv.number, "sandbox": cfg["sandbox"]}),
        created_at=_now(),
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    return intent


def handle_webhook(db: Session, provider: str, payload: dict) -> dict:
    """Traitement webhook — marque payé et met à jour la facture."""
    provider = (provider or "").lower()
    ext_id = payload.get("id") or payload.get("transaction_id") or payload.get("external_id")
    status = (payload.get("status") or "").lower()

    intent = None
    if ext_id:
        intent = db.query(PaymentIntent).filter(
            PaymentIntent.external_id == str(ext_id),
            PaymentIntent.provider == provider,
        ).first()
    if not intent and payload.get("invoice_id"):
        intent = db.query(PaymentIntent).filter(
            PaymentIntent.invoice_id == int(payload["invoice_id"]),
            PaymentIntent.provider == provider,
            PaymentIntent.status == "pending",
        ).order_by(PaymentIntent.id.desc()).first()

    if not intent:
        return {"ok": False, "reason": "intent_not_found"}

    if status in ("approved", "paid", "success", "completed"):
        intent.status = "paid"
        inv = db.query(Invoice).filter(Invoice.id == intent.invoice_id).first()
        if inv:
            inv.paid = float(inv.paid or 0) + float(intent.amount or 0)
            if inv.paid >= float(inv.amount or 0) - 0.01:
                inv.status = "payée"
        from app.services.treasury_advanced_service import create_treasury_from_payment
        from app.services.notification_engine import notify_payment_received
        create_treasury_from_payment(
            db,
            amount=float(intent.amount or 0),
            label=f"Paiement {provider} — {inv.number if inv else intent.external_id}",
            reference=intent.external_id or "",
            payment_method="mobile_money",
        )
        db.commit()
        try:
            notify_payment_received(db, float(intent.amount or 0), inv.number if inv else intent.external_id)
        except Exception:
            pass
        return {"ok": True, "intent_id": intent.id, "status": "paid"}

    if status in ("failed", "cancelled", "declined"):
        intent.status = "failed" if status != "cancelled" else "cancelled"
        db.commit()
        return {"ok": True, "intent_id": intent.id, "status": intent.status}

    return {"ok": True, "intent_id": intent.id, "status": intent.status}
