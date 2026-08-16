"""Point d'entrée Alembic léger — délègue aux migrations SQLite existantes.

Usage futur : `alembic upgrade head` appellera run_migrations().
Pour l'instant, les migrations sont appliquées au démarrage via app.migrate.
"""
from app.migrate import run_migrations

run_migrations()
