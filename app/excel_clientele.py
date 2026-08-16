"""Parseur du tableau de bord clientèle PC (format Excel matriciel)."""
from __future__ import annotations

import unicodedata
from typing import Any

import pandas as pd

from app.excel_utils import load_spreadsheet


def _norm(text: Any) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    s = str(text).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _cell_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _cell_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


CLIENTELE_MAX_COLS = 320


def _trim_df(df: pd.DataFrame, max_row: int | None = None) -> pd.DataFrame:
    """Réduit le DataFrame aux lignes/colonnes utilisées (sans parcourir 10k+ colonnes vides)."""
    if df.empty:
        return df
    col_scan = min(len(df.columns), CLIENTELE_MAX_COLS)
    row_limit = min(len(df), max_row or 450)
    last_col = 0
    for r in range(min(25, len(df))):
        row = df.iloc[r, :col_scan]
        for c in range(len(row) - 1, -1, -1):
            if _cell_str(row.iloc[c]):
                last_col = max(last_col, c)
                break
    last_row = 0
    empty_streak = 0
    for r in range(row_limit):
        v0 = df.iloc[r, 0]
        has_date = _parse_date_cell(v0) is not None
        has_label = bool(_cell_str(v0))
        if has_date or (has_label and r < 25):
            last_row = r
            empty_streak = 0
        elif r > 10:
            empty_streak += 1
            if empty_streak > 30:
                break
    return df.iloc[: last_row + 1, : min(last_col + 4, len(df.columns))].copy()


def _looks_like_person_name(text: str) -> bool:
    t = _cell_str(text)
    if not t or len(t) < 2:
        return False
    if _parse_date_cell(text) is not None:
        return False
    try:
        float(str(text).replace(" ", "").replace(",", "."))
        return False
    except ValueError:
        pass
    low = t.lower()
    if low in ("commande", "remboursement", "solde", "dates", "date", "nom", "prenom"):
        return False
    return any(ch.isalpha() for ch in t)


def _row_has_client_names(row: pd.Series, min_count: int = 2) -> bool:
    found = 0
    for c in range(1, min(len(row), CLIENTELE_MAX_COLS)):
        if _looks_like_person_name(row.iloc[c]):
            found += 1
            if found >= min_count:
                return True
    return False


def _find_clientele_layout(df: pd.DataFrame) -> tuple[int, int, int] | None:
    """
    Retourne (ligne_titre, ligne_noms, ligne_sous_entêtes) ou None.
    Gère les variantes (lignes vides en tête, « new », noms en colonnes B…, etc.).
    """
    if df.empty or len(df.columns) < 4:
        return None

    title_row = None
    names_row = None
    subs_row = None

    for r in range(min(25, len(df))):
        c0 = _norm(df.iloc[r, 0])
        c1 = _norm(df.iloc[r, 1]) if len(df.columns) > 1 else ""
        if title_row is None and "tableau" in c0 and "board" in c0 and "client" in c0:
            title_row = r
        if "nom" in c0 and "prenom" in c0.replace(" ", ""):
            names_row = r
        if c0 in ("dates", "date") and c1 in ("commande", "remboursement", "solde"):
            subs_row = r
        elif c0 in ("dates", "date") and "commande" in c1:
            subs_row = r

    if subs_row is not None and names_row is None:
        for r in range(subs_row - 1, max(-1, subs_row - 5), -1):
            if _row_has_client_names(df.iloc[r]):
                names_row = r
                break
        if names_row is None and subs_row > 0:
            names_row = subs_row - 1

    if names_row is not None and subs_row is not None and subs_row > names_row:
        if title_row is None:
            title_row = max(0, names_row - 2)
        return title_row, names_row, subs_row

    if len(df) >= 5:
        t0 = _norm(df.iloc[0, 0])
        if len(df) > 3:
            s3 = _norm(df.iloc[3, 1]) if len(df.columns) > 1 else ""
            l2_names = _row_has_client_names(df.iloc[2]) if len(df) > 2 else False
            if ("tableau" in t0 and "board" in t0 and "client" in t0) or (l2_names and s3 == "commande"):
                return 0, 2, 3

    return None


