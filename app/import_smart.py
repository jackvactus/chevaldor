"""Détection intelligente du type d'import et mapping automatique (sans contrainte utilisateur)."""
from __future__ import annotations

import re
from typing import Any, Optional

from app.excel_grid import is_junk_column
from app.excel_mapper import _norm, ensure_import_mapping


def count_junk_columns(columns: list) -> int:
    return sum(1 for c in columns if is_junk_column(str(c)))


def filter_meaningful_columns(columns: list) -> list[str]:
    """Colonnes exploitables (sans Unnamed: N vides)."""
    return [str(c) for c in columns if not is_junk_column(str(c))]


def _is_duplicate_col(name: str) -> bool:
    return bool(re.search(r"\.\d+$", str(name).strip()))


LEDGER_TYPE_COLUMNS = frozenset({
    "type", "category", "categorie", "account_type", "transaction_type", "entry_type",
})
LEDGER_AMOUNT_COLUMNS = frozenset({
    "amount", "montant", "total", "value", "valeur", "balance", "net", "gross",
})


def _clientele_wide_core(columns: list) -> bool:
    if not columns:
        return False
    norms = [_norm(str(c)) for c in columns]
    has_dates = any(n in ("date", "dates", "jour") or n == "date" for n in norms)
    has_cmd = sum(1 for n in norms if n == "commande" or n.startswith("commande_")) >= 1
    has_fin = any(n == "remboursement" or n.startswith("remboursement") or n == "solde" for n in norms)
    return has_dates and has_cmd and has_fin


def looks_like_government_ledger(columns: list) -> bool:
    """Exports type TCRG / pièces de journal (colonnes bilingues longues)."""
    meaningful = filter_meaningful_columns(columns)
    if len(meaningful) < 5:
        return False
    norms = [_norm(str(c)) for c in meaningful]
    has_eff_date = any(
        "accounting_effective_date" in n or "date_d_entree_en_vigueur" in n for n in norms
    )
    has_item_amount = any(
        "journal_voucher_item_amount" in n or ("montant" in n and "item" in n) for n in norms
    )
    has_gl = any("general_ledger_account" in n or "grand_livre" in n for n in norms)
    has_cd = any("credit_debit" in n for n in norms)
    has_voucher = any("journal_voucher" in n for n in norms)
    return bool(
        (has_eff_date and has_item_amount)
        or (has_item_amount and has_gl and (has_cd or has_voucher))
    )


def looks_like_accounting_ledger(columns: list) -> bool:
    """Journal / export comptable (date + catégorie type + montants), pas clientèle PC."""
    if looks_like_government_ledger(columns):
        return True
    meaningful = filter_meaningful_columns(columns)
    if len(meaningful) < 3 or _clientele_wide_core(meaningful):
        return False
    norms = [_norm(str(c)) for c in meaningful]
    has_date = any(
        n in ("date", "dates", "jour", "timestamp")
        or n.startswith("date_")
        or "effective_date" in n
        or ("accounting" in n and "date" in n)
        for n in norms
    )
    has_kind = any(n in LEDGER_TYPE_COLUMNS for n in norms)
    has_amount = any(
        n in LEDGER_AMOUNT_COLUMNS or "item_amount" in n or "journal_voucher_item_amount" in n
        for n in norms
    )
    numeric_heavy = len(meaningful) >= 5 and has_date and has_kind
    return has_date and (has_kind or has_amount or numeric_heavy)


# Priorité sur COLUMN_ALIASES génériques (évite Control-Number → numéro facture, Identifier → date)
GOVERNMENT_LEDGER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("date", ("accounting_effective_date", "date_d_entree_en_vigueur_comptable", "effective_date")),
    ("amount", ("journal_voucher_item_amount", "montant_de_l_item_de_la_piece")),
    ("reference", (
        "journal_voucher_identifier",
        "identificateur_de_la_piece_de_journal",
        "journal_voucher_item_identifier",
        "identificateur_de_l_item",
        "accounting_control_number",
        "numero_controle_comptable",
    )),
    ("type_tx", ("journal_voucher_type_code", "credit_debit_code", "code_credit_debit")),
    ("account_code", (
        "general_ledger_account_code",
        "compte_du_grand_livre",
        "subledger_account_identifier",
    )),
    ("label", ("journal_voucher_type_code", "code_du_type_de_piece")),
    ("category", (
        "control_data_type",
        "fiscal_year",
        "department_number",
        "fiscal_month",
        "journal_voucher_type",
    )),
    ("notes", ("gbs_control_number", "accounting_summary", "financial_coding_block")),
]


