"""Middleware : protection JWT sur /api/*."""
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth import decode_token, is_session_revoked
from app.database import SessionLocal
from app.models import User
from app.server_config import docs_enabled

PASSWORD_CHANGE_ALLOWED = (
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/change-password-required",
    "/api/auth/login-history",
    "/api/auth/password-policy",
)

def _public_prefixes():
    base = (
        "/api/auth/login",
        "/api/auth/login/2fa",
        "/api/auth/password-policy",
        "/api/auth/forgot-password",
        "/api/health",
        "/api/public/region",
        "/api/public/",
        "/api/portal/",
    )
    if docs_enabled():
        return base + ("/docs", "/redoc", "/openapi.json")
    return base


PUBLIC_PREFIXES = _public_prefixes()


async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"detail": "Authentification requise"}, status_code=401)

    token = auth[7:]
    db = SessionLocal()
    try:
        payload = decode_token(token)
        if is_session_revoked(db, payload):
            return JSONResponse({"detail": "Session révoquée"}, status_code=401)
        user = db.query(User).filter(
            User.id == int(payload["sub"]),
            User.is_active == True,
        ).first()
        if not user:
            return JSONResponse({"detail": "Session invalide"}, status_code=401)
        request.state.user = user
        from app.services.password_service import user_security_flags

        flags = user_security_flags(user, db)
        request.state.requires_password_change = flags["requires_password_change"]
    except Exception:
        return JSONResponse({"detail": "Session expirée"}, status_code=401)
    finally:
        db.close()

    if getattr(request.state, "requires_password_change", False):
        if not any(path.startswith(p) for p in PASSWORD_CHANGE_ALLOWED):
            return JSONResponse(
                {
                    "detail": "Vous devez changer votre mot de passe avant de continuer",
                    "code": "change_password_required",
                },
                status_code=403,
            )

    return await call_next(request)
