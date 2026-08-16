"""Configuration régionale — Peya Company Togo."""

REGION = {
    "country": "Togo",
    "country_code": "TG",
    "city": "Lomé",
    "city_secondary": "Kara",
    "timezone": "Africa/Lome",
    "currency_iso": "XOF",
    "currency_label": "FCFA",
    "currency_symbol": "FCFA",
    "legal_form": "SARL",
    "company_name": "Peya Company",
    "tagline": "Votre entreprise au Togo, pilotée en un seul endroit",
    "description": (
        "ERP Peya Company pour le Togo : clients, pipeline commercial, devis et factures, "
        "projets, stock, formation et comptabilité — données sécurisées, conformes au Franc CFA (XOF)."
    ),
    "address_default": "Lomé, Togo",
    "phone_prefix": "+228",
    # Objectif chiffre d'affaires année 1 (devise de référence XOF / FCFA)
    "year1_ca_target_xof": 100_000_000,
    "warehouses": [
        ("DEP-LOM", "Dépôt Lomé", "dépôt", "Lomé"),
        ("ENT-KAR", "Entrepôt Kara", "entrepôt", "Kara"),
        ("MAG-LOM", "Magasin Lomé", "magasin", "Lomé"),
    ],
}
