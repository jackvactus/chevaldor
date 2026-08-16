"""Réinitialise le mot de passe admin (à lancer si connexion / restauration impossible)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.auth import hash_password
from app.bootstrap import _FALLBACK_ADMIN_EMAIL, _FALLBACK_ADMIN_PASSWORD, _bootstrap_admin_credentials
from app.database import SessionLocal
from app.models import User
from app.migrate import run_migrations
from app.services.security_service import get_user_security

# Mot de passe cible : env PEYA_ADMIN_PASSWORD, sinon valeur de secours hors prod
try:
    ADMIN_EMAIL, NEW_PASSWORD = _bootstrap_admin_credentials()
except Exception:
    ADMIN_EMAIL = (os.environ.get("PEYA_ADMIN_EMAIL") or _FALLBACK_ADMIN_EMAIL).strip().lower()
    NEW_PASSWORD = (os.environ.get("PEYA_ADMIN_PASSWORD") or _FALLBACK_ADMIN_PASSWORD).strip()


def main():
    run_migrations()
    db = SessionLocal()
    user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if not user:
        user = db.query(User).filter(User.username == "admin").first()
    if not user:
        from app.bootstrap import ensure_admin_user
        ensure_admin_user(db)
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not user:
            user = db.query(User).filter(User.username == "admin").first()
    if not user:
        print("ERREUR — aucun compte admin trouvé")
        db.close()
        sys.exit(1)

    user.password_hash = hash_password(NEW_PASSWORD)
    user.must_change_password = False
    user.is_active = True
    if not user.username:
        user.username = "admin"
    sec = get_user_security(db, user.id)
    sec.failed_login_attempts = 0
    sec.locked_until = ""
    db.commit()
    print("OK — Compte admin réinitialisé")
    print(f"  Email      : {user.email}")
    print(f"  Utilisateur: {user.username}")
    print(f"  Mot de passe: {NEW_PASSWORD}")
    db.close()


if __name__ == "__main__":
    main()
