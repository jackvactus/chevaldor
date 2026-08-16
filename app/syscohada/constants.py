"""Constantes SYSCOHADA révisé — classes, journaux, TVA, comptes par défaut (Togo / UEMOA)."""

# Classes 1 à 8 — comptabilité générale (classe 9 = analytique / engagements, facultative)
ACCOUNT_CLASSES = [
    {
        "code": "1",
        "label": "Ressources stables",
        "kind": "bilan",
        "description": "Capitaux propres, emprunts et dettes financières",
    },
    {
        "code": "2",
        "label": "Immobilisations",
        "kind": "bilan",
        "description": "Actif immobilisé — incorporel, corporel, financier",
    },
    {
        "code": "3",
        "label": "Stocks",
        "kind": "bilan",
        "description": "Marchandises, matières, produits en cours et finis",
    },
    {
        "code": "4",
        "label": "Tiers",
        "kind": "bilan",
        "description": "Clients, fournisseurs, État, personnel, associés",
    },
    {
        "code": "5",
        "label": "Trésorerie",
        "kind": "bilan",
        "description": "Banques, caisse, chèques, effets, monnaie électronique",
    },
    {
        "code": "6",
        "label": "Charges",
        "kind": "gestion",
        "description": "Charges des activités ordinaires (exploitation et financières)",
    },
    {
        "code": "7",
        "label": "Produits",
        "kind": "gestion",
        "description": "Produits des activités ordinaires (exploitation et financiers)",
    },
    {
        "code": "8",
        "label": "Hors activité ordinaire",
        "kind": "gestion",
        "description": "Charges et produits HAO, cessions, subventions d'équilibre",
    },
    {
        "code": "9",
        "label": "Comptabilité analytique & engagements",
        "kind": "analytique",
        "description": "Centres de coûts, sections, engagements hors bilan (facultatif)",
    },
]

# Journaux SYSCOHADA — codification Peya Company
JOURNALS = [
    {"code": "AN", "label": "À-nouveaux", "description": "Report à nouveau, ouverture d'exercice"},
    {"code": "VE", "label": "Ventes", "description": "Factures clients, avoirs, encaissements liés"},
    {"code": "AC", "label": "Achats", "description": "Factures fournisseurs, avoirs, décaissements liés"},
    {"code": "BQ", "label": "Banque", "description": "Mouvements bancaires, virements, cartes"},
    {"code": "CA", "label": "Caisse", "description": "Espèces, mobile money (Flooz, Mixx, FedaPay)"},
    {"code": "OD", "label": "Opérations diverses", "description": "Régularisations, provisions, clôture"},
    {"code": "IN", "label": "Inventaire", "description": "Stocks — entrées, sorties, ajustements (inventaire permanent)"},
    {"code": "IM", "label": "Immobilisations", "description": "Acquisitions, amortissements, cessions"},
]

# TVA Togo (taux en vigueur zone UEMOA — configurable en paramètres)
TOGO_VAT_RATES = [
    {"code": "TVA0", "name": "TVA 0 %", "rate": 0.0, "default": True, "account_collected": "443100", "account_deductible": "445200"},
    {"code": "TVA18", "name": "TVA 18 %", "rate": 18.0, "account_collected": "443100", "account_deductible": "445200"},
    {"code": "EXO", "name": "Exonérée", "rate": 0.0, "account_collected": "443100", "account_deductible": "445200"},
]

# Comptes par défaut — subdivision PME (4 chiffres max SYSCOHADA)
DEFAULT_ACCOUNTS = {
    "sales_goods": "701100",
    "sales_services": "706100",
    "sales_other": "707100",
    "purchases_goods": "601100",
    "purchases_raw": "602100",
    "purchases_services": "604700",
    "stock_goods": "311100",
    "stock_variation_goods": "603100",
    "stock_variation_raw": "603200",
    "clients": "411100",
    "clients_credit": "419100",
    "suppliers": "401100",
    "suppliers_effects": "402100",
    "suppliers_assets": "404100",
    "suppliers_investment": "481200",
    "vat_collected_sales": "443100",
    "vat_collected_services": "443200",
    "vat_deductible_purchases": "445200",
    "vat_deductible_services": "445400",
    "vat_due": "444100",
    "vat_credit": "444900",
    "bank": "521100",
    "cash": "571100",
    "checks_to_deposit": "513100",
    "effects_to_collect": "512100",
    "mobile_money": "521100",
    "depreciation_charge": "681300",
    "depreciation_accumulated": "284400",
    "result_profit": "131000",
    "result_loss": "139000",
    "retained_earnings_cr": "121000",
    "retained_earnings_dr": "129000",
}

# Parallélismes charges / produits (guide SYSCOHADA)
CHARGE_PRODUCT_PAIRS = {
    "601": "701",
    "602": "702",
    "604": "704",
    "606": "706",
    "607": "707",
    "65": "75",
    "67": "77",
    "681": "781",
    "691": "791",
}
