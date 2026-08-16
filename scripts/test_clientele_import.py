#!/usr/bin/env python3
"""Test bout-en-bout import clientèle PC (isolated DB)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys

TEST_DIR = "/tmp/clientele_import_test"
EXCEL = "/tmp/clientele_test.xlsx"


def main() -> int:
    os.makedirs(TEST_DIR, exist_ok=True)
    shutil.copy("/data/peya_company.db", f"{TEST_DIR}/peya_company.db")
    os.environ["PEYA_DATA_DIR"] = TEST_DIR

    sys.path.insert(0, "/app/backend")
    from app.database import SessionLocal
    from app.excel_clientele import try_parse_clientele_board
    from app.import_service import import_clientele_all_sheets

    with open(EXCEL, "rb") as f:
        contents = f.read()

    db = SessionLocal()
    try:
        result = import_clientele_all_sheets(
            db,
            contents,
            "TABLEAU DE BOARD DE LA CLIENTELE PC new (2).xlsx",
            mode="replace",
        )
        print("Import result:", result)
    finally:
        db.close()

    excel_clients: dict[str, float] = {}
    for sheet in ("Nouveau vente", "Feuil1"):
        parsed = try_parse_clientele_board(contents, sheet_name=sheet, filename="x.xlsx")
        if not parsed:
            print(f"WARN: parse failed for {sheet}")
            continue
        for c in parsed["clients"]:
            excel_clients[c["name"].strip().lower()] = c["solde_actuel"]

    conn = sqlite3.connect(f"{TEST_DIR}/peya_company.db")
    prod: dict[str, tuple[float, int]] = {}
    for row in conn.execute(
        """
        SELECT c.name,
          (SELECT cle.solde FROM client_ledger cle
           WHERE cle.client_id=c.id ORDER BY cle.date DESC, cle.id DESC LIMIT 1),
          (SELECT COUNT(*) FROM client_ledger cle
           WHERE cle.client_id=c.id AND (cle.commande>0.01 OR cle.remboursement>0.01))
        FROM clients c
        WHERE c.segment='Clientèle PC' AND (c.is_archived IS NULL OR c.is_archived=0)
        """
    ):
        prod[row[0].strip().lower()] = (row[1], row[2])

    print("Excel clients:", len(excel_clients), "DB clients:", len(prod))
    mismatches = []
    for name, excel_solde in excel_clients.items():
        if name not in prod:
            mismatches.append((name, excel_solde, "MISSING"))
        elif abs(prod[name][0] - excel_solde) > 0.01:
            mismatches.append((name, excel_solde, prod[name][0]))
    print("Solde mismatches:", len(mismatches))
    for m in mismatches[:20]:
        print(" ", m)

    reste = sum(max(0, s[0]) for s in prod.values())
    expected_reste = sum(max(0, s) for s in excel_clients.values())
    print("DB reste_a_payer:", reste, "Expected:", expected_reste)
    conn.close()
    return 1 if mismatches or len(prod) != len(excel_clients) else 0


if __name__ == "__main__":
    raise SystemExit(main())
