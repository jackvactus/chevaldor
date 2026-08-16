"""Chemins données persistants (SQLite, uploads, sauvegardes)."""
from pathlib import Path
import os


def data_root() -> Path:
    env = os.environ.get("PEYA_DATA_DIR", "").strip()
    root = Path(env) if env else Path(__file__).resolve().parent.parent
    root.mkdir(parents=True, exist_ok=True)
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    (root / "backups").mkdir(parents=True, exist_ok=True)
    return root


def clientele_dossiers_root() -> Path:
    root = data_root() / "clientele_dossiers"
    root.mkdir(parents=True, exist_ok=True)
    default = root / "default"
    default.mkdir(parents=True, exist_ok=True)
    return root


def uploads_root() -> Path:
    return data_root() / "uploads"
