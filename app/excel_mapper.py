"""Mapping flexible colonnes Excel (FR/EN) → champs métier."""
import re
import unicodedata

import pandas as pd


def _norm(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


COLUMN_ALIASES = {
    "name": [
        "name", "nom", "noms_et_prenoms", "noms_prenoms", "nom_prenom", "prenom", "prenoms",
        "raison_sociale", "denomination", "societe", "entreprise", "beneficiaire", "client",
        "fullname", "full_name", "libelle", "intitule",
    ],
    "client_name": ["client_name", "nom_client", "client", "customer", "acheteur", "donneur_ordre"],
    "title": ["title", "titre", "objet", "sujet", "opportunite", "affaire"],
    "type": ["type", "categorie", "category"],
    "segment": ["segment", "secteur"],
    "contact": ["contact", "interlocuteur"],
    "email": ["email", "mail", "e_mail", "courriel"],
    "phone": ["phone", "telephone", "tel", "mobile"],
    "city": ["city", "ville", "localite"],
    "status": ["status", "statut", "etat"],
    "stage": ["stage", "etape", "phase", "pipeline", "statut_deal"],
    "notes": ["notes", "commentaire", "commentaires", "remarques"],
    "number": ["number", "numero", "num", "n_facture", "n_devis", "no", "n0", "facture", "devis", "invoice", "quote", "ref_doc"],
    "client_id": ["client_id", "id_client", "client", "code_client"],
    "date": ["date", "jour", "date_operation", "date_facture", "date_devis"],
    "close_date": ["close_date", "date_cloture", "echeance_commerciale", "closing"],
    "due_date": ["due_date", "echeance", "date_echeance"],
    "valid_until": ["valid_until", "validite", "date_validite", "date_expiration", "expiration", "valable_jusqu_au"],
    "amount": ["amount", "montant", "total", "ht", "ttc", "valeur", "prix", "ca", "montant_ht", "montant_ttc", "montant_echeance"],
    "vat_rate": ["vat_rate", "tva", "taux_tva", "vat", "taux_tva_pct", "pct_tva"],
    "commission_pct": ["commission_pct", "commission", "taux_commission", "comm", "pct_commission"],
    "discount_pct": ["discount_pct", "remise", "discount", "taux_remise", "pct_remise"],
    "doc_type": ["doc_type", "type_document", "type_doc", "nature_document"],
    "probability": ["probability", "probabilite", "prob", "chance"],
    "paid": ["paid", "paye", "encaisse", "regle"],
    "label": ["label", "libelle", "designation", "description"],
    "commande": ["commande", "achat", "vente"],
    "remboursement": ["remboursement", "remb", "paiement", "reglement"],
    "solde": ["solde", "balance", "restant"],
    "pole": ["pole", "activite", "domaine"],
    "progress": ["progress", "avancement", "pourcentage"],
    "budget": ["budget", "montant_prevu"],
    "billed": ["billed", "facture", "facture_montant"],
    "start_date": ["start_date", "debut", "date_debut"],
    "end_date": ["end_date", "fin", "date_fin"],
    "description": ["description", "detail", "details"],
    "category": ["category", "categorie", "rubrique"],
    "type_tx": ["type", "type_ecriture"],
    "account_code": ["account_code", "compte", "code_compte", "numero_compte", "n_compte", "account", "cpt"],
    "debit": ["debit", "débit", "montant_debit", "mt_debit", "mvt_debit", "debit_amount"],
    "credit": ["credit", "crédit", "montant_credit", "mt_credit", "mvt_credit", "credit_amount"],
    "journal": ["journal", "code_journal", "jl", "type_journal"],
    "payment_method": ["payment_method", "mode_paiement", "paiement"],
    "reference": ["reference", "ref", "piece", "numero_piece", "n_piece", "piece_comptable"],
    "observation": ["observation", "observations", "obs", "commentaire", "notes"],
    "matricule": ["matricule", "mat", "code_employe", "id_employe", "employee_code", "ref"],
    "firstname": ["firstname", "first_name", "prenom", "prenoms"],
    "lastname": ["lastname", "last_name", "nom", "nom_famille", "nom_employe"],
    "department": ["department", "departement", "service", "dept", "direction"],
    "position": ["position", "poste", "fonction", "job", "intitule_poste"],
    "salary_base": ["salary_base", "salaire", "salaire_base", "base", "remuneration", "salaire_mensuel", "brut"],
    "hire_date": ["hire_date", "date_embauche", "embauche", "date_entree", "entree"],
    "credit_limit": ["credit_limit", "limite_credit", "plafond_credit", "encours_max"],
    "payment_terms": ["payment_terms", "conditions_paiement", "delai_paiement", "jours_paiement", "delai_reglement"],
    "withholding_pct": ["withholding_pct", "retenue_source", "taux_retenue", "irpp_retenue"],
    "frequency": ["frequency", "frequence"],
    "next_date": ["next_date", "prochaine_echeance", "date_prochaine_echeance"],
    "recurring_id": ["recurring_id", "id", "id_plan"],
}


def _first_usable_column(columns: list) -> str | None:
    for col in columns:
        text = str(col).strip()
        if text and not text.startswith("Unnamed"):
            return text
    return str(columns[0]) if columns else None


def ensure_import_mapping(columns: list, col_map: dict, sheet_type: str) -> dict:
    """Complète le mapping si l'analyse automatique n'a pas tout reconnu (import souple)."""
    out = {str(k): str(v) for k, v in (col_map or {}).items() if v}
    mapped = set(out.values())
    first = _first_usable_column(columns)

    def assign_field(field: str, col: str | None) -> None:
        if col and field not in mapped:
            out[col] = field
            mapped.add(field)

    if sheet_type == "clients" and "name" not in mapped:
        for col in columns:
            n = _norm(str(col))
            if any(x in n for x in ("client", "nom", "name", "prenom", "beneficiaire", "raison")):
                assign_field("name", str(col))
                break
        if "name" not in mapped and first:
            assign_field("name", first)
    elif sheet_type in ("invoices", "quotes") and "number" not in mapped:
        for col in columns:
            n = _norm(str(col))
            if any(x in n for x in ("num", "fact", "devis", "ref", "n_")):
                assign_field("number", str(col))
                break
        if "number" not in mapped and first:
            assign_field("number", first)
        if "client_name" not in mapped and "client_id" not in mapped:
            for col in columns:
                n = _norm(str(col))
                if any(x in n for x in ("client", "nom_client", "customer", "acheteur", "beneficiaire")):
                    assign_field("client_name", str(col))
                    break
        if "amount" not in mapped:
            for col in columns:
                n = _norm(str(col))
                if any(x in n for x in ("montant", "total", "ttc", "ht", "amount", "ca")):
                    assign_field("amount", str(col))
                    break
        if "date" not in mapped:
            for col in columns:
                n = _norm(str(col))
                if n in ("date", "date_facture", "date_devis", "jour"):
                    assign_field("date", str(col))
                    break
        if sheet_type == "quotes" and "valid_until" not in mapped:
            for col in columns:
                n = _norm(str(col))
                if any(x in n for x in ("validite", "expiration", "valid_until")):
                    assign_field("valid_until", str(col))
                    break
    elif sheet_type == "projects" and "name" not in mapped and first:
        assign_field("name", first)
    elif sheet_type == "transactions":
        for col in columns:
            n = _norm(str(col))
            if n in ("type", "category", "categorie", "account_type", "transaction_type"):
                assign_field("label", str(col))
                break
        for col in columns:
            n = _norm(str(col))
            if n in ("amount", "montant", "total", "value", "valeur", "balance"):
                assign_field("amount", str(col))
                break
        if "date" not in mapped:
            for col in columns:
                if _norm(str(col)) in ("date", "dates", "jour"):
                    assign_field("date", str(col))
                    break
        if "label" not in mapped and first:
            assign_field("label", first)
    elif sheet_type == "deals" and "title" not in mapped and "name" not in mapped:
        for col in columns:
            n = _norm(str(col))
            if any(x in n for x in ("titre", "objet", "deal", "affaire")):
                assign_field("title", str(col))
                break
        if "title" not in mapped and "name" not in mapped and first:
            assign_field("title", first)
    elif sheet_type == "employees":
        for col in columns:
            n = _norm(str(col))
            if n in ("matricule", "mat", "code", "ref", "id_employe"):
                assign_field("matricule", str(col))
                break
        if "matricule" not in mapped and first:
            assign_field("matricule", first)
        for col in columns:
            n = _norm(str(col))
            if n in ("nom", "lastname", "name"):
                assign_field("lastname", str(col))
                break
        for col in columns:
            n = _norm(str(col))
            if n in ("prenom", "firstname"):
                assign_field("firstname", str(col))
                break
        for col in columns:
            n = _norm(str(col))
            if n in ("salaire", "salary", "salaire_base", "remuneration", "brut"):
                assign_field("salary_base", str(col))
                break
    return out


def map_columns(raw_columns: list) -> dict[str, str]:
    """Retourne {colonne_excel: champ_cible} pour colonnes reconnues."""
    result = {}
    for col in raw_columns:
        n = _norm(col)
        if not n:
            continue
        for field, aliases in COLUMN_ALIASES.items():
            if n in aliases or n == field:
                result[str(col)] = field
                break
    return result


def _normalize_client_name(name: str) -> str:
    s = _norm(name or "")
    return re.sub(r"_+", "_", s).strip("_")


def resolve_client_id(db, row, col_map: dict):
    """Résout client_id depuis ID ou nom (exact, ilike, puis normalisation anti-doublon)."""
    from app.models import Client

    raw_id = row_get(row, col_map, "client_id")
    if raw_id is not None and not (hasattr(raw_id, "__float__") and pd.isna(raw_id)):
        try:
            cid = int(float(raw_id))
            # Un ID figé dans un export peut être périmé si le client a été supprimé depuis —
            # on vérifie qu'il existe encore avant de le faire confiance aveuglément, sinon
            # on laisse la résolution par nom (ci-dessous) prendre le relais.
            if cid > 0 and db.query(Client.id).filter(Client.id == cid).first():
                return cid
        except (TypeError, ValueError):
            pass
    for field in ("client_name", "name"):
        label = row_get(row, col_map, field)
        if label is None or (hasattr(label, "__float__") and pd.isna(label)):
            continue
        name = str(label).strip()
        if not name or name.lower() in ("nan", "none", "—", "-"):
            continue
        client = db.query(Client).filter(Client.name == name).first()
        if not client:
            client = db.query(Client).filter(Client.name.ilike(name)).first()
        if client:
            return client.id
        # Anti-doublon flou : SOCIETE ABC / Société Abc / Societe ABC
        target = _normalize_client_name(name)
        if target:
            for c in db.query(Client).limit(2000).all():
                if _normalize_client_name(c.name or "") == target:
                    return c.id
    return None


def _excel_pct(value, default=0.0) -> float:
    from app.excel_utils import _excel_float

    v = _excel_float(value, default)
    if v and 0 < abs(v) <= 1:
        return round(v * 100, 4)
    return v


def _normalize_invoice_status(raw) -> str:
    from app.excel_utils import _excel_str

    s = _excel_str(raw, "brouillon").lower().replace("_", " ").strip()
    aliases = {
        "draft": "brouillon",
        "brouillon": "brouillon",
        "sent": "envoyée",
        "envoyee": "envoyée",
        "envoyée": "envoyée",
        "emise": "envoyée",
        "émise": "envoyée",
        "paid": "payée",
        "payee": "payée",
        "payée": "payée",
        "reglee": "payée",
        "réglée": "payée",
        "regle": "payée",
        "overdue": "en retard",
        "retard": "en retard",
        "en retard": "en retard",
        "cancelled": "annulée",
        "annulee": "annulée",
        "annulée": "annulée",
        "cancel": "annulée",
    }
    return aliases.get(s, s if s else "brouillon")


def resolve_or_create_client_id(db, row, col_map: dict, *, dry_run: bool = False, company_id: int | None = None):
    """Résout le client ou le crée automatiquement si le nom est présent."""
    from app.models import Client

    cid = resolve_client_id(db, row, col_map)
    if cid:
        return cid, None
    label = row_get(row, col_map, "client_name")
    if label is None or (hasattr(label, "__float__") and pd.isna(label)):
        return None, "Client manquant — associez une colonne « Nom client »"
    name = str(label).strip()
    if not name or name.lower() in ("nan", "none", "—", "-"):
        return None, "Client manquant — nom vide"
    if dry_run:
        return 0, None
    client = Client(name=name, type="Entreprise", status="client")
    if company_id is not None and hasattr(client, "company_id"):
        client.company_id = company_id
    db.add(client)
    db.flush()
    return client.id, None


def build_invoice_import_fields(db, row, col_map: dict, *, dry_run: bool = False, company_id: int | None = None):
    """Construit les champs facture depuis une ligne Excel."""
    from app.excel_utils import _excel_date, _excel_float, _excel_str

    num = row_get(row, col_map, "number")
    if num is None or (hasattr(num, "__float__") and pd.isna(num)) or not str(num).strip():
        return None, "Numéro de facture manquant"
    cid, err = resolve_or_create_client_id(db, row, col_map, dry_run=dry_run, company_id=company_id)
    if err:
        return None, err
    amount_raw = row_get(row, col_map, "amount")
    amount = _excel_float(amount_raw) if amount_raw is not None and not (
        hasattr(amount_raw, "__float__") and pd.isna(amount_raw)
    ) else 0.0
    paid_raw = row_get(row, col_map, "paid")
    paid = _excel_float(paid_raw) if paid_raw is not None and not (
        hasattr(paid_raw, "__float__") and pd.isna(paid_raw)
    ) else 0.0
    fields = {
        "number": _excel_str(num),
        "client_id": cid,
        "date": _excel_date(row_get(row, col_map, "date")),
        "due_date": _excel_date(row_get(row, col_map, "due_date")),
        "amount": amount,
        "paid": paid,
        "status": _normalize_invoice_status(row_get(row, col_map, "status")),
        "vat_rate": _excel_pct(row_get(row, col_map, "vat_rate")),
        "commission_pct": _excel_pct(row_get(row, col_map, "commission_pct")),
        "discount_pct": _excel_pct(row_get(row, col_map, "discount_pct")),
        "description": _excel_str(row_get(row, col_map, "description")),
        "notes": _excel_str(row_get(row, col_map, "notes")),
        "doc_type": _excel_str(row_get(row, col_map, "doc_type"), "invoice") or "invoice",
    }
    return fields, None


def _normalize_quote_status(raw) -> str:
    from app.excel_utils import _excel_str

    s = _excel_str(raw, "brouillon").lower().replace("_", " ").strip()
    aliases = {
        "draft": "brouillon", "brouillon": "brouillon",
        "sent": "envoyé", "envoye": "envoyé", "envoyé": "envoyé",
        "accepted": "accepté", "accepte": "accepté", "accepté": "accepté", "valide": "accepté", "validé": "accepté",
        "refused": "refusé", "refuse": "refusé", "refusé": "refusé", "rejete": "refusé", "rejeté": "refusé",
        "expired": "expiré", "expire": "expiré", "expiré": "expiré",
    }
    return aliases.get(s, s if s in ("brouillon", "envoyé", "accepté", "refusé", "expiré") else "brouillon")


def build_quote_import_fields(db, row, col_map: dict, *, dry_run: bool = False, company_id: int | None = None):
    """Construit les champs devis depuis une ligne Excel (même logique que les factures)."""
    from app.excel_utils import _excel_date, _excel_float, _excel_str

    num = row_get(row, col_map, "number")
    if num is None or (hasattr(num, "__float__") and pd.isna(num)) or not str(num).strip():
        return None, "Numéro de devis manquant"
    cid, err = resolve_or_create_client_id(db, row, col_map, dry_run=dry_run, company_id=company_id)
    if err:
        return None, err
    amount_raw = row_get(row, col_map, "amount")
    amount = _excel_float(amount_raw) if amount_raw is not None and not (
        hasattr(amount_raw, "__float__") and pd.isna(amount_raw)
    ) else 0.0
    title = row_get(row, col_map, "title") or row_get(row, col_map, "description")
    fields = {
        "number": _excel_str(num),
        "client_id": cid,
        "title": _excel_str(title),
        "date": _excel_date(row_get(row, col_map, "date")),
        "valid_until": _excel_date(row_get(row, col_map, "valid_until")),
        "amount": amount,
        "vat_rate": _excel_pct(row_get(row, col_map, "vat_rate")),
        "status": _normalize_quote_status(row_get(row, col_map, "status")),
        "notes": _excel_str(row_get(row, col_map, "notes")),
    }
    return fields, None


def compose_transaction_label(row, col_map: dict) -> str:
    """Libellé d'écriture si aucune colonne « label » (exports journal comptable)."""
    label = row_get(row, col_map, "label")
    if label is not None and not (hasattr(label, "__float__") and pd.isna(label)):
        text = str(label).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    parts: list[str] = []
    for field in ("type_tx", "type", "reference", "account_code", "category"):
        val = row_get(row, col_map, field)
        if val is None or (hasattr(val, "__float__") and pd.isna(val)):
            continue
        text = str(val).strip()
        if text and text.lower() not in ("nan", "none"):
            parts.append(text)
    return " · ".join(parts[:4]) if parts else "Écriture importée"


def row_get(row, col_map: dict, field: str, default=None):
    """Lit une valeur depuis une ligne (pandas Series ou dict grille éditée)."""
    if isinstance(row, dict):
        for excel_col, target in col_map.items():
            if target == field and excel_col in row:
                return row[excel_col]
        for col, val in row.items():
            if _norm(str(col)) == field or _norm(str(col)) in COLUMN_ALIASES.get(field, []):
                return val
        return default
    for excel_col, target in col_map.items():
        if target == field and excel_col in row.index:
            return row[excel_col]
    for col in row.index:
        if _norm(col) == field or _norm(col) in COLUMN_ALIASES.get(field, []):
            return row[col]
    return default
