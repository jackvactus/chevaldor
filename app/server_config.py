"""Configuration serveur (URL publique, CORS, hostname, IP) — production / Docker."""
from __future__ import annotations

import os
import socket
from typing import List
from urllib.parse import urlparse


def data_dir() -> str:
    return os.environ.get("PEYA_DATA_DIR", "").strip()


def server_hostname() -> str:
    return (os.environ.get("PEYA_SERVER_HOSTNAME") or socket.gethostname() or "localhost").strip()


def server_ip() -> str:
    explicit = os.environ.get("PEYA_SERVER_IP", "").strip()
    if explicit:
        return explicit
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def app_port() -> int:
    try:
        return int(os.environ.get("PEYA_PORT", "8001"))
    except ValueError:
        return 8001


def host_port() -> int:
    """Port exposé sur l'hôte (Docker : APP_PORT, sinon PEYA_PORT)."""
    raw = os.environ.get("APP_PORT", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return app_port()


def public_base_url() -> str:
    """URL de base pour liens e-mail / UI (sans slash final)."""
    raw = os.environ.get("PEYA_PUBLIC_URL", "").strip().rstrip("/")
    if raw:
        return raw
    scheme = os.environ.get("PEYA_PUBLIC_SCHEME", "http").strip() or "http"
    return f"{scheme}://{server_ip()}:{app_port()}"


def _origin(scheme: str, host: str, port: int) -> str:
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _short_hostname(hostname: str) -> str | None:
    if not hostname or hostname in ("localhost", "127.0.0.1"):
        return None
    short = hostname.split(".", 1)[0]
    return short if short and short != hostname else None


def build_deploy_cors_origins(
    port: int,
    scheme: str = "http",
    *,
    hostname: str,
    ip: str,
    public_url: str = "",
) -> str:
    """Liste CORS pour .env (IP + hostname + localhost)."""
    short = _short_hostname(hostname)
    default_url = f"{scheme}://{ip}:{port}"
    origins: list[str] = [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
        f"{scheme}://{ip}:{port}",
        f"{scheme}://{hostname}:{port}",
    ]
    url = (public_url or default_url).rstrip("/")
    if url not in origins:
        origins.append(url)
    if short:
        origins.append(f"{scheme}://{short}:{port}")
    if scheme == "https":
        origins.extend([f"http://{ip}:{port}", f"http://{hostname}:{port}"])
    seen: dict[str, None] = {}
    for o in origins:
        seen[o] = None
    return ",".join(seen.keys())


def build_cors_origins() -> List[str]:
    """Origines CORS : env + déduction hostname / IP / URL publique."""
    seen: dict[str, None] = {}
    for part in (os.environ.get("PEYA_CORS_ORIGINS") or "").split(","):
        o = part.strip().rstrip("/")
        if o:
            seen[o] = None

    # En production, n'autoriser que la liste explicite (ou l'URL publique HTTPS).
    if is_production():
        if seen:
            return list(seen.keys())
        base = public_base_url().rstrip("/")
        if base.startswith("https://"):
            return [base]
        # Fallback défensif: aucune origine croisée autorisée si config manquante.
        return []

    base = public_base_url()
    parsed = urlparse(base)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or server_ip()
    port = parsed.port or app_port()
    hn = server_hostname()
    short = _short_hostname(hn)

    hosts = [host, server_ip(), hn, short, "localhost", "127.0.0.1"]
    for h in hosts:
        if not h:
            continue
        seen[_origin(scheme, h, port)] = None
        seen[_origin("http", h, port)] = None
        if scheme == "https":
            seen[_origin("https", h, port)] = None

    return list(seen.keys())


def access_urls() -> dict[str, str]:
    """URLs d'accès par IP, hostname et localhost."""
    port = host_port()
    base = public_base_url()
    parsed = urlparse(base)
    scheme = parsed.scheme or "http"
    root = f"{scheme}://"
    return {
        "public": base,
        "ip": f"{root}{server_ip()}:{port}",
        "hostname": f"{root}{server_hostname()}:{port}",
        "local": f"http://localhost:{port}",
        "login_ip": f"{root}{server_ip()}:{port}/login",
        "login_hostname": f"{root}{server_hostname()}:{port}/login",
        "login_local": f"http://localhost:{port}/login",
    }


def print_access_banner() -> None:
    """Affiche les URLs d'accès (dev / deploy)."""
    urls = access_urls()
    print(f"  {urls['login_ip']}     (IP)")
    print(f"  {urls['login_hostname']}  (hostname)")
    print(f"  {urls['login_local']}            (local)")


def app_config_payload() -> dict:
    base = public_base_url()
    urls = access_urls()
    return {
        "public_url": base,
        "hostname": server_hostname(),
        "server_ip": server_ip(),
        "port": app_port(),
        "login_url": f"{base}/login",
        "app_url": f"{base}/app",
        "welcome_url": f"{base}/",
        "api_base": "/api",
        "access_urls": urls,
    }


def is_production() -> bool:
    """True si déploiement production (PEYA_ENV ou PEYA_PRODUCTION)."""
    env = os.environ.get("PEYA_ENV", "").strip().lower()
    if env in ("production", "prod"):
        return True
    return os.environ.get("PEYA_PRODUCTION", "").strip().lower() in ("1", "true", "yes")


def docs_enabled() -> bool:
    """Swagger / OpenAPI — désactivé en production ou si PEYA_DISABLE_DOCS=1."""
    if os.environ.get("PEYA_DISABLE_DOCS", "").strip().lower() in ("1", "true", "yes"):
        return False
    return not is_production()