def map_government_ledger_columns(columns: list) -> dict[str, str]:
    """Mapping dédié aux colonnes bilingues (ex. tcrg-rgat.csv)."""
    out: dict[str, str] = {}
    used_targets: set[str] = set()
    for col in columns:
        if is_junk_column(str(col)) or _is_duplicate_col(col):
            continue
        n = _norm(str(col))
        if not n:
            continue
        for field, patterns in GOVERNMENT_LEDGER_RULES:
            if field in used_targets:
                continue
            if any(pat in n for pat in patterns):
                out[str(col)] = field
                used_targets.add(field)
                break
    return out


def looks_like_clientele_wide(columns: list) -> bool:
    """Tableau large Dates + Commande / Remboursement / Solde (fichiers clientèle PC)."""
    if not columns or looks_like_accounting_ledger(columns):
        return False
    return _clientele_wide_core(columns)


def infer_amount_column(columns: list, col_map: dict) -> str | None:
    """Première colonne montant explicite, sinon première colonne numérique non-id/date."""
    if "amount" in col_map.values():
        for col, field in col_map.items():
            if field == "amount":
                return str(col)
    for col in columns:
        n = _norm(str(col))
        if n in LEDGER_AMOUNT_COLUMNS:
            return str(col)
    skip = {"id", "index", "idx", "row", "date", "dates", "type", "category", "categorie"}
    for col in columns:
        n = _norm(str(col))
        if n in skip or is_junk_column(str(col)):
            continue
        if any(x in n for x in ("amount", "montant", "total", "balance", "value", "valeur")):
            return str(col)
    for col in columns:
        n = _norm(str(col))
        if n not in skip and not is_junk_column(str(col)) and n not in LEDGER_TYPE_COLUMNS:
            return str(col)
    return None


def looks_like_client_list(columns: list, col_map: dict) -> bool:
    targets = set(col_map.values())
    norms = [_norm(str(c)) for c in columns]
    has_nom = "name" in targets or any(
        n in ("nom", "name", "client", "email", "telephone", "ville") or "nom" in n for n in norms
    )
    has_clientele_only = looks_like_clientele_wide(columns) and not any(
        n in ("email", "telephone", "ville", "segment") for n in norms
    )
    return has_nom and not has_clientele_only


def looks_like_employee_list(columns: list, col_map: dict) -> bool:
    if looks_like_clientele_wide(columns) or looks_like_accounting_ledger(columns):
        return False
    targets = set(col_map.values())
    norms = [_norm(str(c)) for c in filter_meaningful_columns(columns)]
    hr_tokens = (
        "matricule", "mat", "code_employe", "prenom", "nom", "lastname", "firstname",
        "salaire", "salaire_base", "departement", "department", "poste", "position", "embauche",
    )
    hits = sum(1 for n in norms if n in hr_tokens or any(t in n for t in hr_tokens))
    has_mat = "matricule" in targets or any(n in ("matricule", "mat", "code_employe") for n in norms)
    has_name = "lastname" in targets or "firstname" in targets or any(n in ("nom", "prenom") for n in norms)
    has_pay = "salary_base" in targets or "department" in targets or any(
        n in ("salaire", "salaire_base", "departement", "poste") for n in norms
    )
    return hits >= 2 and (has_mat or has_name) and (has_pay or has_mat)


