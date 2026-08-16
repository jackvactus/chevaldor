"""Configuration SQLAlchemy.

Supporte SQLite par défaut (fichier local) ou PostgreSQL via la variable
`DATABASE_URL` d'environnement. Pour PostgreSQL la variable prend la priorité.
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from app.paths import data_root

# Par défaut : base SQLite locale
DB_PATH = data_root() / "peya_company.db"
default_sqlite = f"sqlite:///{DB_PATH.as_posix()}"

# Permettre à l'environnement d'imposer la base de données (Postgres, etc.)
DATABASE_URL = os.environ.get("DATABASE_URL", default_sqlite)


def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Crée l'engine en adaptant les options selon le dialecte
engine_kwargs = {
    "echo": False,
}
connect_args = None
if DATABASE_URL.startswith("sqlite:"):
    connect_args = {"check_same_thread": False}

if connect_args:
    engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
else:
    engine = create_engine(DATABASE_URL, **engine_kwargs)

# Si sqlite, appliquer le PRAGMA lors de la connexion
if DATABASE_URL.startswith("sqlite:"):
    event.listen(engine, "connect", _set_sqlite_pragma)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def release_db_connections() -> None:
    """Ferme toutes les connexions du pool (requis avant restauration SQLite sous Windows)."""
    import gc
    import time

    engine.dispose()
    gc.collect()
    time.sleep(0.15)

def get_db():
    """Session par requête : rollback si erreur, commit si la route n'a pas levé d'exception."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_session_active(db) -> None:
    """Réinitialise la session après un rollback interne (évite PendingRollbackError)."""
    from sqlalchemy import text
    from sqlalchemy.exc import PendingRollbackError, InvalidRequestError

    try:
        db.execute(text("SELECT 1"))
    except (PendingRollbackError, InvalidRequestError):
        db.rollback()
    except Exception:
        db.rollback()
