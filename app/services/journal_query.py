"""Filtres d'affichage du journal comptable."""
from __future__ import annotations

from sqlalchemy.orm import Query
from sqlalchemy import or_

from app.models_erp import JournalEntry

# Bruit comptable auto (stock IN, achats fournisseur AC) — hors vue « commercial ».
JOURNAL_DISPLAY_EXCLUDED_SOURCES = frozenset({"stock_movement", "supplier_invoice"})


def apply_journal_display_scope(query: Query, scope: str = "commercial") -> Query:
    """commercial = saisies manuelles + factures clients ; all = tout le journal."""
    if scope == "all":
        return query
    st = JournalEntry.source_type
    return query.filter(
        or_(
            st.is_(None),
            st == "",
            ~st.in_(JOURNAL_DISPLAY_EXCLUDED_SOURCES),
        )
    )