def build_smart_mapping(columns: list, sheet_type: str) -> dict[str, str]:
    """Mapping automatique : une seule colonne par champ, doublons .1 .2 ignorés."""
    from app.excel_smart import _map_columns_enhanced

    raw = _map_columns_enhanced(columns)
    if looks_like_government_ledger(columns):
        gov = map_government_ledger_columns(columns)
        for col, field in gov.items():
            raw[str(col)] = field
    out: dict[str, str] = {}
    used_targets: set[str] = set()

    for col in columns:
        if is_junk_column(str(col)) or _is_duplicate_col(col):
            continue
        target = raw.get(str(col))
        if not target or target in used_targets:
            continue
        if sheet_type == "clients" and target in ("commande", "remboursement", "solde", "date"):
            continue
        if sheet_type in ("invoices", "quotes", "recurring") and target in ("commande", "remboursement", "solde"):
            continue
        if sheet_type == "transactions" and target == "type":
            continue
        if sheet_type == "employees" and target in (
            "commande", "remboursement", "solde", "client_name", "client_id", "number", "amount",
        ):
            continue
        out[str(col)] = target
        used_targets.add(target)

    if sheet_type == "transactions":
        for col in columns:
            if is_junk_column(str(col)) or _is_duplicate_col(col):
                continue
            n = _norm(str(col))
            if n in LEDGER_TYPE_COLUMNS:
                old = [k for k, v in out.items() if v == "label"]
                for k in old:
                    del out[k]
                    used_targets.discard("label")
                out[str(col)] = "label"
                used_targets.add("label")
                break
        amt_col = infer_amount_column(columns, out)
        if amt_col and "amount" not in used_targets:
            out[amt_col] = "amount"
            used_targets.add("amount")

    return ensure_import_mapping(columns, out, sheet_type)


def columns_for_display(columns: list, mapping: dict[str, str]) -> list[str]:
    """Colonnes utiles à afficher (pas Unnamed ni doublons .1 .2)."""
    shown: list[str] = []
    for col in filter_meaningful_columns(columns):
        c = str(col)
        if _is_duplicate_col(c):
            continue
        if mapping.get(c):
            shown.append(c)
    return shown[:24]


def detect_import_profile(
    columns: list,
    *,
    matrix_available: bool = False,
    layout: str = "tabular",
    col_map: Optional[dict] = None,
) -> dict[str, Any]:
    col_map = col_map or build_smart_mapping(columns, "clients")
    junk = count_junk_columns(columns)
    profile: dict[str, Any] = {
        "matrix_available": matrix_available,
        "layout": layout,
        "clientele_wide": looks_like_clientele_wide(filter_meaningful_columns(columns)),
        "client_list": looks_like_client_list(filter_meaningful_columns(columns), col_map),
        "employee_list": looks_like_employee_list(filter_meaningful_columns(columns), col_map),
        "junk_columns_ignored": junk,
    }
    junk_note = f" · {junk} colonne(s) vide(s) ignorée(s)" if junk else ""
    meaningful = filter_meaningful_columns(columns)
    profile["government_ledger"] = looks_like_government_ledger(meaningful)
    profile["accounting_ledger"] = looks_like_accounting_ledger(meaningful)
    if profile["accounting_ledger"]:
        profile["recommended_type"] = "transactions"
        if profile.get("government_ledger"):
            profile["label"] = "Écritures comptables (export gouvernemental)"
            profile["hint"] = (
                "Export type pièces de journal détecté (date comptable, montants, comptes GL). "
                "Choisissez « Écritures comptables » — tout le fichier sera importé."
                + junk_note
            )
        else:
            profile["label"] = "Écritures comptables / journal"
            profile["hint"] = (
                "Journal détecté (date, type de mouvement, montants). "
                "Import automatique en écritures — tout le fichier sera lu."
                + junk_note
            )
    elif matrix_available or (profile["clientele_wide"] and layout != "matrix"):
        profile["recommended_type"] = "clientele_pc"
        profile["label"] = "Tableau clientèle PC"
        profile["hint"] = (
            "Import automatique depuis le fichier (matrice ou tableau large). "
            "Aucun mapping manuel requis."
            + junk_note
        )
    elif profile.get("employee_list"):
        profile["recommended_type"] = "employees"
        profile["label"] = "Registre du personnel / RH"
        profile["hint"] = (
            "Colonnes RH détectées (matricule, nom, département, salaire…). "
            "Import vers le registre des employés."
            + junk_note
        )
    elif profile["client_list"]:
        profile["recommended_type"] = "clients"
        profile["label"] = "Liste clients / contacts"
        profile["hint"] = "Colonnes reconnues automatiquement (nom, email, téléphone…)." + junk_note
    elif "number" in col_map.values() and "amount" in col_map.values():
        profile["recommended_type"] = "invoices"
        profile["label"] = "Factures"
        profile["hint"] = "Numéro et montants détectés."
    elif (
        "label" in col_map.values()
        or ("amount" in col_map.values() and "date" in col_map.values())
        or ("date" in col_map.values() and any(_norm(str(c)) in LEDGER_TYPE_COLUMNS for c in meaningful))
    ):
        profile["recommended_type"] = "transactions"
        profile["label"] = "Écritures comptables"
        profile["hint"] = "Libellé / montant / date détectés." + junk_note
    else:
        profile["recommended_type"] = "clients"
        profile["label"] = "Données générales"
        profile["hint"] = "Import souple : les colonnes reconnues seront utilisées." + junk_note
    return profile


