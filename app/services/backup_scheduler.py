"""Sauvegarde automatique SQLite selon paramètres système."""
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from app.database import DB_PATH, SessionLocal
from app.paths import data_root
from app.models_prefs import SystemSettings


def _should_run(s: SystemSettings, now: datetime) -> bool:
    if not s or not s.backup_enabled:
        return False
    last = (s.backup_last_run or "").strip()
    if not last:
        return True
    try:
        last_dt = datetime.strptime(last[:15], "%Y%m%d_%H%M%S")
    except ValueError:
        return True
    freq = (s.backup_frequency or "daily").lower()
    delta = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(days=7)}
    return now - last_dt >= delta.get(freq, timedelta(days=1))


def _prune_old(backups_dir: Path, retention_days: int):
    if retention_days <= 0:
        return
    cutoff = datetime.now() - timedelta(days=retention_days)
    for p in backups_dir.glob("peya_backup_*.db"):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                p.unlink(missing_ok=True)
        except OSError:
            pass


def run_backup_if_due() -> dict | None:
    if not DB_PATH.exists():
        return None
    db = SessionLocal()
    try:
        s = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
        now = datetime.now()
        if not _should_run(s, now):
            return None
        backup_dir = data_root() / "backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = now.strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"peya_backup_{stamp}.db"
        shutil.copy2(DB_PATH, dest)
        s.backup_last_run = stamp
        db.commit()
        _prune_old(backup_dir, int(s.backup_retention_days or 30))
        return {"ok": True, "filename": dest.name}
    finally:
        db.close()


def start_backup_scheduler(interval_sec: int = 3600):
    """Thread daemon — vérifie toutes les heures."""

    def _loop():
        while True:
            try:
                run_backup_if_due()
            except Exception:
                pass
            time.sleep(interval_sec)

    t = threading.Thread(target=_loop, name="peya-backup-scheduler", daemon=True)
    t.start()
