"""Gestion centralisée des erreurs API — messages lisibles en français."""
import re

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

# Libellé humain par table — utilisé pour que le message d'erreur de contrainte
# FOREIGN KEY désigne le bon élément (l'ancien message accusait toujours « le client »,
# même quand l'élément réellement bloqué était un article de stock, un fournisseur...).
_ENTITY_LABELS = {
    "clients": "ce client",
    "suppliers": "ce fournisseur",
    "stock_items": "cet article de stock",
    "warehouses": "cet entrepôt",
    "stock_categories": "cette catégorie de stock",
    "invoices": "cette facture",
    "quotes": "ce devis",
    "projects": "ce projet",
    "employees": "cet employé",
    "deals": "cette opportunité",
    "accounts": "ce compte comptable",
    "trainings": "cette formation",
    "sales_contracts": "ce contrat",
    "journal_entries": "cette écriture",
    "purchase_orders": "cette commande fournisseur",
    "purchase_requests": "cette demande d'achat",
    "supplier_invoices": "cette facture fournisseur",
}


def _failing_table(exc: IntegrityError) -> tuple[str | None, str | None]:
    """Extrait (verbe, table) de la requête SQL en échec (best-effort, pour message d'erreur)."""
    stmt = str(getattr(exc, "statement", "") or "")
    m = re.search(r'\b(DELETE FROM|INSERT INTO|UPDATE)\s+"?(\w+)"?', stmt, re.IGNORECASE)
    if not m:
        return None, None
    return m.group(1).upper(), m.group(2).lower()

_FIELD_LABELS = {
    "number": "Numéro",
    "client_id": "Client",
    "supplier_id": "Fournisseur",
    "date": "Date",
    "due_date": "Échéance",
    "amount": "Montant",
    "paid": "Montant payé",
    "unit_price": "Prix unitaire",
    "quantity": "Quantité",
    "vat_rate": "TVA",
    "description": "Description",
    "email": "Email",
    "phone": "Téléphone",
    "name": "Nom",
    "status": "Statut",
}


def _fr_msg(err: dict) -> str:
    raw = err.get("msg", "Valeur invalide")
    if raw.startswith("Value error, "):
        return raw[13:]
    if raw == "Input should be a valid integer":
        return "Nombre entier attendu"
    if raw == "Input should be a valid number":
        return "Nombre invalide"
    return raw


def _format_validation_errors(exc: RequestValidationError) -> tuple[str, list[dict]]:
    parts = []
    fields = []
    for err in exc.errors():
        loc = [str(x) for x in err.get("loc", []) if x != "body"]
        field = loc[-1] if loc else ""
        label = _FIELD_LABELS.get(field, field.replace("_", " ").title() if field else "Formulaire")
        msg = _fr_msg(err)
        parts.append(f"{label} : {msg}" if label else msg)
        if field:
            fields.append({"field": field, "message": msg, "label": label})
    detail = "; ".join(parts) if parts else "Données invalides"
    return detail, fields


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    detail, fields = _format_validation_errors(exc)
    return JSONResponse(
        status_code=422,
        content={"detail": detail, "fields": fields, "errors": exc.errors()},
    )


async def integrity_exception_handler(request: Request, exc: IntegrityError):
    msg = str(exc.orig) if exc.orig else str(exc)
    if "UNIQUE" in msg.upper():
        return JSONResponse(status_code=409, content={"detail": "Cet enregistrement existe déjà (doublon)."})
    if "FOREIGN KEY" in msg.upper():
        verb, table = _failing_table(exc)
        subject = _ENTITY_LABELS.get(table, "cet élément")
        if verb == "DELETE FROM":
            detail = (
                f"Suppression impossible : {subject} est encore utilisé ailleurs dans l'ERP "
                "(documents ou mouvements liés). Supprimez ou détachez d'abord les éléments liés"
                + (" — ou utilisez « Archiver » si l'option est proposée." if table == "clients" else ".")
            )
        else:
            detail = f"Enregistrement impossible : {subject} référencé n'existe pas ou plus."
        return JSONResponse(status_code=400, content={"detail": detail})
    return JSONResponse(status_code=400, content={"detail": "Erreur base de données : contrainte non respectée."})


async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erreur serveur : {type(exc).__name__}"},
    )
