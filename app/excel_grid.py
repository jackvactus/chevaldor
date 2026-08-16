"""Grille universelle — tout fichier Excel/CSV en tableau exploitable."""
from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

from app.excel_utils import _json_cell, load_spreadsheet

_UNNAMED_RE = re.compile(r"^Unnamed:\s*\d+$", re.IGNORECASE)
_COLONNE_AUTO_RE = re.compile(r"^Colonne_\d+$", re.IGNORECASE)


def is_junk_column(name: str) -> bool:
    """Colonnes fantômes Excel (Unnamed: 37, Colonne_12 sans libellé réel)."""
    s = str(name).strip()
    if not s:
        return True
    if _UNNAMED_RE.match(s):
        return True
    if _COLONNE_AUTO_RE.match(s):
        return True
    return False


def _series_has_meaningful_data(series: pd.Series, min_filled: int = 1) -> bool:
    filled = 0
    for v in series:
        if _cell_filled(v):
            filled += 1
            if filled >= min_filled:
                return True
    return False


def prune_dataframe_columns(df: pd.DataFrame, min_fill_ratio: float = 0.01) -> pd.DataFrame:
    """Supprime colonnes vides ou « Unnamed » sans données utiles."""
    if df.empty:
        return df
    keep: list = []
    row_count = max(len(df), 1)
    min_cells = max(1, int(row_count * min_fill_ratio))
    for col in df.columns:
        name = str(col).strip()
        if is_junk_column(name):
            continue
        series = df[col]
        if not _series_has_meaningful_data(series, 1):
            continue
        keep.append(col)
    if not keep:
        return df.iloc[:, :0]
    return df.loc[:, keep]

GRID_MAX_COLS = 120
GRID_PREVIEW_ROWS = 800


def _cell_filled(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(str(value).strip())


def detect_header_row(df_raw: pd.DataFrame, max_try: int = 15) -> int:
    """Trouve la ligne d'en-tête la plus probable (libellés de colonnes)."""
    best_row, best_score = 0, -1
    limit = min(max_try, len(df_raw))
    for r in range(limit):
        row = df_raw.iloc[r]
        non_empty = 0
        text_cells = 0
        for c in range(min(len(row), GRID_MAX_COLS)):
            v = row.iloc[c]
            if not _cell_filled(v):
                continue
            non_empty += 1
            if isinstance(v, str) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
                try:
                    pd.to_datetime(v)
                    continue
                except Exception:
                    text_cells += 1
        if non_empty < 2:
            continue
        score = non_empty * 3 + text_cells * 2
        if score > best_score:
            best_score = score
            best_row = r
    return best_row


def extract_grid(
    contents: bytes,
    filename: str = "",
    sheet_name: str | int = 0,
    header_row: Optional[int] = None,
) -> dict[str, Any]:
    """Extrait colonnes + lignes pour affichage et édition (tout format tabulaire)."""
    sn = sheet_name if sheet_name not in (None, "", "CSV") else 0
    raw = load_spreadsheet(
        contents,
        filename=filename,
        sheet_name=sn,
        header=None,
        max_columns=GRID_MAX_COLS,
    )
    hdr = int(header_row) if header_row is not None else detect_header_row(raw)
    df = load_spreadsheet(
        contents,
        filename=filename,
        sheet_name=sn,
        header=hdr,
        max_columns=GRID_MAX_COLS,
    )
    df = df.dropna(how="all")
    df = prune_dataframe_columns(df.dropna(axis=1, how="all"))

    # Secours : feuille lisible mais en-têtes non reconnus → colonnes positionnelles
    if df.empty or len(df.columns) == 0:
        df = raw.dropna(how="all").dropna(axis=1, how="all")
        if not df.empty:
            hdr = 0
            df.columns = [f"Colonne_{i + 1}" for i in range(len(df.columns))]
            if len(df) > 1 and detect_header_row(raw) > 0:
                hdr = detect_header_row(raw)
                hdr_df = load_spreadsheet(contents, filename=filename, sheet_name=sn, header=hdr, max_columns=GRID_MAX_COLS)
                hdr_df = hdr_df.dropna(how="all").dropna(axis=1, how="all")
                if not hdr_df.empty:
                    df = hdr_df
                    df = prune_dataframe_columns(df)
                    if df.empty:
                        df = hdr_df

    columns: list[str] = []
    for i, c in enumerate(df.columns):
        label = str(c).strip()
        if is_junk_column(label):
            label = f"Colonne_{i + 1}"
        columns.append(label if label else f"Colonne_{i + 1}")

    if not columns and not df.empty:
        columns = [f"Colonne_{i + 1}" for i in range(len(df.columns))]
        df.columns = columns

    if not columns:
        return {
            "columns": [],
            "rows": [],
            "total_rows": 0,
            "truncated": False,
            "header_row": hdr,
            "column_count": 0,
        }

    keep_cols = list(df.columns)
    rows: list[list] = []
    for row in df.itertuples(index=False):
        rows.append([_json_cell(v) for v in row])
    total = len(rows)
    truncated = total > GRID_PREVIEW_ROWS
    if truncated:
        rows = rows[:GRID_PREVIEW_ROWS]
    return {
        "columns": columns,
        "rows": rows,
        "total_rows": total,
        "truncated": truncated,
        "header_row": hdr,
        "column_count": len(columns),
    }


def board_to_flat_grid(board: dict) -> dict[str, Any]:
    """Convertit un tableau matriciel clientèle en grille longue (Date, Client, …)."""
    columns = ["Date", "Client", "Commande", "Remboursement", "Solde"]
    rows: list[list] = []
    for di, dt in enumerate(board.get("dates") or []):
        for cl in board.get("clients") or []:
            rows.append([
                dt,
                cl.get("name", ""),
                (cl.get("commandes") or [0])[di] if di < len(cl.get("commandes") or []) else 0,
                (cl.get("remboursements") or [0])[di] if di < len(cl.get("remboursements") or []) else 0,
                (cl.get("soldes") or [0])[di] if di < len(cl.get("soldes") or []) else 0,
            ])
    return {
        "columns": columns,
        "rows": rows[:GRID_PREVIEW_ROWS],
        "total_rows": len(rows),
        "truncated": len(rows) > GRID_PREVIEW_ROWS,
        "header_row": 0,
        "column_count": len(columns),
    }
