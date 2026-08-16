"""Rôles personnalisés, surcharges matrice et permissions."""
from sqlalchemy import Column, Integer, String, Text, Boolean
from app.database import Base


class CustomRole(Base):
    __tablename__ = "custom_roles"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)
    label = Column(String, default="")
    permissions_json = Column(Text, default="[]")
    is_active = Column(Boolean, default=True)
    description = Column(Text, default="")


class RoleMatrixOverride(Base):
    """Surcharge de la matrice pour les rôles système (admin, manager, …)."""
    __tablename__ = "role_matrix_overrides"
    id = Column(Integer, primary_key=True)
    role_code = Column(String, unique=True, index=True)
    matrix_json = Column(Text, default="{}")
    updated_at = Column(String, default="")
