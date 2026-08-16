"""Tests import Excel — feuilles courtes (ex. Clients) et analyse."""
from io import BytesIO

import pandas as pd
import pytest

from app.excel_smart import analyze_workbook
from app.excel_utils import load_spreadsheet


def _xlsx_bytes(sheet_name: str, rows: list, header: bool = True) -> bytes:
    df = pd.DataFrame(rows[1:], columns=rows[0]) if header and len(rows) > 1 else pd.DataFrame(rows)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=sheet_name, index=False, header=header)
    return buf.getvalue()


def test_load_spreadsheet_few_columns():
  data = _xlsx_bytes("Clients", [["Nom", "Email"], ["Alice", "a@test.com"]])
  df = load_spreadsheet(data, "clients.xlsx", sheet_name="Clients", max_columns=120)
  assert list(df.columns) == ["Nom", "Email"]
  assert len(df) == 1


def test_analyze_workbook_clients_sheet():
  data = _xlsx_bytes("Clients", [["Nom", "Email", "Telephone"], ["Bob", "b@x.com", "010203"]])
  r = analyze_workbook(data, "export.xlsx", sheet_name="Clients")
  assert r.get("ok") is True
  assert r.get("columns")
  assert (r.get("total_rows") or 0) >= 1
  assert "name" in (r.get("mapped_fields") or []) or "Nom" in (r.get("columns") or [])


def test_analyze_workbook_offset_header():
  rows = [["", ""], ["Liste clients", ""], ["Nom", "Email"], ["A", "a@x.com"]]
  data = _xlsx_bytes("Feuil1", rows, header=False)
  r = analyze_workbook(data, "liste.xlsx")
  assert r.get("ok") is True
  assert (r.get("total_rows") or 0) >= 1


def test_invoice_import_mapping():
  from app.excel_mapper import ensure_import_mapping
  from app.import_smart import build_smart_mapping

  cols = ["Numéro", "Client", "Date", "Montant TTC", "TVA", "Commission", "Statut"]
  col_map = ensure_import_mapping(cols, build_smart_mapping(cols, "invoices"), "invoices")
  assert "number" in col_map.values()
  assert "client_name" in col_map.values() or "amount" in col_map.values()


def test_normalize_invoice_status():
  from app.excel_mapper import _normalize_invoice_status

  assert _normalize_invoice_status("Payée") == "payée"
  assert _normalize_invoice_status("sent") == "envoyée"
  assert _normalize_invoice_status("") == "brouillon"
