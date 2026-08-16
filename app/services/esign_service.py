"""Signature électronique — interne + connecteurs tiers (DocuSign, Yousign)."""
from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models_enterprise_suite import EsignRequest

PROVIDERS = {
    "internal": {"label": "Peya (interne)", "webhook_env": ""},
    "docusign": {"label": "DocuSign", "webhook_env": "PEYA_DOCUSIGN_WEBHOOK"},
    "yousign": {"label": "Yousign", "webhook_env": "PEYA_YOUSIGN_WEBHOOK"},
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _signing_url(token: str) -> str:
    return f"/esign-sign.html?token={token}"


def create_esign_with_provider(
    db: Session,
    document_type: str,
    document_id: int,
    signer_email: str,
    signer_name: str,
    provider: str = "internal",
) -> EsignRequest:
    provider = (provider or "internal").lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Prestataire inconnu : {provider}")
    token = secrets.token_urlsafe(32)
    provider_ref = f"{provider}-{uuid.uuid4().hex[:12]}"
    obj = EsignRequest(
        document_type=document_type,
        document_id=document_id,
        signer_email=signer_email,
        signer_name=signer_name,
        status="pending",
        provider=provider,
        signing_token=token,
        provider_ref=provider_ref,
        signing_url=_signing_url(token),
        created_at=_now(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    if provider != "internal":
        _notify_provider(obj)
    return obj


def _notify_provider(req: EsignRequest) -> None:
    """Envoie la demande au webhook du prestataire si configuré (sinon mode simulation)."""
    cfg = PROVIDERS.get(req.provider or "internal", {})
    webhook = os.environ.get(cfg.get("webhook_env", ""), "")
    if not webhook:
        return
    try:
        import urllib.request
        payload = json.dumps({
            "provider_ref": req.provider_ref,
            "signer_email": req.signer_email,
            "signer_name": req.signer_name,
            "document_type": req.document_type,
            "document_id": req.document_id,
            "callback_url": f"/api/portal/esign/webhook/{req.provider}",
            "signing_url": req.signing_url,
        }).encode()
        urllib.request.urlopen(
            urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST"),
            timeout=12,
        )
    except Exception:
        pass


def get_esign_by_token(db: Session, token: str) -> EsignRequest:
    row = db.query(EsignRequest).filter(EsignRequest.signing_token == token).first()
    if not row:
        raise ValueError("Lien de signature invalide")
    return row


def sign_by_token(db: Session, token: str, signer_name: str = "") -> EsignRequest:
    row = get_esign_by_token(db, token)
    if row.status == "signed":
        return row
    if signer_name:
        row.signer_name = signer_name
    row.status = "signed"
    row.signed_at = _now()
    db.commit()
    db.refresh(row)
    return row


def webhook_provider_update(db: Session, provider: str, provider_ref: str, status: str) -> Optional[EsignRequest]:
    row = db.query(EsignRequest).filter(
        EsignRequest.provider == provider,
        EsignRequest.provider_ref == provider_ref,
    ).first()
    if not row:
        return None
    if status in ("signed", "completed"):
        row.status = "signed"
        row.signed_at = _now()
    elif status in ("rejected", "declined"):
        row.status = "rejected"
    db.commit()
    db.refresh(row)
    return row
