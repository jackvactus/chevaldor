"""
Middleware : audit automatique des actions sensibles.

Objectif : donner à l'admin un journal complet par acteur (utilisateur JWT),
avec IP, user-agent et une trace générique (méthode HTTP + chemin).
"""

import re
from typing import Optional, Tuple

from fastapi import HTTPException
from starlette.requests import Request

from app.database import SessionLocal
from app.services.audit_log import log_audit

# Requêtes GET bruyantes à ne pas journaliser (polling, branding, session).
_SKIP_GET_PREFIXES = (
    "/api/health",
    "/api/auth/me",
    "/api/cms/branding",
    "/api/cms/public",
    "/api/notifications",
    "/api/dashboard/cockpit",
    "/api/enhanced/cockpit",
    "/api/erp/audit-logs",
    "/static/",
    "/favicon",
)


def _should_skip_get(path: str) -> bool:
    p = path or ""
    return any(p.startswith(prefix) for prefix in _SKIP_GET_PREFIXES)


def _split_path(path: str) -> list[str]:
    return [p for p in (path or "").split("/") if p]


def _infer_module_entity(path: str) -> Tuple[str, str]:
    parts = _split_path(path)
    prefix = parts[1] if len(parts) > 1 and parts[0] == "api" else (parts[0] if parts else "")

    module_map = {
        "clients": "crm",
        "deals": "commercial",
        "quotes": "ventes",
        "invoices": "ventes",
        "suppliers": "achats",
        "supplier-invoices": "achats",
        "stock": "stock",
        "stock-movements": "stock",
        "projects": "projects",
        "tasks": "projects",
        "trainings": "hr",
        "trainees": "hr",
        "accounts": "compta",
        "transactions": "compta",
        "journal-entries": "compta",
        "calendar": "paramètres",
        "settings": "paramètres",
        "roles": "admin",
        "users": "admin",
        "auth": "admin",
        "erp": "admin",
        "import": "paramètres",
        "exports": "paramètres",
        "backup": "paramètres",
        "enterprise": "admin",
        "syscohada": "compta",
        "finance": "compta",
        "bi": "compta",
    }

    entity_map = {
        "clients": "client",
        "deals": "deal",
        "quotes": "quote",
        "invoices": "invoice",
        "suppliers": "supplier",
        "supplier-invoices": "supplier_invoice",
        "stock": "stock_item",
        "stock-movements": "stock_movement",
        "projects": "project",
        "tasks": "task",
        "trainings": "training",
        "trainees": "trainee",
        "accounts": "account",
        "transactions": "transaction",
        "journal-entries": "journal_entry",
        "calendar": "calendar_event",
        "settings": "settings",
        "roles": "role",
        "users": "user",
        "auth": "auth",
        "erp": "erp_action",
        "import": "import",
        "enterprise": "enterprise",
        "backup": "backup",
        "exports": "export",
        "syscohada": "syscohada",
        "finance": "finance_report",
        "bi": "bi_report",
    }

    module = module_map.get(prefix, prefix or "admin")
    entity = entity_map.get(prefix, prefix or "request")
    return module, entity


def _infer_entity_id(path: str) -> Optional[int]:
    parts = _split_path(path)
    ids = []
    for p in parts:
        if p.isdigit():
            try:
                ids.append(int(p))
            except Exception:
                pass
    return ids[-1] if ids else None


def _infer_action(method: str) -> Optional[str]:
    return {
        "GET": "view",
        "POST": "create",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "delete",
    }.get(method)


async def audit_middleware(request: Request, call_next):
    method_action = _infer_action(request.method)
    path = request.url.path or ""

    if not path.startswith("/api/") or not method_action:
        return await call_next(request)

    if method_action == "view" and _should_skip_get(path):
        return await call_next(request)

    if path.rstrip("/") == "/api/auth/logout":
        return await call_next(request)

    if path.rstrip("/") == "/api/erp/activity-log":
        return await call_next(request)

    user = getattr(request.state, "user", None)
    if not user:
        return await call_next(request)

    ip = request.client.host if request.client else ""
    ua = (request.headers.get("user-agent", "") or "")[:200]
    module, entity_type = _infer_module_entity(path)
    entity_id = _infer_entity_id(path)

    status_code = 0
    exc_detail = ""
    try:
        response = await call_next(request)
        status_code = getattr(response, "status_code", 0) or 0
        return response
    except HTTPException as e:
        status_code = getattr(e, "status_code", 400) or 400
        exc_detail = str(getattr(e, "detail", "") or "")
        raise
    except Exception as e:
        status_code = 500
        exc_detail = str(e)[:300]
        raise
    finally:
        # Skip logging for view requests that returned client/server errors
        should_skip_log = status_code and status_code >= 400 and method_action == "view"
        if not should_skip_log:
            db = SessionLocal()
            try:
                qs = request.url.query or ""
                qs = f"?{qs}" if qs else ""
                detail = f"HTTP {request.method} {path}{qs} status={status_code}"
                if exc_detail:
                    detail += f" | error={exc_detail[:200]}"

                log_audit(
                    db,
                    method_action,
                    module,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    detail=detail,
                    user_id=user.id,
                    user_email=getattr(user, "email", "") or "",
                    ip=ip,
                    user_agent=ua,
                )
                db.commit()
            except Exception:
                pass
            finally:
                db.close()
