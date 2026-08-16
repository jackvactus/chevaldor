"""Limites de taille et types pour les fichiers uploadés."""
import os
from pathlib import Path

from fastapi import HTTPException, UploadFile

MAX_UPLOAD_BYTES = int(os.environ.get("PEYA_MAX_UPLOAD_MB", "15")) * 1024 * 1024
MAX_DB_UPLOAD_BYTES = int(os.environ.get("PEYA_MAX_DB_UPLOAD_MB", "512")) * 1024 * 1024

SPREADSHEET_EXT = {".xlsx", ".xls", ".xlsm", ".csv", ".ods"}
DATABASE_EXT = {".db", ".sqlite", ".sqlite3"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}


async def read_bounded(file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Lit le corps du fichier avec une limite stricte."""
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"Fichier trop volumineux (max {max_bytes // (1024 * 1024)} Mo)")
        chunks.append(chunk)
    return b"".join(chunks)


def assert_extension(filename: str | None, allowed: set[str]) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Type de fichier non autorisé ({ext or 'sans extension'})")
