"""Analyse universelle de fichiers Excel / CSV (multi-feuilles, grilles, formats spéciaux)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.excel_clientele import analyze_clientele, detect_clientele_format
from app.excel_grid import GRID_MAX_COLS, GRID_PREVIEW_ROWS, board_to_flat_grid, detect_header_row, extract_grid
from app.excel_mapper import map_columns
from app.excel_utils import _json_cell, load_spreadsheet


def list_workbook_sheets(contents: bytes, filename: str = "") -> list[str]:
    ext = Path(filename or "").suffix.lower()
    if ext == ".csv":
        return ["CSV"]
    buf = BytesIO(contents)
    try:
        xl = pd.ExcelFile(buf)
        return list(xl.sheet_names) or ["Feuil1"]
    except Exception:
        return ["Feuil1"]


def _map_columns_enhanced(columns: list) -> dict[str, str]:
    from app.excel_mapper import COLUMN_ALIASES, _norm

    result: dict[str, str] = {}
    used_fields: set[str] = set()
    for col in columns:
        n = _norm(str(col))
        if not n or str(col).startswith("Unnamed"):
            continue
        matched = None
        for field, aliases in COLUMN_ALIASES.items():
            if field in used_fields:
                continue
            if n in aliases or n == field:
                matched = field
                break
            for alias in aliases:
                if n == alias or n == field:
                    matched = field
                    break
                if len(alias) >= 3 and (n == alias or n.endswith("_" + alias) or n.startswith(alias + "_")):
                    matched = field
                    break
                if len(alias) >= 4 and alias in n:
                    if alias == "fin" and "financial" in n:
                        continue
                    if alias == "num" and "numero" in n and field == "number":
                        continue
                    matched = field
                    break
            if matched:
                break
        if matched:
            result[str(col)] = matched
            used_fields.add(matched)
    return result


def _score_table(col_map: dict, row_count: int, col_count: int) -> int:
    if col_count < 1:
        return 0
    score = len(col_map) * 12 + min(row_count, 1000)
    score += col_count * 2
    return score


def _suggest_types(col_map: dict, columns: list | None = None) -> list[str]:
    from app.import_smart import looks_like_accounting_ledger, looks_like_clientele_wide

    targets = set(col_map.values())
    types: list[str] = []
    if columns and looks_like_accounting_ledger(columns):
        types.insert(0, "transactions")
    if columns and looks_like_clientele_wide(columns):
        types.append("clientele_pc")
    if "name" in targets and ("commande" in targets or "remboursement" in targets):
        if "clientele_pc" not in types:
            types.append("clientele_pc")
    if "name" in targets:
        types.append("clients")
    if "number" in targets and "amount" in targets:
        types.append("invoices")
    if "name" in targets and ("budget" in targets or "pole" in targets):
        types.append("projects")
    if "label" in targets or ("amount" in targets and "date" in targets):
        types.append("transactions")
    if "title" in targets or ("name" in targets and "amount" in targets):
        types.append("deals")
    return types or ["clients"]


def analyze_tabular(
    contents: bytes,
    filename: str,
    sheet_name: str | int = 0,
    header_row: Optional[int] = None,
) -> dict[str, Any]:
    grid = extract_grid(contents, filename, sheet_name=sheet_name, header_row=header_row)
    from app.import_smart import count_junk_columns, filter_meaningful_columns

    all_columns = grid.get("columns") or []
    columns = filter_meaningful_columns(all_columns)
    keep_i = [i for i, c in enumerate(all_columns) if str(c) in columns]
    grid["columns"] = columns
    if grid.get("rows") and keep_i:
        grid["rows"] = [[row[i] if i < len(row) else "" for i in keep_i] for row in grid["rows"]]
    col_map = _map_columns_enhanced(columns)
    suggested = _suggest_types(col_map, columns)
    from app.import_smart import (
        build_smart_mapping,
        columns_for_display,
        detect_import_profile,
        file_is_clientele_matrix,
    )

    from app.import_smart import looks_like_accounting_ledger

    if looks_like_accounting_ledger(columns):
        recommended = "transactions"
        smart_map = build_smart_mapping(columns, "transactions")
        profile = detect_import_profile(columns, col_map=smart_map)
    else:
        recommended = suggested[0] if suggested else "clients"
        smart_map = build_smart_mapping(columns, recommended)
        profile = detect_import_profile(columns, col_map=smart_map)
    if file_is_clientele_matrix(contents, filename, sheet_name):
        profile["matrix_available"] = True
        profile["clientele_wide"] = True
        if "clientele_pc" not in suggested:
            suggested = ["clientele_pc"] + [t for t in suggested if t != "clientele_pc"]
        if not looks_like_accounting_ledger(columns):
            profile["recommended_type"] = profile.get("recommended_type") or "clientele_pc"
            profile["label"] = profile.get("label") or "Tableau clientèle (matrice)"
            if recommended == "clients":
                recommended = "clientele_pc"
    return {
        "ok": True,
        "format": "tabular",
        "layout": "tabular",
        "filename": filename,
        "sheet_name": sheet_name if isinstance(sheet_name, str) else str(sheet_name),
        "header_row": grid["header_row"],
        "columns": columns,
        "column_mapping": smart_map,
        "smart_mapping": smart_map,
        "display_columns": columns_for_display(columns, smart_map),
        "mapped_fields": list(smart_map.values()),
        "sample_rows": grid["rows"][: min(50, len(grid["rows"]))],
        "preview_rows": min(len(grid["rows"]), GRID_PREVIEW_ROWS),
        "total_rows": grid["total_rows"],
        "suggested_types": suggested,
        "suggested_sheet_type": recommended,
        "smart_profile": profile,
        "grid": grid,
        "grid_truncated": grid.get("truncated", False),
    }


def analyze_workbook(
    contents: bytes,
    filename: str = "",
    sheet_name: Optional[str] = None,
    header_row: Optional[int] = None,
) -> dict[str, Any]:
    """
    Analyse un classeur : compare feuilles et layouts (liste ou matriciel),
    retourne toujours une grille exploitable quand le fichier est lisible.
    """
    sheets = list_workbook_sheets(contents, filename)
    if sheet_name is not None and sheet_name != "":
        sheets_to_try: list[str | int] = [sheet_name if sheet_name != "CSV" else 0]
    else:
        sheets_to_try = [0] if sheets == ["CSV"] else list(sheets)

    candidates: list[tuple[int, str, dict]] = []
    matrix_option: Optional[dict] = None

    for sheet in sheets_to_try:
        sn = sheet if sheet not in (None, "", "CSV") else 0
        # Format matriciel — seulement si la feuille a assez de colonnes (évite 40s sur listes simples)
        try:
            from app.excel_clientele import CLIENTELE_MAX_COLS, _trim_df

            raw = load_spreadsheet(
                contents, filename, sheet_name=sn, header=None, max_columns=CLIENTELE_MAX_COLS
            )
            raw = _trim_df(raw)
            wide_enough = len(raw.columns) >= 6 or any(
                len(raw.iloc[r].dropna()) >= 6 for r in range(min(8, len(raw)))
            )
            if wide_enough and detect_clientele_format(raw):
                cli = analyze_clientele(contents, sheet_name=sn, filename=filename)
                cli["layout"] = "matrix"
                cli["sheets"] = sheets
                score = 400 + (cli.get("nb_clients") or 0) * 15 + (cli.get("total_rows") or 0)
                matrix_option = cli
                candidates.append((score, "matrix", cli))
        except Exception:
            pass

        # En-têtes probables : ligne choisie + voisinage + détection auto
        if header_row is not None:
            header_candidates = [int(header_row)]
        else:
            try:
                raw_probe = load_spreadsheet(contents, filename, sheet_name=sn, header=None, max_columns=GRID_MAX_COLS)
                best = detect_header_row(raw_probe)
                header_candidates = sorted({best, max(0, best - 1), min(best + 1, 14), 0, 1, 2})
            except Exception:
                header_candidates = list(range(0, 8))
        for hdr in header_candidates:
            try:
                tab = analyze_tabular(contents, filename, sheet_name=sn, header_row=hdr)
                ncols = len(tab.get("columns") or [])
                nrows = tab.get("total_rows") or 0
                if ncols < 1 and nrows < 1:
                    continue
                score = _score_table(tab["column_mapping"], nrows, ncols)
                if ncols >= 1:
                    score = max(score, 10 + ncols + min(nrows, 500))
                candidates.append((score, "tabular", tab))
            except Exception:
                continue

    if not candidates:
        # Dernier recours : grille brute sans mapping
        for sheet in sheets_to_try:
            sn = sheet if sheet not in (None, "", "CSV") else 0
            try:
                grid = extract_grid(contents, filename, sheet_name=sn, header_row=header_row)
                if grid.get("columns"):
                    tab = analyze_tabular(contents, filename, sheet_name=sn, header_row=grid.get("header_row", 0))
                    tab["ok"] = True
                    candidates.append((5, "tabular", tab))
                    break
            except Exception:
                continue

    if not candidates:
        return {
            "ok": False,
            "message": (
                "Fichier illisible ou vide. Vérifiez le format (.xlsx, .xls, .xlsm, .csv, .ods) "
                "et qu'au moins une feuille contient des données."
            ),
            "sheets": sheets,
        }

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_layout, result = candidates[0]

    # Si matriciel gagne de justesse, préférer la vue liste (plus universelle)
    if best_layout == "matrix" and len(candidates) > 1:
        for sc, layout, payload in candidates:
            if layout == "tabular" and sc >= best_score * 0.35:
                best_layout, result = layout, payload
                break

    result["sheets"] = sheets
    result["layout"] = result.get("layout") or best_layout
    result["available_layouts"] = []
    if matrix_option:
        result["available_layouts"].append(
            {"layout": "matrix", "label": "Tableau matriciel (type clientèle PC)", "sheet_name": matrix_option.get("sheet_name")}
        )
    if result.get("layout") != "tabular" and any(c[1] == "tabular" for c in candidates):
        tab = next(c[2] for c in candidates if c[1] == "tabular")
        result["available_layouts"].append(
            {"layout": "tabular", "label": "Liste (colonnes/lignes)", "sheet_name": tab.get("sheet_name"), "header_row": tab.get("header_row")}
        )
    elif result.get("layout") == "tabular" and matrix_option:
        result["available_layouts"].append(
            {"layout": "matrix", "label": "Tableau matriciel détecté", "sheet_name": matrix_option.get("sheet_name")}
        )

    # Grille universelle : toujours fournie pour exploitation des données
    if result.get("layout") == "matrix" and result.get("board"):
        result["grid"] = board_to_flat_grid(result["board"])
        result["format"] = "clientele_pc"
    elif not result.get("grid"):
        try:
            result["grid"] = extract_grid(
                contents,
                filename,
                sheet_name=result.get("sheet_name", 0),
                header_row=result.get("header_row"),
            )
        except Exception:
            pass

    if matrix_option and result.get("board") is None and best_layout == "tabular":
        result["board"] = matrix_option.get("board")
        result["matrix_available"] = True

    from app.import_smart import (
        build_smart_mapping,
        columns_for_display,
        detect_import_profile,
    )

    cols = result.get("columns") or (result.get("grid") or {}).get("columns") or []
    matrix_avail = bool(matrix_option or result.get("matrix_available"))
    rec = "clientele_pc" if matrix_avail else (result.get("suggested_sheet_type") or "clients")
    smart_map = build_smart_mapping(cols, rec)
    profile = detect_import_profile(
        cols,
        matrix_available=matrix_avail,
        layout=result.get("layout") or "tabular",
        col_map=smart_map,
    )
    if profile.get("clientele_wide") or matrix_avail:
        rec = "clientele_pc"
        smart_map = build_smart_mapping(cols, "clientele_pc")
        profile = detect_import_profile(
            cols, matrix_available=matrix_avail, layout=result.get("layout") or "tabular", col_map=smart_map
        )
    result["suggested_sheet_type"] = rec
    result["smart_profile"] = profile
    result["smart_mapping"] = smart_map
    result["column_mapping"] = smart_map
    result["display_columns"] = columns_for_display(cols, smart_map)
    result["mapped_fields"] = list(smart_map.values())
    if matrix_avail:
        result["format"] = result.get("format") or "clientele_pc"

    result["ok"] = True
    return result
