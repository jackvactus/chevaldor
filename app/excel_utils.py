"""Utilitaires lecture Excel / CSV — robustes (petites et grandes feuilles)."""
import math
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd


def _excel_str(value, default=""):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return default if text.lower() == "nan" else text


def _excel_float(value, default=0.0):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return float(value)


def _excel_int(value, default=0):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return int(float(value))


def _excel_date(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return pd.to_datetime(value).date()


def _json_cell(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return _json_cell(value.item())
    return value


def _sample_rows(df, n=3):
    rows = []
    for row in df.head(n).itertuples(index=False):
        rows.append([_json_cell(v) for v in row])
    return rows


def _trim_columns(df: pd.DataFrame, max_columns: int | None) -> pd.DataFrame:
    if max_columns and max_columns > 0 and len(df.columns) > max_columns:
        return df.iloc[:, :max_columns]
    return df


def _read_csv(buf: BytesIO, header=0) -> pd.DataFrame:
    """CSV avec détection encodage / séparateur."""
    raw = buf.getvalue()
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        for sep in (";", ",", "\t", "|"):
            try:
                return pd.read_csv(BytesIO(raw), header=header, sep=sep, encoding=enc, on_bad_lines="skip")
            except Exception:
                continue
    return pd.read_csv(BytesIO(raw), header=header, on_bad_lines="skip")


def _read_excel(buf: BytesIO, sheet_name, header) -> pd.DataFrame:
    """Lecture Excel sans usecols (évite l'erreur pandas sur petites feuilles)."""
    buf.seek(0)
    try:
        return pd.read_excel(buf, sheet_name=sheet_name, header=header, engine="openpyxl")
    except Exception:
        buf.seek(0)
        try:
            return pd.read_excel(buf, sheet_name=sheet_name, header=header)
        except Exception:
            buf.seek(0)
            return pd.read_excel(buf, sheet_name=sheet_name, header=header, engine="xlrd")


def load_spreadsheet(
    contents: bytes,
    filename: str = "",
    sheet_name=0,
    header=0,
    max_columns: int | None = None,
):
    """Charge un fichier Excel ou CSV en DataFrame."""
    ext = Path(filename or "").suffix.lower()
    buf = BytesIO(contents)
    sn = sheet_name if sheet_name not in (None, "", "CSV") else 0

    if ext == ".csv":
        df = _read_csv(buf, header=header)
    elif ext in (".xls", ".xlsx", ".xlsm", ".xlsb", ".odf", ".ods", ".odt"):
        df = _read_excel(buf, sn, header)
    else:
        try:
            df = _read_excel(buf, sn, header)
        except Exception:
            buf.seek(0)
            df = _read_csv(buf, header=header)

    return _trim_columns(df, max_columns)
