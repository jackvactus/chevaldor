"""Sauvegarde et restauration de la base SQLite Peya ERP."""
from __future__ import annotations

import gc
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.database import DB_PATH, release_db_connections
from app.paths import data_root

SQLITE_MAGIC = b"SQLite format 3\x00"
MIN_DB_BYTES = 512
MAX_DB_BYTES = int(os.environ.get("PEYA_MAX_DB_UPLOAD_MB", "512")) * 1024 * 1024

# Tables minimales attendues pour une base Peya exploitable
REQUIRED_TABLES = frozenset({"users", "clients", "system_settings"})

BACKUP_GLOBS = (
    "peya_backup_*.db",
    "peya_pre_restore_*.db",
    "peya_upload_*.db",
    "backup_*.db",
)


def backups_dir() -> Path:
    d = data_root() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_sqlite_file(path: Path) -> dict[str, Any]:
    """Vérifie en-tête SQLite, intégrité et tables métier minimales."""
    if not path.is_file():
        raise ValueError("Fichier introuvable")
    size = path.stat().st_size
    if size < MIN_DB_BYTES:
        raise ValueError("Fichier trop petit pour être une base SQLite valide")
    if size > MAX_DB_BYTES:
        raise ValueError(f"Fichier trop volumineux (max {MAX_DB_BYTES // (1024 * 1024)} Mo)")

    with open(path, "rb") as fh:
        if fh.read(16) != SQLITE_MAGIC:
            raise ValueError("Le fichier n'est pas une base SQLite valide (.db)")

    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Intégrité SQLite compromise : {integrity}")
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ValueError(
                "Base incompatible avec Peya ERP — tables manquantes : "
                + ", ".join(sorted(missing))
            )
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        clients = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        return {
            "size_bytes": size,
            "size_mb": round(size / (1024 * 1024), 2),
            "table_count": len(tables),
            "users": users,
            "clients": clients,
            "integrity": integrity,
        }
    finally:
        conn.close()


def create_backup(prefix: str = "peya_backup") -> Path:
    """Copie la base active dans le dossier backups/ (API SQLite — cohérent même si BDD ouverte)."""
    if not DB_PATH.exists():
        raise ValueError("Base de données active introuvable")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups_dir() / f"{prefix}_{stamp}.db"
    if dest.exists():
        dest.unlink()
    sqlite3.connect(str(dest)).close()
    src = sqlite3.connect(str(DB_PATH.resolve()), timeout=60)
    dst = sqlite3.connect(str(dest.resolve()), timeout=60)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    return dest


def _sqlite_hot_restore(source: Path, dest_path: Path) -> None:
    """
    Restaure source dans la base active via l'API backup() de SQLite.
    Évite os.replace() qui échoue sous Windows quand le fichier est verrouillé.
    """
    src_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    last_err: BaseException | None = None

    for attempt in range(6):
        try:
            release_db_connections()
            if attempt:
                time.sleep(0.35 * attempt)

            src = sqlite3.connect(src_uri, uri=True, timeout=90)
            dst = sqlite3.connect(str(dest_path.resolve()), timeout=90)
            try:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                dst.commit()
                row = dst.execute("PRAGMA integrity_check").fetchone()
                if row and row[0] != "ok":
                    raise ValueError(f"Intégrité après restauration : {row[0]}")
            finally:
                dst.close()
                src.close()

            for sidecar in (Path(f"{dest_path}-wal"), Path(f"{dest_path}-shm")):
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                    except OSError:
                        pass
            return
        except (sqlite3.Error, OSError, ValueError) as exc:
            last_err = exc
            gc.collect()

    # Secours : remplacement fichier si plus aucun verrou (hors Windows actif)
    release_db_connections()
    time.sleep(0.8)
    tmp = dest_path.with_suffix(".db.restoring")
    try:
        shutil.copy2(source, tmp)
        os.replace(str(tmp), str(dest_path))
        return
    except OSError as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        hint = (
            "La base est verrouillée par le serveur (Windows). "
            "Réessayez dans quelques secondes ou arrêtez start.bat, "
            "remplacez peya_company.db manuellement depuis backups/, puis relancez."
        )
        raise ValueError(f"Impossible de restaurer la base active : {hint}") from (last_err or exc)

    raise ValueError("Restauration impossible") from last_err


def list_backups(limit: int = 30) -> list[dict[str, Any]]:
    """Liste les sauvegardes disponibles sur le serveur."""
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for pattern in BACKUP_GLOBS:
        for f in backups_dir().glob(pattern):
            if f.name in seen:
                continue
            seen.add(f.name)
            st = f.stat()
            items.append({
                "filename": f.name,
                "size_mb": round(st.st_size / (1024 * 1024), 2),
                "size_bytes": st.st_size,
                "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "kind": _backup_kind(f.name),
            })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[:limit]


def _backup_kind(name: str) -> str:
    if name.startswith("peya_pre_restore_"):
        return "pre_restore"
    if name.startswith("peya_upload_"):
        return "upload"
    if name.startswith("peya_backup_"):
        return "auto"
    return "manual"


def resolve_backup_path(filename: str) -> Path:
    """Résout un nom de fichier dans backups/ (anti path traversal)."""
    base = Path(filename).name
    if base != filename or ".." in base:
        raise ValueError("Nom de fichier invalide")
    if not base.lower().endswith(".db"):
        raise ValueError("Extension .db requise")
    root = backups_dir().resolve()
    path = (root / base).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError("Chemin invalide")
    if not path.is_file():
        raise ValueError("Sauvegarde introuvable sur le serveur")
    return path


def save_uploaded_database(data: bytes, original_name: str) -> tuple[Path, dict[str, Any]]:
    """Enregistre un upload validé dans backups/ sans remplacer la base active."""
    if len(data) > MAX_DB_BYTES:
        raise ValueError(f"Fichier trop volumineux (max {MAX_DB_BYTES // (1024 * 1024)} Mo)")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = Path(original_name or "upload.db").name
    if not safe.lower().endswith(".db"):
        safe = f"{safe}.db"
    dest = backups_dir() / f"peya_upload_{stamp}_{safe}"
    dest.write_bytes(data)
    meta = validate_sqlite_file(dest)
    meta["filename"] = dest.name
    return dest, meta


def restore_database(source: Path) -> dict[str, Any]:
    """Remplace le contenu de la base active par source (sauvegarde de sécurité avant)."""
    meta = validate_sqlite_file(source)
    pre = create_backup("peya_pre_restore")
    _sqlite_hot_restore(source, DB_PATH)

    from app.migrate import run_migrations

    run_migrations()

    return {
        "ok": True,
        "restored_from": source.name,
        "pre_restore_backup": pre.name,
        "meta": meta,
    }


def delete_backup(filename: str) -> None:
    path = resolve_backup_path(filename)
    if path.name == "peya_company.db":
        raise ValueError("Suppression interdite")
    path.unlink()