def file_is_clientele_matrix(
    contents: bytes,
    filename: str = "",
    sheet_name: str | int | None = None,
) -> bool:
    """Détecte le format matriciel nativement dans le fichier (indépendant de la vue liste)."""
    if not contents:
        return False
    try:
        from app.excel_clientele import CLIENTELE_MAX_COLS, _trim_df, detect_clientele_format
        from app.excel_utils import load_spreadsheet

        sn = sheet_name if sheet_name not in (None, "", "CSV") else 0
        raw = load_spreadsheet(
            contents, filename=filename, sheet_name=sn, header=None, max_columns=CLIENTELE_MAX_COLS
        )
        return detect_clientele_format(_trim_df(raw))
    except Exception:
        return False


def resolve_import_strategy(
    sheet_type: str,
    columns: Optional[list],
    *,
    matrix_available: bool = False,
    contents: bytes | None = None,
    filename: str = "",
    custom_map: Optional[dict] = None,
    sheet_name: str | int | None = None,
) -> dict[str, Any]:
    """
    Prépare le mapping intelligent sans imposer de type de fichier.
    Le type choisi dans l'interface (sheet_type) est toujours respecté.
    """
    cols = columns or []
    user_type = (sheet_type or "clients").strip() or "clients"
    file_matrix = file_is_clientele_matrix(contents, filename, sheet_name) if contents else False
    if file_matrix:
        matrix_available = True

    profile = detect_import_profile(
        cols,
        matrix_available=matrix_available,
        col_map=custom_map or (build_smart_mapping(cols, user_type) if cols else {}),
    )
    recommended = profile.get("recommended_type") or "clients"

    mapping = build_smart_mapping(cols, user_type) if cols else {}
    if custom_map:
        mapping.update({str(k): str(v) for k, v in custom_map.items() if v})
        mapping = ensure_import_mapping(cols, mapping, user_type)

    hints: list[str] = []
    if profile.get("hint"):
        hints.append(profile["hint"])
    if recommended != user_type:
        hints.append(
            f"Suggestion : « {profile.get('label', recommended)} » — vous avez choisi « {user_type} »."
        )
    if profile.get("clientele_wide") and user_type != "clientele_pc":
        hints.append(
            "Ce fichier ressemble à un tableau clientèle large ; le mode matriciel reste disponible si besoin."
        )
    if profile.get("accounting_ledger") and user_type != "transactions":
        hints.append("Colonnes type journal comptable détectées.")

    use_file = user_type == "clientele_pc" and bool(contents)

    return {
        "sheet_type": user_type,
        "user_sheet_type": user_type,
        "recommended_type": recommended,
        "column_mapping": mapping,
        "profile": profile,
        "use_file_parse": use_file,
        "reason": " ".join(hints) if hints else "Import dynamique selon vos colonnes.",
        "auto": True,
    }
