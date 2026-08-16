"""Stock avancé — entrepôts, niveaux, mouvements enrichis."""
from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey, Text
from app.database import Base


class Warehouse(Base):
    __tablename__ = "warehouses"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, default="entrepôt")  # dépôt, entrepôt, magasin, point_de_vente
    city = Column(String, default="")
    is_active = Column(Boolean, default=True)


class StockInventory(Base):
    """Session d'inventaire (tournant, annuel, par magasin)."""
    __tablename__ = "stock_inventories"
    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String, default="")
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    type = Column(String, default="tournant")  # tournant, annuel, categorie
    status = Column(String, default="brouillon")  # brouillon, en_cours, validé
    started_at = Column(String, default="")
    completed_at = Column(String, default="")
    notes = Column(Text, default="")
