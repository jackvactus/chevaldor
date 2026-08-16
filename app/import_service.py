"""Services d'import Excel (clientèle + mapping)."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.excel_clientele import build_board_from_parsed, list_clientele_sheets, try_parse_clientele_board
from app.excel_mapper import _norm, ensure_import_mapping, row_get
from app.import_smart import looks_like_clientele_wide
from app.models import Client, ClientLedgerEntry

CLIENTELE_SEGMENT = "Clientèle PC"


def _grid_row_dict(columns: list, row: list) -> dict:
    out: dict[str, Any] = {}
    for i, col in enumerate(columns):
        if i < len(row):
            out[str(col)] = row[i]
    return out


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _cell_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _cell_date_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, date):
        return value.isoformat()
    try:
        ts = pd.to_datetime(value, dayfirst=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date().isoformat()
    except Exception:
        s = _cell_str(value)
        if not s:
            return None
        try:
            ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
            if pd.isna(ts):
                return None
            return ts.date().isoformat()
        except Exception:
            return None


def _column_looks_like_client_name(col: str) -> bool:
    n = _norm(str(col))
    if not n or any(x in n for x in ("date", "jour", "commande", "remboursement", "solde", "montant")):
        return False
    return n in ("client", "nom_client", "nom", "name") or "client" in n or n.startswith("nom")


def _is_long_clientele_grid(columns: list, col_map: dict) -> bool:
    """Grille longue Date + Client + montants (pas tableau large multi-clients)."""
    targets = set(col_map.values())
    has_client_col = any(_column_looks_like_client_name(c) for c in columns)
    if not has_client_col:
        return False
    has_date = "date" in targets or any(
        _norm(str(c)) in ("date", "dates", "jour") or str(c).strip().lower() == "date" for c in columns
    )
    has_amount = any(t in targets for t in ("commande", "remboursement", "solde"))
    return has_client_col and has_date and has_amount


def _has_clientele_flat_columns(columns: list, col_map: dict) -> bool:
    return _is_long_clientele_grid(columns, col_map)


def build_board_from_flat_grid(grid: dict, custom_map: Optional[dict] = None) -> dict | None:
    """Convertit une grille longue (Date, Client, Commande, …) en matrice clientèle."""
    from app.excel_smart import _map_columns_enhanced

    columns = grid.get("columns") or []
    rows = grid.get("rows") or []
    if not columns or not rows:
        return None

    col_map = _map_columns_enhanced(columns)
    if custom_map:
        col_map.update({str(k): str(v) for k, v in custom_map.items() if v})
    col_map = ensure_import_mapping(columns, col_map, "clients")
    if not _has_clientele_flat_columns(columns, col_map):
        return None

    dates_order: list[str] = []
    dates_seen: set[str] = set()
    clients_data: dict[str, dict] = {}

    for raw in rows:
        row = _grid_row_dict(columns, raw) if isinstance(raw, list) else raw
        if not any(_cell_str(v) for v in row.values()):
            continue
        client_name = _cell_str(
            row_get(row, col_map, "name") or row_get(row, col_map, "client_name")
        )
        if not client_name or client_name.lower() in ("nan", "none"):
            continue
        dt_iso = _cell_date_iso(row_get(row, col_map, "date"))
        if not dt_iso:
            continue
        if dt_iso not in dates_seen:
            dates_seen.add(dt_iso)
            dates_order.append(dt_iso)
        idx = dates_order.index(dt_iso)
        bucket = clients_data.setdefault(
            client_name,
            {"name": client_name, "commandes": [], "remboursements": [], "soldes": []},
        )
        for key in ("commandes", "remboursements", "soldes"):
            while len(bucket[key]) <= idx:
                bucket[key].append(0.0)
        bucket["commandes"][idx] += _cell_float(row_get(row, col_map, "commande"))
        bucket["remboursements"][idx] += _cell_float(row_get(row, col_map, "remboursement"))
        bucket["soldes"][idx] += _cell_float(row_get(row, col_map, "solde"))

    if not clients_data:
        return None
    return {
        "title": grid.get("title") or "Import clientèle",
        "dates": dates_order,
        "clients": list(clients_data.values()),
    }


def import_clientele_from_grid(
    db: Session,
    grid: dict,
    contents: bytes | None = None,
    filename: str = "",
    custom_map: Optional[dict] = None,
    sheet_name: str | int = 0,
) -> dict:
    """Import clientèle flexible : grille longue, large ou fichier matriciel."""
    return import_clientele_flexible(
        db,
        contents=contents,
        filename=filename,
        grid=grid,
        board=None,
        custom_map=custom_map,
        sheet_name=sheet_name,
    )


def import_clientele_flexible(
    db: Session,
    *,
    contents: bytes | None = None,
    filename: str = "",
    grid: dict | None = None,
    board: dict | None = None,
    custom_map: Optional[dict] = None,
    sheet_name: str | int = 0,
    mode: str = "replace",
    auto_commit: bool = True,
) -> dict:
    """
    Tente plusieurs interprétations (matrice, grille large, grille longue, fichier)
    sans exiger un titre ou un modèle Excel fixe.
    """
    total = 0
    if board and board.get("clients"):
        result = import_clientele_board_data(
            db, board, filename, mode=mode, auto_commit=auto_commit,
        )
        result["total"] = max(total, result.get("imported", 0))
        return result

    if grid:
        total = int(grid.get("total_rows") or len(grid.get("rows") or []))
        for builder in (
            lambda: build_board_from_flat_grid(grid, custom_map=custom_map),
            lambda: build_board_from_wide_grid(grid),
        ):
            built = builder()
            if built and built.get("clients"):
                result = import_clientele_board_data(
                    db, built, filename, mode=mode, auto_commit=auto_commit,
                )
                result["total"] = max(total, result.get("imported", 0))
                return result

    if contents:
        parsed = try_parse_clientele_board(contents, sheet_name=sheet_name, filename=filename)
        if parsed and parsed.get("clients"):
            result = import_clientele_board_data(
                db, build_board_from_parsed(parsed), filename, mode=mode, auto_commit=auto_commit,
            )
            result["total"] = max(total, result.get("imported", 0))
            return result
        if grid:
            built = build_board_from_wide_grid(grid)
            if built and built.get("clients"):
                result = import_clientele_board_data(
                    db, built, filename, mode=mode, auto_commit=auto_commit,
                )
                result["total"] = max(total, result.get("imported", 0))
                result["message"] = (
                    f"{result.get('message', '')} (interprétation automatique de la grille)"
                )
                return result

    return {
        "ok": False,
        "format": "clientele_pc",
        "imported": 0,
        "total": total,
        "errors": [
            "Aucune structure clientèle exploitable (date + montants commande/remboursement/solde). "
            "Choisissez un autre type d'enregistrement (Clients, Écritures…) ou ajustez la ligne d'en-tête."
        ],
        "message": (
            "Import clientèle matriciel impossible avec ces données. "
            "Essayez « Clients / contacts » ou « Écritures comptables »."
        ),
    }


def _clear_clientele(db: Session) -> dict:
    """Remplace la clientèle PC sans violer les clés étrangères.

    Un client Clientèle PC peut désormais avoir de vrais documents commerciaux liés
    (devis/factures importés ou saisis depuis son segment — voir §M6 CLAUDE.md) : le
    supprimer physiquement violerait alors une contrainte de clé étrangère et faisait
    planter tout l'import/effacement avec un message générique et trompeur
    (« ce client est encore utilisé ailleurs »). On archive désormais ces clients au
    lieu de les supprimer, exactement comme le fait la suppression normale d'un client
    (`delete_or_archive_client`), et on ne fait jamais échouer l'opération entière pour
    un seul client bloqué.
    """
    from app.services.client_lifecycle_service import _cascade_cleanup, analyze_client_dependencies

    clients = db.query(Client).filter(Client.segment == CLIENTELE_SEGMENT).all()
    deleted = 0
    archived = 0
    for client in clients:
        cid = client.id
        analysis = analyze_client_dependencies(db, cid)
        if analysis["blocking_count"] > 0:
            if hasattr(client, "is_archived"):
                client.is_archived = True
            client.status = "inactif"
            archived += 1
            continue
        db.query(ClientLedgerEntry).filter(ClientLedgerEntry.client_id == cid).delete(
            synchronize_session=False
        )
        _cascade_cleanup(db, cid)
        db.delete(client)
        deleted += 1
    db.flush()
    return {"deleted": deleted, "archived": archived}


def clear_clientele_import(db: Session) -> dict:
    """Supprime toutes les données Clientèle PC importées (clients + mouvements)."""
    from pathlib import Path

    from app.models import Attachment, ImportBatch

    clients = db.query(Client).filter(Client.segment == CLIENTELE_SEGMENT).all()
    client_ids = [c.id for c in clients]
    entries_count = 0
    if client_ids:
        entries_count = db.query(ClientLedgerEntry).filter(
            ClientLedgerEntry.client_id.in_(client_ids)
        ).count()
    clients_count = len(clients)
    batch_ids = [
        bid for (bid,) in db.query(ImportBatch.id).filter(ImportBatch.sheet_type == "clientele_pc").all()
    ]
    if batch_ids:
        # Le fichier Excel brut de chaque import est conservé comme pièce jointe
        # (attachments.import_batch_id -> import_batches.id, sans cascade en base) : la
        # supprimer sans détacher d'abord ces pièces jointes viole la contrainte de clé
        # étrangère et fait planter tout l'effacement (bug confirmé sur la base réelle).
        stray_attachments = db.query(Attachment).filter(Attachment.import_batch_id.in_(batch_ids)).all()
        for att in stray_attachments:
            try:
                Path(att.stored_path).unlink(missing_ok=True)
            except OSError:
                pass
            db.delete(att)
        db.flush()
    batches_removed = db.query(ImportBatch).filter(
        ImportBatch.sheet_type == "clientele_pc"
    ).delete(synchronize_session=False)
    result = _clear_clientele(db)
    db.commit()
    archived_note = (
        f" {result['archived']} client(s) avec factures/devis/opportunités liés ont été archivés "
        "plutôt que supprimés."
        if result["archived"] else ""
    )
    return {
        "ok": True,
        "clients_removed": result["deleted"],
        "clients_archived": result["archived"],
        "entries_removed": entries_count,
        "batches_removed": batches_removed,
        "message": (
            f"Import effacé : {result['deleted']} client(s) supprimé(s), {entries_count} mouvement(s) supprimés."
            + (f" {batches_removed} entrée(s) d'historique retirée(s)." if batches_removed else "")
            + archived_note
        ),
    }


def import_clientele_board_data(
    db: Session,
    board: dict,
    filename: str = "",
    *,
    mode: str = "replace",
    auto_commit: bool = True,
) -> dict:
    """Importe depuis la matrice éditée (aperçu JSON). mode: replace | merge."""
    imported_clients = 0
    imported_entries = 0
    errors: list[str] = []

    if mode != "merge":
        try:
            _clear_clientele(db)
            db.flush()
        except Exception as e:
            db.rollback()
            return {
                "ok": False,
                "format": "clientele_pc",
                "imported": 0,
                "total": 0,
                "clients_imported": 0,
                "errors": [str(e)],
                "message": f"Erreur lors du remplacement clientèle : {e}",
            }

    dates = board.get("dates") or []
    ledger_batch = []
    # Comparaison en Python (str.lower() gère correctement les accents/ligatures comme "Œ"),
    # pas en SQL : LOWER() de SQLite est ASCII-only et ne reconnaît pas "Œ" comme "œ" — un
    # client dont le nom contient ce genre de caractère (ex. "SŒUR SIKA", vu sur un fichier
    # réel) n'était donc jamais retrouvé en mode fusion et se dupliquait à chaque réimport.
    existing_by_name: dict[str, Client] = {}
    if mode == "merge":
        for c in db.query(Client).filter(
            Client.segment == CLIENTELE_SEGMENT,
            Client.is_archived.isnot(True),
        ).all():
            existing_by_name.setdefault((c.name or "").strip().lower(), c)
    for client_data in board.get("clients") or []:
        name = (client_data.get("name") or "").strip()
        if not name:
            continue
        nested = db.begin_nested()
        try:
            client = existing_by_name.get(name.lower()) if mode == "merge" else None
            if not client:
                parts = name.split(" ", 1)
                client = Client(
                    name=name,
                    type="Particulier",
                    segment=CLIENTELE_SEGMENT,
                    contact=parts[0],
                    status="actif",
                    notes=f"Importé depuis {filename or 'Excel'}",
                )
                db.add(client)
                db.flush()
                imported_clients += 1
                if mode == "merge":
                    existing_by_name[name.lower()] = client
            elif mode == "merge" and filename:
                src = f"Source: {filename}"
                notes = client.notes or ""
                if src not in notes:
                    client.notes = (notes + "\n" + src).strip()
            commandes = client_data.get("commandes") or []
            remboursements = client_data.get("remboursements") or []
            soldes = client_data.get("soldes") or []
            for i, dt_str in enumerate(dates):
                cmd = float(commandes[i]) if i < len(commandes) else 0.0
                remb = float(remboursements[i]) if i < len(remboursements) else 0.0
                solde = float(soldes[i]) if i < len(soldes) else 0.0
                if cmd == 0 and remb == 0 and solde == 0:
                    continue
                d = date.fromisoformat(str(dt_str)[:10])
                if mode == "merge":
                    existing = db.query(ClientLedgerEntry).filter(
                        ClientLedgerEntry.client_id == client.id,
                        ClientLedgerEntry.date == d,
                    ).first()
                    if existing:
                        existing.commande = cmd
                        existing.remboursement = remb
                        existing.solde = solde
                        existing.source_file = filename
                        imported_entries += 1
                        continue
                ledger_batch.append(ClientLedgerEntry(
                    client_id=client.id,
                    date=d,
                    commande=cmd,
                    remboursement=remb,
                    solde=solde,
                    source_file=filename,
                ))
                imported_entries += 1
            nested.commit()
        except Exception as e:
            nested.rollback()
            errors.append(f"{name}: {e}")

    if ledger_batch:
        try:
            db.bulk_save_objects(ledger_batch)
            db.flush()
        except Exception as e:
            db.rollback()
            return {
                "ok": False,
                "format": "clientele_pc",
                "imported": 0,
                "total": 0,
                "clients_imported": imported_clients,
                "errors": errors + [str(e)],
                "message": f"Erreur enregistrement mouvements : {e}",
            }

    if imported_clients == 0 and imported_entries == 0:
        db.rollback()
        return {
            "ok": False,
            "format": "clientele_pc",
            "imported": 0,
            "total": 0,
            "clients_imported": 0,
            "errors": errors or ["Aucun client ni mouvement détecté dans les données."],
            "message": "Aucune donnée clientèle à enregistrer.",
        }

    if auto_commit:
        db.commit()
    date_min = dates[0] if dates else None
    date_max = dates[-1] if dates else None
    return {
        "ok": True,
        "format": "clientele_pc",
        "imported": imported_entries,
        "total": imported_entries,
        "clients_imported": imported_clients,
        "errors": errors,
        "message": f"{imported_clients} clients · {imported_entries} mouvements importés",
        "title": board.get("title") or "",
        "date_min": date_min,
        "date_max": date_max,
    }


def build_board_from_wide_grid(grid: dict) -> dict | None:
    """
    Reconstruit une matrice clientèle depuis la vue liste (Dates + triplets Commande/Remb./Solde).
    Utilisé en secours si le parseur matriciel du fichier échoue.
    """
    columns = [str(c) for c in (grid.get("columns") or [])]
    rows = grid.get("rows") or []
    if not columns or not rows or not looks_like_clientele_wide(columns):
        return None

    date_idx = 0
    for i, col in enumerate(columns):
        n = _norm(str(col))
        if n in ("date", "dates", "jour") or n.startswith("date"):
            date_idx = i
            break

    triplets: list[dict] = []
    i = 0
    while i < len(columns):
        if i == date_idx:
            i += 1
            continue
        n = _norm(str(columns[i]))
        if n == "commande" or n.startswith("commande"):
            if i + 2 < len(columns):
                suffix = str(columns[i])
                m = re.search(r"\.(\d+)$", suffix)
                idx = int(m.group(1)) + 1 if m else len(triplets) + 1
                triplets.append({
                    "name": f"Client {idx}",
                    "cmd": i,
                    "remb": i + 1,
                    "solde": i + 2,
                })
                i += 3
                continue
        i += 1

    if not triplets:
        return None

    dates_order: list[str] = []
    dates_seen: set[str] = set()
    clients_data = [
        {"name": t["name"], "commandes": [], "remboursements": [], "soldes": []}
        for t in triplets
    ]

    for raw in rows:
        row = _grid_row_dict(columns, raw) if isinstance(raw, list) else raw
        dt_iso = _cell_date_iso(row.get(columns[date_idx]) if date_idx < len(columns) else None)
        if not dt_iso:
            continue
        if dt_iso not in dates_seen:
            dates_seen.add(dt_iso)
            dates_order.append(dt_iso)
        di = dates_order.index(dt_iso)
        for ci, t in enumerate(triplets):
            while len(clients_data[ci]["commandes"]) <= di:
                clients_data[ci]["commandes"].append(0.0)
                clients_data[ci]["remboursements"].append(0.0)
                clients_data[ci]["soldes"].append(0.0)
            cmd = _cell_float(row.get(columns[t["cmd"]]) if t["cmd"] < len(columns) else 0)
            remb = _cell_float(row.get(columns[t["remb"]]) if t["remb"] < len(columns) else 0)
            solde = _cell_float(row.get(columns[t["solde"]]) if t["solde"] < len(columns) else 0)
            clients_data[ci]["commandes"][di] = cmd
            clients_data[ci]["remboursements"][di] = remb
            clients_data[ci]["soldes"][di] = solde

    if not dates_order:
        return None
    return {"title": grid.get("title") or "Import clientèle (grille)", "dates": dates_order, "clients": clients_data}


def import_clientele_board(
    db: Session,
    contents: bytes,
    filename: str = "",
    sheet_name: str | int = 0,
    grid: dict | None = None,
) -> dict:
    return import_clientele_flexible(
        db,
        contents=contents,
        filename=filename,
        grid=grid,
        sheet_name=sheet_name,
    )


def import_clientele_all_sheets(
    db: Session,
    contents: bytes,
    filename: str = "",
    *,
    mode: str = "merge",
    auto_commit: bool = True,
) -> dict:
    """Importe toutes les feuilles reconnues comme tableaux clientèle PC."""
    sheets = list_clientele_sheets(contents, filename=filename)
    if not sheets:
        return {
            "ok": False,
            "format": "clientele_pc",
            "imported": 0,
            "total": 0,
            "clients_imported": 0,
            "errors": ["Aucune feuille clientèle PC détectée dans ce classeur."],
            "message": "Aucune feuille clientèle PC détectée.",
        }

    imported_clients = 0
    imported_entries = 0
    errors: list[str] = []

    for i, sheet in enumerate(sheets):
        parsed = try_parse_clientele_board(contents, sheet_name=sheet, filename=filename)
        if not parsed or not parsed.get("clients"):
            continue
        sheet_mode = "replace" if mode == "replace" and i == 0 else "merge"
        result = import_clientele_board_data(
            db,
            build_board_from_parsed(parsed),
            filename,
            mode=sheet_mode,
            auto_commit=False,
        )
        if not result.get("ok"):
            errors.extend(result.get("errors") or [result.get("message") or f"Échec feuille {sheet}"])
            continue
        imported_clients += int(result.get("clients_imported") or 0)
        imported_entries += int(result.get("imported") or 0)

    if imported_clients == 0 and imported_entries == 0:
        db.rollback()
        return {
            "ok": False,
            "format": "clientele_pc",
            "imported": 0,
            "total": 0,
            "clients_imported": 0,
            "errors": errors or ["Aucune donnée importée."],
            "message": "Aucune donnée clientèle enregistrée.",
        }

    if auto_commit:
        db.commit()

    return {
        "ok": True,
        "format": "clientele_pc",
        "imported": imported_entries,
        "total": imported_entries,
        "clients_imported": imported_clients,
        "errors": errors,
        "sheets_imported": sheets,
        "message": (
            f"{len(sheets)} feuille(s) · {imported_clients} client(s) · "
            f"{imported_entries} mouvement(s) importé(s)"
        ),
    }