def detect_clientele_format(df: pd.DataFrame) -> bool:
    """Détecte le format « Tableau de board clientèle PC »."""
    return _find_clientele_layout(df) is not None


def _parse_date_cell(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        return pd.to_datetime(raw).date().isoformat()
    except Exception:
        return None


def _find_stray_name_in_column(df: pd.DataFrame, col: int, data_start: int) -> str:
    """Cherche un nom de client égaré dans les données (en-tête vide mais nom recopié par
    erreur dans une cellule de la colonne, vu sur un fichier réel : en-tête dupliqué en plein
    milieu du tableau). Ignore les valeurs numériques et les mots-clés d'en-tête connus."""
    for row_idx in range(data_start, min(len(df), data_start + 200)):
        val = _cell_str(df.iloc[row_idx, col])
        if not val or _cell_float(val) is not None:
            continue
        if _norm(val) in ("commande", "remboursement", "solde", "dates", "date"):
            continue
        return val
    return ""


def _collect_client_blocks(
    names_row: pd.Series,
    subs_row: pd.Series,
    max_col: int,
    df: pd.DataFrame | None = None,
    data_start: int = 0,
) -> list[dict]:
    blocks: list[dict] = []
    col = 1
    while col < max_col:
        name = _cell_str(names_row.iloc[col])
        sub_cmd = _norm(subs_row.iloc[col]) if col < len(subs_row) else ""
        if not name:
            # En-tête de nom vide mais colonne "commande" bien présente : le nom réel a pu
            # être perdu (en-tête corrompu) tout en laissant une trace dans les données —
            # ex. client "AZIANTSI Dzifa" recopié par erreur en pleine zone de données sur un
            # fichier réel, sans quoi son historique (soldes/remboursements réels) disparaîtrait
            # silencieusement faute de nom pour le rattacher.
            if sub_cmd.startswith("command") and df is not None:
                found = _find_stray_name_in_column(df, col, data_start)
                if found:
                    name = found
            if not name:
                col += 1
                continue
        # Une cellule nommée dont l'en-tête dit clairement "remboursement"/"solde" n'est pas
        # le début d'un bloc client : c'est du texte tombé dans une des 2 colonnes suivantes
        # d'un bloc déjà ouvert (vu sur un fichier réel : nom de client éclaté sur 2 cellules,
        # ou mot isolé sans rapport laissé par erreur). On l'ignore comme début de bloc.
        if sub_cmd.startswith("rembours") or sub_cmd.startswith("remebours") or sub_cmd == "solde":
            col += 1
            continue
        # Accepte toute variante d'en-tête "commande" (ex. "Command" sans e final, "command"
        # en minuscules — variantes réelles observées) plutôt que d'exiger une correspondance
        # exacte : un simple typo d'en-tête ne doit jamais faire disparaître silencieusement
        # un client entier de l'import (bug confirmé : 10 clients perdus sur un fichier réel).
        extra = _cell_str(names_row.iloc[col + 1]) if col + 1 < len(names_row) else ""
        if extra:
            # Nom de client éclaté sur 2 cellules adjacentes (ex. "Mme Venavinon" / "KOMI") :
            # on le recolle plutôt que de perdre la seconde partie silencieusement.
            name = f"{name} {extra}"
        blocks.append({
            "name": name,
            "col_commande": col,
            "col_remb": col + 1,
            "col_solde": col + 2,
        })
        col += 3
    return blocks


def _collect_sheet_dates(df: pd.DataFrame, data_start: int) -> list[str]:
    dates: list[str] = []
    seen: set[str] = set()
    for row_idx in range(data_start, len(df)):
        dt = _parse_date_cell(df.iloc[row_idx, 0])
        if dt and dt not in seen:
            seen.add(dt)
            dates.append(dt)
    return dates


def try_parse_clientele_board(
    contents: bytes,
    sheet_name: str | int = 0,
    filename: str = "",
) -> dict | None:
    """Parse matriciel clientèle si structure détectée ; sinon None (pas d'erreur bloquante)."""
    try:
        df = load_spreadsheet(
            contents,
            filename=filename,
            sheet_name=sheet_name,
            header=None,
            max_columns=CLIENTELE_MAX_COLS,
        )
        df = _trim_df(df)
        layout = _find_clientele_layout(df)
        if not layout:
            return None
        parsed = _parse_clientele_dataframe(
            df, layout, sheet_label=str(sheet_name) if sheet_name not in (None, "") else "Feuil1"
        )
        return parsed if parsed and parsed.get("clients") else None
    except Exception:
        return None


def _parse_clientele_dataframe(
    df: pd.DataFrame,
    layout: tuple[int, int, int],
    *,
    sheet_label: str = "Feuil1",
) -> dict | None:
    title_row, names_row_idx, subs_row_idx = layout
    title = _cell_str(df.iloc[title_row, 0])
    names_row = df.iloc[names_row_idx]
    subs_row = df.iloc[subs_row_idx]
    data_start = subs_row_idx + 1

    max_col = min(len(df.columns), 3 + len([c for c in range(1, len(names_row)) if _cell_str(names_row.iloc[c])]) * 3 + 50)
    for c in range(len(names_row) - 1, 0, -1):
        if _cell_str(names_row.iloc[c]) or _cell_str(subs_row.iloc[c]):
            max_col = max(max_col, c + 3)
            break

    blocks = _collect_client_blocks(names_row, subs_row, max_col, df=df, data_start=data_start)
    if not blocks:
        return None

    all_dates = _collect_sheet_dates(df, data_start)
    clients: list[dict] = []
    all_dates_for_range: list = []

    for block in blocks:
        entries: list[dict] = []
        by_date: dict[str, dict] = {}
        running_solde = 0.0

        for row_idx in range(data_start, len(df)):
            row = df.iloc[row_idx]
            dt = _parse_date_cell(row.iloc[0])
            if not dt:
                continue

            commande = _cell_float(row.iloc[block["col_commande"]])
            remboursement = _cell_float(row.iloc[block["col_remb"]])
            solde_raw = _cell_float(row.iloc[block["col_solde"]])

            if commande is None and remboursement is None and solde_raw is None:
                # Aucune valeur ce jour-là pour ce client : pas de mouvement, mais surtout
                # pas de solde ici — sinon le solde réel est écrasé par 0 dès qu'une autre
                # colonne du tableau a des dates plus tardives que celles de ce client
                # (report de solde géré ci-dessous, après la boucle).
                continue

            cmd = commande or 0.0
            remb = remboursement or 0.0
            if solde_raw is None:
                # Commande/remboursement saisis sans solde : extrapole depuis le dernier solde
                # connu plutôt que de forcer 0 (cas réel : dernière ligne du fichier).
                solde = running_solde + cmd - remb
            else:
                solde = solde_raw
            running_solde = solde

            all_dates_for_range.append(pd.to_datetime(dt).date())
            rec = {
                "date": dt,
                "commande": cmd,
                "remboursement": remb,
                "solde": solde,
            }
            by_date[dt] = rec
            entries.append(rec)

        # Reconstruit la série complète sur toutes les dates du tableau en reportant
        # le dernier solde connu sur les dates sans mouvement (comme un vrai relevé de
        # compte) plutôt que de le remettre artificiellement à zéro.
        ordered_entries: list[dict] = []
        last_solde = 0.0
        for dt in all_dates:
            rec = by_date.get(dt)
            if rec is None:
                rec = {"date": dt, "commande": 0.0, "remboursement": 0.0, "solde": last_solde}
            else:
                last_solde = rec["solde"]
            ordered_entries.append(rec)

        last_solde = ordered_entries[-1]["solde"] if ordered_entries else 0.0
        total_commande = sum(e["commande"] for e in ordered_entries)
        total_remb = sum(e["remboursement"] for e in ordered_entries)

        clients.append({
            "name": block["name"],
            "entries": ordered_entries,
            "total_commande": total_commande,
            "total_remboursement": total_remb,
            "solde_actuel": last_solde,
            "nb_mouvements": len([e for e in ordered_entries if e["commande"] or e["remboursement"]]),
        })

    date_min = min(all_dates_for_range).isoformat() if all_dates_for_range else (all_dates[0] if all_dates else None)
    date_max = max(all_dates_for_range).isoformat() if all_dates_for_range else (all_dates[-1] if all_dates else None)

    return {
        "title": title,
        "clients": clients,
        "client_names": [c["name"] for c in clients],
        "nb_clients": len(clients),
        "nb_dates": len(all_dates),
        "all_dates": all_dates,
        "date_min": date_min,
        "date_max": date_max,
        "sheet": sheet_label,
    }


def parse_clientele_board(contents: bytes, sheet_name: str | int = 0, filename: str = "") -> dict:
    """Compatibilité : lève seulement si appel legacy ; préférer try_parse_clientele_board."""
    parsed = try_parse_clientele_board(contents, sheet_name=sheet_name, filename=filename)
    if not parsed:
        raise ValueError(
            "Structure matricielle clientèle non détectée. Utilisez un autre type d'import "
            "(Clients, Écritures…) ou la vue grille."
        )
    return parsed


def build_board_from_parsed(parsed: dict) -> dict:
    """Construit la matrice dates × clients (comme le fichier Excel)."""
    dates = parsed.get("all_dates") or []
    if not dates:
        all_dates: set[str] = set()
        for client in parsed["clients"]:
            for entry in client["entries"]:
                all_dates.add(entry["date"])
        dates = sorted(all_dates)

    board_clients = []
    for client in parsed["clients"]:
        by_date = {e["date"]: e for e in client["entries"]}
        board_clients.append({
            "name": client["name"],
            "commandes": [by_date[d]["commande"] if d in by_date else 0.0 for d in dates],
            "remboursements": [by_date[d]["remboursement"] if d in by_date else 0.0 for d in dates],
            "soldes": [by_date[d]["solde"] if d in by_date else 0.0 for d in dates],
        })

    return {
        "title": parsed.get("title") or "Tableau de board clientèle PC",
        "dates": dates,
        "clients": board_clients,
        "total_dates": len(dates),
        "truncated": False,
    }


def analyze_clientele(contents: bytes, sheet_name: str | int = 0, filename: str = "") -> dict:
    """Analyse pour aperçu clientèle ; ne bloque pas si le fichier n'est pas matriciel."""
    clientele_sheets = list_clientele_sheets(contents, filename=filename)
    parsed = try_parse_clientele_board(contents, sheet_name, filename)
    if not parsed:
        return {
            "ok": False,
            "format": "clientele_pc",
            "message": (
                "Structure matricielle non détectée dans ce fichier. "
                "Utilisez la vue liste ou choisissez un autre type d'import."
            ),
            "suggested_sheet_type": "clients",
            "suggested_types": ["clients", "transactions"],
            "clientele_sheets": clientele_sheets,
        }
    board = build_board_from_parsed(parsed)

    return {
        "ok": True,
        "format": "clientele_pc",
        "title": parsed["title"],
        "filename": filename,
        "sheets": clientele_sheets or [parsed["sheet"]],
        "clientele_sheets": clientele_sheets,
        "sheet_name": parsed["sheet"],
        "current_sheet": parsed["sheet"],
        "columns": ["Date", "Client", "Commande", "Remboursement", "Solde"],
        "sample_rows": [],
        "total_rows": board["total_dates"],
        "client_names": parsed["client_names"],
        "nb_clients": parsed["nb_clients"],
        "date_min": parsed["date_min"],
        "date_max": parsed["date_max"],
        "suggested_sheet_type": "clientele_pc",
        "suggested_types": ["clientele_pc"],
        "board": board,
    }


def list_clientele_sheets(contents: bytes, filename: str = "") -> list[str]:
    """Feuilles du classeur reconnues comme tableaux clientèle PC."""
    from io import BytesIO

    import pandas as pd

    try:
        xl = pd.ExcelFile(BytesIO(contents))
    except Exception:
        return []
    found: list[str] = []
    for sheet in xl.sheet_names:
        if try_parse_clientele_board(contents, sheet_name=sheet, filename=filename):
            found.append(sheet)
    return found
