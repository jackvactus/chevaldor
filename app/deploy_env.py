"""Génération .env Docker — détection hostname/IP de l'hôte (pas du conteneur)."""
from __future__ import annotations

import argparse
import os
import platform
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.server_config import build_deploy_cors_origins, print_access_banner, server_ip


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def read_env_dict(repo_root: Path) -> dict[str, str]:
    env_path = repo_root / ".env"
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key:
            out[key] = value
    return out


def load_env_file(repo_root: Path) -> None:
    for key, value in read_env_dict(repo_root).items():
        os.environ.setdefault(key, value)


def detect_host_hostname() -> str:
    """Hostname de la machine hôte (exécuté avant docker compose)."""
    explicit = (os.environ.get("SERVER_HOSTNAME") or "").strip()
    if explicit:
        return explicit.lower()
    if platform.system() != "Windows":
        for args in (["hostname", "-f"], ["hostname"]):
            try:
                r = subprocess.run(
                    args, capture_output=True, text=True, timeout=5, check=False
                )
                h = (r.stdout or "").strip().lower()
                if r.returncode == 0 and h and h not in ("(none)", "localhost"):
                    return h
            except (OSError, subprocess.TimeoutExpired):
                continue
    import socket

    return (socket.gethostname() or "localhost").strip().lower()


def detect_host_ip() -> str:
    """IP principale de l'hôte — route vers Internet."""
    explicit = (os.environ.get("SERVER_IP") or "").strip()
    if explicit:
        return explicit
    if platform.system() != "Windows":
        try:
            r = subprocess.run(
                ["ip", "-4", "route", "get", "1.1.1.1"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            m = re.search(r"\bsrc\s+(\S+)", r.stdout or "")
            if m and m.group(1) != "127.0.0.1":
                return m.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            r = subprocess.run(
                ["hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for ip in (r.stdout or "").split():
                if ip and ip != "127.0.0.1":
                    return ip
        except (OSError, subprocess.TimeoutExpired):
            pass
    return server_ip()


def detect_host_ips() -> list[str]:
    """Toutes les IPv4 de l'hôte (CORS multi-interfaces)."""
    ips: list[str] = []
    primary = detect_host_ip()
    if primary:
        ips.append(primary)
    if platform.system() != "Windows":
        try:
            r = subprocess.run(
                ["hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for ip in (r.stdout or "").split():
                if ip and ip != "127.0.0.1" and ip not in ips:
                    ips.append(ip)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ips


def build_deploy_vars(existing: dict[str, str] | None = None) -> dict[str, str]:
    existing = existing or {}
    container_port = _env_int("PEYA_PORT", int(existing.get("PEYA_PORT", "8001")))
    host_port = _env_int("APP_PORT", int(existing.get("APP_PORT", str(container_port))))
    scheme = (os.environ.get("PUBLIC_SCHEME") or existing.get("PEYA_PUBLIC_SCHEME") or "http").strip() or "http"

    hostname = detect_host_hostname()
    ip = detect_host_ip()

    public_url = (os.environ.get("PEYA_PUBLIC_URL") or existing.get("PEYA_PUBLIC_URL") or "").strip().rstrip("/")
    if not public_url:
        public_url = f"{scheme}://{ip}:{host_port}"

    cors = build_deploy_cors_origins(
        host_port, scheme, hostname=hostname, ip=ip, public_url=public_url
    )
    # Interfaces réseau supplémentaires
    extra: list[str] = []
    for alt_ip in detect_host_ips():
        if alt_ip == ip:
            continue
        for origin in (f"{scheme}://{alt_ip}:{host_port}", f"http://{alt_ip}:{host_port}"):
            if origin not in cors:
                extra.append(origin)
    if extra:
        cors = cors + "," + ",".join(extra)

    jwt = (
        (os.environ.get("PEYA_JWT_SECRET") or "").strip()
        or existing.get("PEYA_JWT_SECRET", "").strip()
        or secrets.token_hex(32)
    )
    admin_email = (
        (os.environ.get("PEYA_ADMIN_EMAIL") or "").strip()
        or existing.get("PEYA_ADMIN_EMAIL", "").strip()
    )
    if not admin_email:
        hn = hostname
        admin_email = f"admin@{hn}" if hn not in ("localhost", "127.0.0.1") else f"admin@{secrets.token_hex(4)}.local"
    admin_password = (
        (os.environ.get("PEYA_ADMIN_PASSWORD") or "").strip()
        or existing.get("PEYA_ADMIN_PASSWORD", "").strip()
        or secrets.token_hex(12)
    )
    max_mb = (
        os.environ.get("PEYA_MAX_UPLOAD_MB")
        or existing.get("PEYA_MAX_UPLOAD_MB")
        or "15"
    ).strip() or "15"

    return {
        "APP_PORT": str(host_port),
        "PEYA_PORT": str(container_port),
        "PEYA_HOST": "0.0.0.0",
        "PEYA_ENV": "production",
        "PEYA_PUBLIC_URL": public_url,
        "PEYA_PUBLIC_SCHEME": scheme,
        "PEYA_SERVER_HOSTNAME": hostname,
        "PEYA_SERVER_IP": ip,
        "PEYA_CORS_ORIGINS": cors,
        "PEYA_JWT_SECRET": jwt,
        "PEYA_ADMIN_EMAIL": admin_email,
        "PEYA_ADMIN_PASSWORD": admin_password,
        "PEYA_MAX_UPLOAD_MB": max_mb,
        "PEYA_RELOAD": "0",
        "PEYA_DATA_DIR": "/data",
    }


def write_env_file(repo_root: Path) -> Path:
    existing = read_env_dict(repo_root)
    vars_ = build_deploy_vars(existing)
    env_path = repo_root / ".env"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"# Généré par deploy.sh — {stamp}", ""]
    lines.extend(f"{k}={v}" for k, v in vars_.items())
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    return env_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Génère .env Docker (hostname/IP hôte)")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Racine du dépôt",
    )
    parser.add_argument("--print-urls", action="store_true", help="Affiche les URLs d'accès")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.print_urls:
        load_env_file(root)
        os.environ.setdefault("APP_PORT", os.environ.get("PEYA_PORT", "8001"))
        print_access_banner()
        return 0

    path = write_env_file(root)
    vars_ = build_deploy_vars(read_env_dict(root))
    print(f"[deploy-env] {path}")
    print(f"[deploy-env] hôte hostname={vars_['PEYA_SERVER_HOSTNAME']} ip={vars_['PEYA_SERVER_IP']}")
    print(f"[deploy-env] port hôte={vars_['APP_PORT']} conteneur={vars_['PEYA_PORT']}")
    print(f"[deploy-env] url={vars_['PEYA_PUBLIC_URL']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
