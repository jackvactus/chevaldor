"""Modèles SYSCOHADA — classes de comptes, immobilisations, amortissements."""
from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey, Text
from app.database import Base


class AccountClass(Base):
    """Classes 1 à 8 du plan SYSCOHADA."""
    __tablename__ = "account_classes"
    code = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    kind = Column(String, default="bilan")  # bilan | gestion
    description = Column(Text, default="")


class AssetCategory(Base):
    """Catégories d'immobilisations — durées et méthodes d'amortissement."""
    __tablename__ = "asset_categories"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    account_asset = Column(String, default="244200")  # compte immobilisation
    account_depreciation = Column(String, default="284400")  # amort. cumulé
    account_charge = Column(String, default="681300")  # dotation
    method = Column(String, default="lineaire")  # lineaire | degressif | unites
    duration_months = Column(Integer, default=36)
    rate_pct = Column(Float, default=0)
    is_active = Column(Boolean, default=True)


class FixedAsset(Base):
    """Immobilisation — acquisition, mise en service, cession."""
    __tablename__ = "fixed_assets"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    label = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("asset_categories.id"), nullable=True)
    acquisition_date = Column(Date)
    service_date = Column(Date)
    acquisition_cost = Column(Float, default=0)
    residual_value = Column(Float, default=0)
    account_code = Column(String, default="244200")
    status = Column(String, default="en_service")  # brouillon, en_service, cede, deprecie
    disposal_date = Column(Date, nullable=True)
    disposal_amount = Column(Float, default=0)
    notes = Column(Text, default="")


class DepreciationEntry(Base):
    """Écriture d'amortissement périodique."""
    __tablename__ = "depreciation_entries"
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("fixed_assets.id"), index=True)
    period_date = Column(Date)
    fiscal_year = Column(Integer)
    period = Column(Integer)  # mois 1-12
    amount = Column(Float, default=0)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    status = Column(String, default="brouillon")  # brouillon, validée


class AssetDisposal(Base):
    """Cession ou mise au rebut d'une immobilisation."""
    __tablename__ = "asset_disposals"
    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("fixed_assets.id"), index=True)
    date = Column(Date)
    proceeds = Column(Float, default=0)
    book_value = Column(Float, default=0)
    gain_loss = Column(Float, default=0)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    notes = Column(Text, default="")
