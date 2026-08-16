"""Typologie articles SYSCOHADA — mapping comptes par type produit."""

from __future__ import annotations

# Types obligatoires pilotant les comptes comptables
PRODUCT_ACCOUNTING_TYPES = (
    "ASSET",
    "MERCHANDISE",
    "RAW_MATERIAL",
    "SUPPLY",
    "NON_STOCK_SUPPLY",
    "SERVICE",
    "TRANSPORT",
    "CONSIGNMENT",
)

# Comptes par type — codification SYSCOHADA révisé (PME)
TYPE_ACCOUNTS: dict[str, dict[str, str | None]] = {
    "ASSET": {
        "purchase": "244200",
        "sale": "820000",
        "stock": None,
        "stock_class": None,
        "variation": None,
        "vat_collected": "443200",
        "vat_deductible": "445100",
        "accessory": "202200",
        "supplier": "481200",
    },
    "MERCHANDISE": {
        "purchase": "601100",
        "sale": "701100",
        "stock": "311100",
        "stock_class": "31",
        "variation": "603100",
        "vat_collected": "443100",
        "vat_deductible": "445200",
        "accessory": "601500",
        "supplier": "401100",
    },
    "RAW_MATERIAL": {
        "purchase": "602100",
        "sale": "702100",
        "stock": "321100",
        "stock_class": "32",
        "variation": "603200",
        "vat_collected": "443100",
        "vat_deductible": "445200",
        "accessory": "602500",
        "supplier": "401100",
    },
    "SUPPLY": {
        "purchase": "604700",
        "sale": "704100",
        "stock": "334100",
        "stock_class": "33",
        "variation": "603300",
        "vat_collected": "443200",
        "vat_deductible": "445400",
        "accessory": "604500",
        "supplier": "401100",
    },
    "NON_STOCK_SUPPLY": {
        "purchase": "605800",
        "sale": "707100",
        "stock": None,
        "stock_class": None,
        "variation": None,
        "vat_collected": "443200",
        "vat_deductible": "445400",
        "accessory": "608500",
        "supplier": "401100",
    },
    "SERVICE": {
        "purchase": "622100",
        "sale": "706100",
        "stock": None,
        "stock_class": None,
        "variation": None,
        "vat_collected": "443200",
        "vat_deductible": "445400",
        "accessory": "622400",
        "supplier": "401100",
    },
    "TRANSPORT": {
        "purchase": "611100",
        "sale": "711100",
        "stock": None,
        "stock_class": None,
        "variation": None,
        "vat_collected": "443200",
        "vat_deductible": "445300",
        "accessory": "601500",
        "supplier": "401100",
    },
    "CONSIGNMENT": {
        "purchase": "409400",
        "sale": "707400",
        "stock": "335300",
        "stock_class": "33",
        "variation": None,
        "vat_collected": "443100",
        "vat_deductible": "445200",
        "accessory": "622400",
        "supplier": "401100",
        "client_credit": "419400",
    },
}

# Frais accessoires sur achats (6015, 6025, 6045, 6085)
ACCESSORY_FEE_TYPES = {
    "TRANSPORT": {"label": "Transport", "accounts": {"MERCHANDISE": "601500", "RAW_MATERIAL": "602500", "SUPPLY": "604500", "NON_STOCK_SUPPLY": "608500"}},
    "CUSTOMS": {"label": "Douane", "accounts": {"MERCHANDISE": "601500", "RAW_MATERIAL": "602500", "SUPPLY": "604500"}},
    "INSURANCE": {"label": "Assurance", "accounts": {"MERCHANDISE": "601500", "RAW_MATERIAL": "602500", "SUPPLY": "604500"}},
    "TRANSIT": {"label": "Transit", "accounts": {"MERCHANDISE": "601500", "RAW_MATERIAL": "602500", "SUPPLY": "604500"}},
    "HANDLING": {"label": "Manutention", "accounts": {"MERCHANDISE": "601500", "RAW_MATERIAL": "602500", "SUPPLY": "604500"}},
}

# Types d'avoirs SYSCOHADA
CREDIT_NOTE_TYPES = {
    "RETURN": {"label": "Retour marchandise", "accounts_debit": "701100", "reverse_stock": True},
    "RABAIS": {"label": "Rabais", "accounts_debit": "709100", "reverse_stock": False},
    "REMISE": {"label": "Remise", "accounts_debit": "709200", "reverse_stock": False},
    "RISTOURNE": {"label": "Ristourne", "accounts_debit": "709300", "reverse_stock": False},
    "ESCOMPTE": {"label": "Escompte", "accounts_debit": "673000", "reverse_stock": False},
}

# Catégories stock OHADA (classe 3)
STOCK_CATEGORIES_OHADA = [
    {"code": "31", "label": "Marchandises", "account": "311100", "product_type": "MERCHANDISE"},
    {"code": "32", "label": "Matières premières et fournitures liées", "account": "321100", "product_type": "RAW_MATERIAL"},
    {"code": "33", "label": "Autres approvisionnements", "account": "334100", "product_type": "SUPPLY"},
    {"code": "34", "label": "Produits en cours", "account": "341100", "product_type": "RAW_MATERIAL"},
    {"code": "36", "label": "Produits finis", "account": "361100", "product_type": "MERCHANDISE"},
    {"code": "37", "label": "Produits intermédiaires et résiduels", "account": "371100", "product_type": "RAW_MATERIAL"},
]


def accounts_for_type(product_type: str, overrides: dict | None = None) -> dict[str, str | None]:
    base = dict(TYPE_ACCOUNTS.get(product_type, TYPE_ACCOUNTS["SERVICE"]))
    if overrides:
        for k, v in overrides.items():
            if v:
                base[k] = v
    return base


def resolve_line_accounts(
    product_type: str,
    *,
    purchase_account: str = "",
    sale_account: str = "",
    stock_account: str = "",
    vat_account: str = "",
) -> dict[str, str | None]:
    acc = accounts_for_type(product_type)
    if purchase_account:
        acc["purchase"] = purchase_account
    if sale_account:
        acc["sale"] = sale_account
    if stock_account:
        acc["stock"] = stock_account
    if vat_account:
        acc["vat_deductible"] = vat_account
        acc["vat_collected"] = vat_account
    return acc
