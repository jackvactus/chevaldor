"""Import Excel avancé, historique, pièces jointes / images."""
import json
import re
import shutil
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_permission
from app.permissions import has_module_action
from app.upload_limits import (
    IMAGE_EXT,
    IMAGE_MIMES,
    MAX_UPLOAD_BYTES,
    SPREADSHEET_EXT,
    assert_extension,
    read_bounded,
)
from app.database import get_db
from app.excel_clientele import analyze_clientele, parse_clientele_board
from app.import_service import (
    import_clientele_board,
    import_clientele_board_data,
    import_clientele_all_sheets,
    import_clientele_flexible,
    import_clientele_from_grid,
)
from app.import_smart import build_smart_mapping, resolve_import_strategy
from app.excel_mapper import (
    build_invoice_import_fields,
    build_quote_import_fields,
    compose_transaction_label,
    map_columns,
    resolve_client_id,
    row_get,
)
from app.excel_smart import analyze_workbook
from app.excel_utils import _excel_date, _excel_float, _excel_int, _excel_str, _sample_rows, load_spreadsheet
from app.models import Attachment, Client, ImportBatch, User
from app.services.notify import create_app_notification
from app.tenant_service import get_company_id, stamp_company

router = APIRouter(prefix="/api/data", tags=["data"])

from app.paths import data_root, uploads_root, clientele_dossiers_root

UPLOAD_ROOT = uploads_root()

class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    sheet_type: str
    status: str
    rows_total: int
    rows_ok: int
    errors_json: str
    created_at: Optional[date] = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    mime_type: str
    size_bytes: int
    entity_type: str
    entity_id: Optional[int] = None
    import_batch_id: Optional[int] = None
    uploaded_by: Optional[int] = None
    uploaded_by_name: str = ""
    created_at: Optional[date] = None
    status: str = "disponible"
    file_type: str = ""
    url: str = ""
    previewable: bool = False


def _file_type_label(filename: str, mime: str) -> str:
    ext = Path(filename or "").suffix.lower()
    mapping = {
        ".pdf": "PDF",
        ".xlsx": "Excel",
        ".xls": "Excel",
        ".csv": "CSV",
        ".doc": "Word",
        ".docx": "Word",
        ".png": "Image",
        ".jpg": "Image",
        ".jpeg": "Image",
        ".webp": "Image",
        ".gif": "Image",
    }
    if ext in mapping:
        return mapping[ext]
    if mime.startswith("image/"):
        return "Image"
    if "sheet" in mime or "excel" in mime:
        return "Excel"
    if "pdf" in mime:
        return "PDF"
    return (ext.replace(".", "") or "Fichier").upper()


def _attachment_out(att: Attachment, db: Session) -> AttachmentOut:
    uploader = ""
    if att.uploaded_by:
        u = db.query(User).filter(User.id == att.uploaded_by).first()
        if u:
            uploader = u.full_name or u.email or str(u.id)
    mime = att.mime_type or ""
    previewable = mime.startswith("image/") or mime == "application/pdf" or (att.filename or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"))
    return AttachmentOut(
        id=att.id,
        filename=att.filename,
        mime_type=mime,
        size_bytes=att.size_bytes or 0,
        entity_type=att.entity_type,
        entity_id=att.entity_id,
        import_batch_id=att.import_batch_id,
        uploaded_by=att.uploaded_by,
        uploaded_by_name=uploader,
        created_at=att.created_at,
        status="disponible",
        file_type=_file_type_label(att.filename, mime),
        url=f"/api/data/attachments/{att.id}/file",
        previewable=previewable,
    )


_SAFE_SUBDIR_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _safe_subdir(raw: str, default: str = "misc") -> str:
    """Restreint le sous-dossier d'upload à un nom simple (liste blanche par motif) —
    empêche toute traversée de chemin via un champ de formulaire libre (entity_type…)."""
    raw = (raw or "").strip()
    return raw if _SAFE_SUBDIR_RE.match(raw) else default


async def _save_upload(file: UploadFile, subdir: str, *, allowed_ext: set[str] | None = None) -> tuple[str, str, int]:
    if allowed_ext:
        assert_extension(file.filename, allowed_ext)
    body = await read_bounded(file, MAX_UPLOAD_BYTES)
    ext = Path(file.filename or "file").suffix.lower()
    stored = f"{uuid.uuid4().hex}{ext}"
    dest_dir = (UPLOAD_ROOT / _safe_subdir(subdir)).resolve()
    if UPLOAD_ROOT.resolve() not in dest_dir.parents and dest_dir != UPLOAD_ROOT.resolve():
        raise HTTPException(400, "Dossier de destination invalide")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored
    dest.write_bytes(body)
    mime = file.content_type or "application/octet-stream"
    if allowed_ext == IMAGE_EXT and mime not in IMAGE_MIMES:
        raise HTTPException(400, "Type MIME image non autorisé")
    return str(dest.relative_to(data_root())), mime, len(body)


@router.get("/imports/{batch_id}")
def get_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("data.import")),
):
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(404, "Import introuvable")
    try:
        parsed = json.loads(batch.errors_json or "[]")
    except Exception:
        parsed = []
    if isinstance(parsed, dict):
        plain_errors = parsed.get("errors", [])
        rejected = parsed.get("rejected_rows", [])
    else:
        plain_errors = [e for e in parsed if isinstance(e, str)]
        rejected = [e for e in parsed if isinstance(e, dict)]
    return {
        "id": batch.id,
        "filename": batch.filename,
        "sheet_type": batch.sheet_type,
        "status": batch.status,
        "rows_total": batch.rows_total,
        "rows_ok": batch.rows_ok,
        "rows_rejected": batch.rows_total - batch.rows_ok if batch.rows_total else 0,
        "errors": plain_errors,
        "rejected_rows": rejected,
        "created_at": batch.created_at,
    }


@router.get("/imports", response_model=List[ImportBatchOut])
def list_imports(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("data.import")),
):
    return db.query(ImportBatch).order_by(ImportBatch.id.desc()).limit(50).all()


@router.post("/imports/analyze")
async def analyze_import_file(
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    header_row: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("data.import")),
):
    assert_extension(file.filename, SPREADSHEET_EXT)
    contents = await read_bounded(file)
    try:
        hdr = int(header_row) if header_row is not None else None
        return analyze_workbook(
            contents,
            file.filename or "",
            sheet_name=sheet_name,
            header_row=hdr,
        )
    except Exception as e:
        return {"ok": False, "message": f"Erreur lors de l'analyse : {str(e)}"}


@router.post("/imports/preview")
async def preview_import(
    file: UploadFile = File(...),
    sheet_type: str = Form("clients"),
    mapping_json: Optional[str] = Form(None),
    grid_json: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    header_row: Optional[int] = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("data.import")),
):
    company_id = get_company_id(db, user)
    assert_extension(file.filename, SPREADSHEET_EXT)
    contents = await read_bounded(file)
    custom_map = {}
    if mapping_json:
        try:
            custom_map = json.loads(mapping_json)
        except Exception:
            raise HTTPException(400, "mapping_json invalide (JSON attendu)")
    grid = None
    if grid_json:
        try:
            grid = json.loads(grid_json)
        except Exception:
            raise HTTPException(400, "grid_json invalide")
    sheet_ref = sheet_name if sheet_name not in (None, "", "CSV") else 0
    strategy = resolve_import_strategy(
        sheet_type,
        (grid or {}).get("columns") or [],
        matrix_available=False,
        contents=contents,
        filename=file.filename or "",
        custom_map=custom_map or None,
        sheet_name=sheet_ref,
    )
    sheet_type = strategy["sheet_type"]
    custom_map = strategy["column_mapping"]
    auto_hint = strategy.get("reason", "")

    if sheet_type == "clientele_pc":
        if strategy.get("use_file_parse") and contents:
            parsed = analyze_clientele(
                contents,
                sheet_name=sheet_name if sheet_name not in (None, "", "CSV") else 0,
                filename=file.filename or "",
            )
            parsed["message"] = (
                f"Prévisualisation : import clientèle PC ({parsed.get('nb_clients', '?')} clients) — {auto_hint}"
            )
            return parsed
        if grid:
            from app.import_service import build_board_from_flat_grid

            board = build_board_from_flat_grid(grid, custom_map=custom_map)
            total = len(grid.get("rows") or [])
            if board and board.get("clients"):
                nc = len(board["clients"])
                nd = len(board.get("dates") or [])
                return {
                    "ok": True,
                    "imported": nc,
                    "total": total,
                    "errors": [],
                    "rejected_rows": [],
                    "preview_rows": [{"type": "clientele_pc", "clients": nc, "dates": nd}],
                    "message": f"Prévisualisation clientèle : {nc} client(s), {nd} date(s) — {auto_hint}",
                }
        sn = sheet_name if sheet_name not in (None, "", "CSV") else 0
        out = analyze_clientele(contents, sheet_name=sn, filename=file.filename or "")
        out["message"] = (out.get("message") or "Prévisualisation clientèle") + f" — {auto_hint}"
        return out
    if grid and not strategy.get("use_file_parse"):
        truncated = bool(
            grid.get("truncated")
            or (grid.get("total_rows") or 0) > len(grid.get("rows") or [])
        )
        if truncated and contents:
            result = _import_mapped_excel(
                db,
                contents,
                sheet_type,
                file.filename or "",
                custom_map=custom_map,
                dry_run=True,
                sheet_name=sheet_name,
                header_row=int(header_row or 0),
                company_id=company_id,
            )
            if auto_hint:
                result["message"] = f"{result.get('message', '')} ({auto_hint})"
            return result
        result = _import_from_grid(db, grid, sheet_type, custom_map=custom_map, dry_run=True, company_id=company_id)
        if auto_hint:
            result["message"] = f"{result.get('message', '')} ({auto_hint})"
        return result
    return _import_mapped_excel(
        db,
        contents,
        sheet_type,
        file.filename or "",
        custom_map=custom_map,
        dry_run=True,
        sheet_name=sheet_name,
        header_row=int(header_row or 0),
        company_id=company_id,
    )


@router.post("/imports/run")
async def run_import(
    file: UploadFile = File(...),
    sheet_type: str = Form("clients"),
    mapping_json: Optional[str] = Form(None),
    board_json: Optional[str] = Form(None),
    grid_json: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    header_row: Optional[int] = Form(0),
    dry_run: bool = Form(False),
    mode: str = Form("merge"),
    all_sheets: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("data.import")),
):
    company_id = get_company_id(db, user)
    assert_extension(file.filename, SPREADSHEET_EXT)
    contents = await read_bounded(file)
    batch = ImportBatch(
        filename=file.filename or "import.xlsx",
        sheet_type=sheet_type,
        status="processing",
        user_id=user.id,
        created_at=date.today(),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    # Sauvegarder copie du fichier source — nom de fichier physique généré,
    # jamais dérivé de file.filename (traversée de chemin sinon possible).
    safe_ext = Path(file.filename or "import.xlsx").suffix.lower()
    if safe_ext not in SPREADSHEET_EXT:
        safe_ext = ".xlsx"
    subpath = f"imports/{batch.id}_{uuid.uuid4().hex}{safe_ext}"
    dest = data_root() / "uploads" / subpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(contents)
    att = Attachment(
        filename=file.filename or "source.xlsx",
        stored_path=f"uploads/{subpath}",
        mime_type=file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=len(contents),
        entity_type="import_batch",
        entity_id=batch.id,
        import_batch_id=batch.id,
        uploaded_by=user.id,
        created_at=date.today(),
    )
    db.add(att)

    auto_note: Optional[str] = None
    try:
        custom_map = {}
        if mapping_json:
            try:
                custom_map = json.loads(mapping_json)
            except Exception:
                raise HTTPException(400, "mapping_json invalide (JSON attendu)")

        grid_data = None
        if grid_json:
            try:
                grid_data = json.loads(grid_json)
            except Exception:
                raise HTTPException(400, "grid_json invalide (JSON attendu)")

        cols = (grid_data or {}).get("columns") or []
        matrix_avail = bool(board_json)
        sheet_ref = sheet_name if sheet_name not in (None, "", "CSV") else 0
        strategy = resolve_import_strategy(
            sheet_type,
            cols,
            matrix_available=matrix_avail,
            contents=contents,
            filename=file.filename or "",
            custom_map=custom_map or None,
            sheet_name=sheet_ref,
        )
        sheet_type = strategy["sheet_type"]
        custom_map = strategy["column_mapping"]
        auto_note = strategy.get("reason")
        batch.sheet_type = sheet_type

        if sheet_type == "clientele_pc":
            board = None
            if board_json:
                try:
                    board = json.loads(board_json)
                except Exception:
                    raise HTTPException(400, "board_json invalide (JSON attendu)")
            if all_sheets and contents:
                result = import_clientele_all_sheets(
                    db,
                    contents,
                    file.filename or "",
                    mode=mode if mode in ("merge", "replace") else "merge",
                    auto_commit=False,
                )
            else:
                result = import_clientele_flexible(
                    db,
                    contents=contents,
                    filename=file.filename or "",
                    grid=grid_data,
                    board=board,
                    custom_map=custom_map,
                    sheet_name=sheet_ref,
                    mode=mode if mode in ("merge", "replace") else "merge",
                    auto_commit=False,
                )
            if not result.get("ok"):
                profile = strategy.get("profile") or {}
                fallback = strategy.get("recommended_type") or "clients"
                if profile.get("accounting_ledger") or profile.get("government_ledger"):
                    fallback = "transactions"
                if fallback == "clientele_pc":
                    fallback = "transactions" if profile.get("accounting_ledger") else "clients"
                fb_map = build_smart_mapping(cols, fallback) if cols else custom_map
                if fallback != "clientele_pc" and contents:
                    batch.sheet_type = fallback
                    sheet_type = fallback
                    result = _import_mapped_excel(
                        db,
                        contents,
                        fallback,
                        file.filename or "",
                        custom_map=fb_map,
                        dry_run=dry_run,
                        sheet_name=sheet_name,
                        header_row=int(header_row or 0),
                        company_id=company_id,
                    )
                    auto_note = (
                        f"Repli automatique en import « {fallback} » "
                        f"({result.get('message', '')})"
                    )
        elif grid_data and not strategy.get("use_file_parse"):
            truncated = bool(
                grid_data.get("truncated")
                or (grid_data.get("total_rows") or 0) > len(grid_data.get("rows") or [])
            )
            if truncated and contents:
                result = _import_mapped_excel(
                    db,
                    contents,
                    sheet_type,
                    file.filename or "",
                    custom_map=custom_map,
                    dry_run=dry_run,
                    sheet_name=sheet_name,
                    header_row=int(header_row or 0),
                    company_id=company_id,
                )
                auto_note = (
                    f"Import complet depuis le fichier ({grid_data.get('total_rows')} lignes). "
                    "La grille n’affiche qu’un extrait."
                )
            else:
                result = _import_from_grid(
                    db, grid_data, sheet_type, custom_map=custom_map, dry_run=dry_run, company_id=company_id,
                )
        else:
            result = _import_mapped_excel(
                db,
                contents,
                sheet_type,
                file.filename or "",
                custom_map=custom_map,
                dry_run=dry_run,
                sheet_name=sheet_name,
                header_row=int(header_row or 0),
                company_id=company_id,
            )
        batch.status = "done" if result.get("ok") else "error"
        batch.rows_total = result.get("total", 0)
        batch.rows_ok = result.get("imported", 0)
        batch.errors_json = json.dumps(
            {
                "errors": result.get("errors", [])[:200],
                "rejected_rows": result.get("rejected_rows", [])[:200],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        from app.database import ensure_session_active
        ensure_session_active(db)
        batch = db.get(ImportBatch, batch.id) or batch
        batch.status = "error"
        batch.errors_json = json.dumps({"errors": [str(e)], "rejected_rows": []})
        result = {"ok": False, "message": str(e)}
    from app.database import ensure_session_active
    ensure_session_active(db)
    batch = db.get(ImportBatch, batch.id) or batch
    if not db.query(Attachment).filter(Attachment.import_batch_id == batch.id).first():
        db.add(att)
    create_app_notification(
        db,
        user_id=user.id,
        type_="success" if result.get("ok") else "warn",
        title=f"Import {batch.filename}",
        message=result.get("message", "Import terminé"),
        category="import",
    )
    db.commit()
    result["batch_id"] = batch.id
    if auto_note and result.get("ok"):
        prev = result.get("message") or ""
        result["message"] = f"{prev} ({auto_note})" if prev else auto_note
    result["resolved_sheet_type"] = sheet_type
    return result


def _import_invoice_row(
    db: Session,
    row,
    col_map,
    *,
    dry_run: bool,
    pending_rows: list,
    line_no: int,
    company_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """Import ou mise à jour d'une facture (upsert par numéro)."""
    from app.models import Invoice

    fields, err = build_invoice_import_fields(db, row, col_map, dry_run=dry_run, company_id=company_id)
    if err:
        return False, err
    client_label = _excel_str(row_get(row, col_map, "client_name"))
    if dry_run:
        pending_rows.append({
            "row": line_no,
            "type": "invoices",
            "number": fields["number"],
            "amount": fields.get("amount"),
            "client": client_label,
        })
        return True, None
    existing = db.query(Invoice).filter(Invoice.number == fields["number"]).first()
    if existing:
        for key, val in fields.items():
            if key == "number":
                continue
            setattr(existing, key, val)
    else:
        obj = Invoice(**fields)
        stamp_company(obj, company_id)
        db.add(obj)
    return True, None


def _import_quote_row(
    db: Session,
    row,
    col_map,
    *,
    dry_run: bool,
    pending_rows: list,
    line_no: int,
    company_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """Import ou mise à jour d'un devis (upsert par numéro) — même logique que les factures."""
    from app.models import Quote

    fields, err = build_quote_import_fields(db, row, col_map, dry_run=dry_run, company_id=company_id)
    if err:
        return False, err
    client_label = _excel_str(row_get(row, col_map, "client_name"))
    if dry_run:
        pending_rows.append({
            "row": line_no,
            "type": "quotes",
            "number": fields["number"],
            "amount": fields.get("amount"),
            "client": client_label,
        })
        return True, None
    existing = db.query(Quote).filter(Quote.number == fields["number"]).first()
    if existing:
        for key, val in fields.items():
            if key == "number":
                continue
            setattr(existing, key, val)
    else:
        obj = Quote(**fields)
        stamp_company(obj, company_id)
        db.add(obj)
    return True, None


_RECURRING_FREQ_REVERSE = {
    "journaliere": "daily", "journalière": "daily", "daily": "daily",
    "hebdomadaire": "weekly", "hebdo": "weekly", "weekly": "weekly",
    "mensuelle": "monthly", "mensuel": "monthly", "monthly": "monthly",
    "trimestrielle": "quarterly", "quarterly": "quarterly",
    "annuelle": "yearly", "annuel": "yearly", "yearly": "yearly",
}


def _recurring_frequency_from(raw, default: str) -> str:
    key = str(raw or "").strip().lower()
    if key in _RECURRING_FREQ_REVERSE:
        return _RECURRING_FREQ_REVERSE[key]
    return key if key in _RECURRING_FREQ_REVERSE.values() else default


def _recurring_date_or(raw, default):
    try:
        val = _excel_date(raw)
    except Exception:
        return default
    return val if val is not None else default


def _import_recurring_row(
    db: Session,
    row,
    col_map,
    *,
    dry_run: bool,
    pending_rows: list,
    line_no: int,
    company_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """Import ou mise à jour d'un plan de facturation récurrente — upsert par ID
    (colonne « id », alias de « recurring_id »), sinon par client + libellé — pour
    ré-importer un export (`excel_export.export_recurring`) édité sans dupliquer."""
    from app.models_business_ext import InvoiceRecurring

    label = row_get(row, col_map, "label")
    try:
        if pd.isna(label):
            label = None
    except (TypeError, ValueError):
        pass

    # resolve_client_id vérifie désormais que l'ID existe encore (un "code_client" exporté
    # est figé au moment de l'export et peut être périmé si le client a été supprimé depuis)
    # et retombe sur une résolution par nom le cas échéant.
    client_id = resolve_client_id(db, row, col_map)
    if not client_id:
        client_label = _excel_str(row_get(row, col_map, "client_name"))
        code = _excel_str(row_get(row, col_map, "client_id"))
        detail = f"{client_label or '—'}" + (f" / code {code}" if code else "")
        return False, f"Client introuvable ({detail}) — a peut-être été supprimé depuis l'export"

    existing = None
    raw_id = row_get(row, col_map, "recurring_id")
    if raw_id is not None:
        try:
            if not (hasattr(raw_id, "__float__") and pd.isna(raw_id)):
                rid = int(float(raw_id))
                if rid > 0:
                    existing = db.query(InvoiceRecurring).filter(InvoiceRecurring.id == rid).first()
        except (TypeError, ValueError):
            existing = None
    if not existing and label:
        existing = (
            db.query(InvoiceRecurring)
            .filter(InvoiceRecurring.client_id == client_id, InvoiceRecurring.label == _excel_str(label))
            .first()
        )

    status_raw = _excel_str(row_get(row, col_map, "status")).strip().lower()
    if status_raw:
        active = status_raw not in ("suspendu", "suspendue", "suspended", "inactif", "0", "false", "non")
    else:
        active = bool(existing.active) if existing else True

    values = {
        "client_id": client_id,
        "label": _excel_str(label, existing.label if existing else ""),
        "frequency": _recurring_frequency_from(
            row_get(row, col_map, "frequency"), existing.frequency if existing else "monthly"
        ),
        "amount": _excel_float(row_get(row, col_map, "amount"), existing.amount if existing else 0.0),
        "next_date": _recurring_date_or(row_get(row, col_map, "next_date"), existing.next_date if existing else None),
        "end_date": _recurring_date_or(row_get(row, col_map, "end_date"), existing.end_date if existing else None),
        "active": 1 if active else 0,
        "notes": _excel_str(row_get(row, col_map, "notes"), existing.notes if existing else ""),
    }

    if dry_run:
        pending_rows.append({
            "row": line_no, "type": "recurring", "label": values["label"],
            "action": "update" if existing else "create",
        })
        return True, None

    if existing:
        for k, v in values.items():
            setattr(existing, k, v)
    else:
        obj = InvoiceRecurring(**values)
        db.add(obj)
    return True, None


def _import_client_row(
    db: Session,
    row,
    col_map,
    *,
    dry_run: bool,
    pending_rows: list,
    line_no: int,
    company_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """Import ou mise à jour d'un client — upsert par ID (colonne « ID client ») puis par
    nom (exact/normalisé, via resolve_client_id), pour pouvoir ré-importer un export édité
    sans dupliquer chaque client à chaque fois."""
    name = row_get(row, col_map, "name") or row_get(row, col_map, "client_name")
    try:
        if pd.isna(name):
            name = None
    except (TypeError, ValueError):
        pass
    if name is None or not str(name).strip():
        return False, None

    existing_id = resolve_client_id(db, row, col_map)
    existing = db.query(Client).filter(Client.id == existing_id).first() if existing_id else None

    def field(key, cast, default):
        return cast(row_get(row, col_map, key), default)

    values = {
        "name": _excel_str(name, existing.name if existing else ""),
        "type": field("type", _excel_str, existing.type if existing else "Entreprise"),
        "segment": field("segment", _excel_str, existing.segment if existing else ""),
        "contact": field("contact", _excel_str, existing.contact if existing else ""),
        "email": field("email", _excel_str, existing.email if existing else ""),
        "phone": field("phone", _excel_str, existing.phone if existing else ""),
        "city": field("city", _excel_str, existing.city if existing else ""),
        "status": field("status", _excel_str, existing.status if existing else "prospect"),
        "notes": field("notes", _excel_str, existing.notes if existing else ""),
        "credit_limit": field("credit_limit", _excel_float, existing.credit_limit if existing else 0.0),
        "payment_terms": field("payment_terms", _excel_int, existing.payment_terms if existing else 30),
        "account_code": field("account_code", _excel_str, existing.account_code if existing else ""),
        "default_discount_pct": field("discount_pct", _excel_float, existing.default_discount_pct if existing else 0.0),
        "default_vat_pct": field("vat_rate", _excel_float, existing.default_vat_pct if existing else 0.0),
        "default_commission_pct": field("commission_pct", _excel_float, existing.default_commission_pct if existing else 0.0),
        "default_withholding_pct": field("withholding_pct", _excel_float, existing.default_withholding_pct if existing else 0.0),
    }

    if dry_run:
        pending_rows.append({
            "row": line_no, "type": "clients", "name": values["name"],
            "action": "update" if existing else "create",
        })
        return True, None

    if existing:
        for k, v in values.items():
            setattr(existing, k, v)
    else:
        obj = Client(**values)
        stamp_company(obj, company_id)
        db.add(obj)
    return True, None


def _import_sheet_ref(sheet_name: Optional[str]):
    if sheet_name is None or sheet_name == "" or sheet_name == "CSV":
        return 0
    try:
        return int(sheet_name)
    except ValueError:
        return sheet_name


def _import_required_hint(sheet_type: str) -> str:
    hints = {
        "clients": "associez une colonne à « Nom » (ou « Nom client »)",
        "invoices": "associez une colonne à « Numéro » et idéalement « Nom client » + « Montant »",
        "quotes": "associez une colonne à « Numéro » et idéalement « Nom client » + « Montant »",
        "recurring": "associez une colonne à « Client » (ou « code_client ») et idéalement « Montant » + « Fréquence »",
        "projects": "associez une colonne à « Nom »",
        "transactions": "associez une colonne à « Libellé »",
        "deals": "associez une colonne à « Titre / Objet » ou « Nom »",
        "clientele_pc": "utilisez la vue matricielle ou un fichier tableau clientèle PC",
        "employees": "associez une colonne à « Matricule » ou « Nom » + « Salaire » / « Département »",
    }
    return hints.get(sheet_type, "vérifiez le mapping des colonnes")


def _import_row_empty(row) -> bool:
    if isinstance(row, dict):
        for v in row.values():
            if v is not None and str(v).strip() and str(v).lower() not in ("nan", "none"):
                return False
        return True
    for v in row:
        try:
            if pd.notna(v) and str(v).strip():
                return False
        except Exception:
            pass
    return True


def _grid_row_dict(columns: list, row: list) -> dict:
    out = {}
    for i, col in enumerate(columns):
        if i < len(row):
            out[str(col)] = row[i]
    return out


def _employee_import_fields(row, col_map) -> Optional[dict]:
    mat = row_get(row, col_map, "matricule")
    first = row_get(row, col_map, "firstname")
    last = row_get(row, col_map, "lastname") or row_get(row, col_map, "name")
    mat_ok = mat is not None and not (hasattr(mat, "__float__") and pd.isna(mat)) and str(mat).strip()
    last_ok = last is not None and not (hasattr(last, "__float__") and pd.isna(last)) and str(last).strip()
    if not mat_ok and not last_ok:
        return None
    if not mat_ok:
        mat = f"EMP-{str(last).strip()[:4].upper()}{str(first or '').strip()[:2].upper() or '00'}"
    return {
        "matricule": _excel_str(mat),
        "firstname": _excel_str(first),
        "lastname": _excel_str(last),
        "email": _excel_str(row_get(row, col_map, "email")),
        "phone": _excel_str(row_get(row, col_map, "phone")),
        "department": _excel_str(row_get(row, col_map, "department")),
        "position": _excel_str(row_get(row, col_map, "position")),
        "hire_date": _excel_date(row_get(row, col_map, "hire_date") or row_get(row, col_map, "start_date")),
        "salary_base": _excel_float(row_get(row, col_map, "salary_base")),
        "status": _excel_str(row_get(row, col_map, "status"), "actif"),
        "notes": _excel_str(row_get(row, col_map, "notes")),
    }


def _import_employee_row(
    db: Session,
    row,
    col_map,
    *,
    dry_run: bool,
    pending_rows: list,
    line_no: int,
) -> bool:
    from app.models_erp import Employee

    fields = _employee_import_fields(row, col_map)
    if not fields:
        return False
    label = f"{fields['firstname']} {fields['lastname']}".strip() or fields["matricule"]
    if dry_run:
        pending_rows.append({"row": line_no, "type": "employees", "matricule": fields["matricule"], "name": label})
        return True
    existing = db.query(Employee).filter(Employee.matricule == fields["matricule"]).first()
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        db.add(Employee(**fields))
    return True


def _import_journal_entries_from_rows(
    db: Session,
    columns: list,
    rows: list,
    col_map: dict,
    *,
    dry_run: bool = False,
    company_id: Optional[int] = None,
    header_row: int = 0,
) -> dict:
    """Importe un journal SYSCOHADA (lignes groupées par date + référence + journal)."""
    from datetime import date as date_cls
    from app.models_erp import JournalEntry, JournalLine
    from app.excel_mapper import resolve_or_create_client_id
    from app.services.accounting_reports import validate_entry_balance

    groups: dict[tuple, dict] = {}
    errors: list[str] = []
    rejected_rows: list[dict] = []
    pending_rows: list[dict] = []
    excel_row = header_row + 2

    for idx, raw in enumerate(rows):
        line_no = idx + excel_row
        row = _grid_row_dict(columns, raw) if isinstance(raw, list) else raw
        if _import_row_empty(row):
            continue
        account = _excel_str(row_get(row, col_map, "account_code"))
        debit = _excel_float(row_get(row, col_map, "debit"))
        credit = _excel_float(row_get(row, col_map, "credit"))
        # Compat: colonne montant unique + type
        if not debit and not credit:
            amt = _excel_float(row_get(row, col_map, "amount"))
            tx = _excel_str(row_get(row, col_map, "type_tx") or row_get(row, col_map, "type"), "").lower()
            if amt:
                if tx in ("charge", "debit", "débit", "achat"):
                    debit = amt
                else:
                    credit = amt
        if not account:
            errors.append(f"Ligne {line_no}: compte manquant")
            rejected_rows.append({"row": line_no, "error": "compte manquant"})
            continue
        if debit <= 0 and credit <= 0:
            errors.append(f"Ligne {line_no}: montant invalide")
            rejected_rows.append({"row": line_no, "error": "montant invalide"})
            continue
        d = _excel_date(row_get(row, col_map, "date")) or date_cls.today()
        journal = _excel_str(row_get(row, col_map, "journal"), "OD") or "OD"
        reference = _excel_str(row_get(row, col_map, "reference"))
        label = _excel_str(row_get(row, col_map, "label") or compose_transaction_label(row, col_map))
        cid, _cerr = resolve_or_create_client_id(db, row, col_map, dry_run=dry_run, company_id=company_id)
        key = (str(d), journal, reference or f"auto-{idx // 2}")
        bucket = groups.setdefault(key, {
            "date": d,
            "journal": journal,
            "reference": reference,
            "label": label,
            "client_id": cid if cid else None,
            "observation": _excel_str(row_get(row, col_map, "observation") or row_get(row, col_map, "notes")),
            "lines": [],
            "row_nos": [],
        })
        if cid and not bucket["client_id"]:
            bucket["client_id"] = cid
        if label and not bucket["label"]:
            bucket["label"] = label
        bucket["lines"].append({
            "account_code": account,
            "label": label,
            "debit": debit,
            "credit": credit,
            "client_id": cid if cid else None,
        })
        bucket["row_nos"].append(line_no)

    imported = 0
    for key, bucket in groups.items():
        lines = bucket["lines"]
        if not validate_entry_balance(lines):
            msg = f"Pièce {bucket['reference'] or key} non équilibrée (débit ≠ crédit)"
            errors.append(msg)
            for rn in bucket["row_nos"]:
                rejected_rows.append({"row": rn, "error": msg})
            continue
        if dry_run:
            pending_rows.append({
                "type": "journal_entries",
                "date": str(bucket["date"]),
                "journal": bucket["journal"],
                "reference": bucket["reference"],
                "lines": len(lines),
                "client_id": bucket["client_id"],
            })
            imported += 1
            continue
        entry = JournalEntry(
            date=bucket["date"],
            value_date=bucket["date"],
            journal=bucket["journal"],
            reference=bucket["reference"],
            label=bucket["label"] or bucket["reference"] or "Import journal",
            status="brouillon",
            fiscal_year=bucket["date"].year if hasattr(bucket["date"], "year") else date_cls.today().year,
            period=(bucket["date"].month if hasattr(bucket["date"], "month") else 1),
            client_id=bucket["client_id"],
            observation=bucket["observation"],
            source_type="import",
        )
        db.add(entry)
        db.flush()
        for ln in lines:
            db.add(JournalLine(
                entry_id=entry.id,
                account_code=ln["account_code"],
                label=ln["label"],
                debit=ln["debit"],
                credit=ln["credit"],
                client_id=ln.get("client_id") or bucket["client_id"],
            ))
        imported += 1

    total = len(rows)
    if dry_run:
        db.rollback()
        return {
            "ok": True,
            "imported": imported,
            "total": total,
            "errors": errors,
            "rejected_rows": rejected_rows,
            "preview_rows": pending_rows[:50],
            "message": f"Prévisualisation : {imported} pièce(s) valides, {len(rejected_rows)} ligne(s) en erreur",
        }
    db.commit()
    return {
        "ok": True,
        "imported": imported,
        "total": total,
        "errors": errors,
        "rejected_rows": rejected_rows,
        "message": f"{imported} écriture(s) journal importée(s)",
    }


def _import_from_grid(
    db: Session,
    grid: dict,
    sheet_type: str,
    custom_map: Optional[dict] = None,
    dry_run: bool = False,
    company_id: Optional[int] = None,
) -> dict:
    """Import depuis la grille éditée (tout fichier Excel tabulaire)."""
    from app.import_smart import build_smart_mapping
    from app.models import Deal, Invoice, Project, Transaction

    columns = grid.get("columns") or []
    rows = grid.get("rows") or []
    from app.excel_mapper import ensure_import_mapping

    # Alias : journal SYSCOHADA
    if sheet_type in ("journal_entries", "journal", "écritures", "ecritures"):
        sheet_type = "journal_entries"

    col_map = build_smart_mapping(columns, sheet_type if sheet_type != "journal_entries" else "transactions")
    if custom_map:
        col_map.update({str(k): str(v) for k, v in custom_map.items() if v})
    col_map = ensure_import_mapping(columns, col_map, sheet_type if sheet_type != "journal_entries" else "transactions")

    # Si type transactions mais colonnes débit/crédit présentes → journal SYSCOHADA
    has_dc = any(k in col_map for k in ("debit", "credit")) or any(
        __import__("app.excel_mapper", fromlist=["_norm"])._norm(str(c)) in (
            "debit", "credit", "montant_debit", "montant_credit", "debit_amount", "credit_amount"
        )
        for c in columns
    )
    if sheet_type == "journal_entries" or (sheet_type == "transactions" and has_dc):
        return _import_journal_entries_from_rows(
            db, columns, rows, col_map,
            dry_run=dry_run, company_id=company_id,
            header_row=int(grid.get("header_row") or 0),
        )

    imported = 0
    errors: list[str] = []
    rejected_rows: list[dict] = []
    pending_rows: list[dict] = []
    header_row = int(grid.get("header_row") or 0)
    excel_row = header_row + 2

    if sheet_type == "clientele_pc":
        if dry_run:
            board = None
            try:
                from app.import_service import build_board_from_flat_grid

                board = build_board_from_flat_grid(grid, custom_map=custom_map)
            except Exception:
                board = None
            if board and board.get("clients"):
                n_clients = len(board["clients"])
                n_rows = len(board.get("dates") or [])
                return {
                    "ok": True,
                    "imported": n_clients,
                    "total": len(rows),
                    "errors": [],
                    "rejected_rows": [],
                    "preview_rows": [{"type": "clientele_pc", "clients": n_clients, "dates": n_rows}],
                    "message": f"Prévisualisation clientèle : {n_clients} client(s), {n_rows} date(s)",
                }
        return import_clientele_from_grid(
            db,
            grid,
            contents=None,
            filename="",
            custom_map=custom_map,
        )

    for idx, raw in enumerate(rows):
        line_no = idx + excel_row
        row = _grid_row_dict(columns, raw) if isinstance(raw, list) else raw
        if _import_row_empty(row):
            continue
        # SAVEPOINT par ligne : sans ça, une seule ligne en échec (ex. FK invalide) laissait
        # la session dans un état invalide et faisait échouer en cascade TOUTES les lignes
        # suivantes du même lot avec la même erreur recyclée (autoflush SQLAlchemy sur une
        # session déjà en rollback) — confirmé en testant le ré-import d'un export réel sur
        # une copie isolée de la base (client supprimé depuis l'export → 271 lignes suivantes
        # rejetées avec le même message au lieu d'une seule erreur isolée).
        savepoint = db.begin_nested()
        try:
            if sheet_type == "clients":
                ok, err = _import_client_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "invoices":
                ok, err = _import_invoice_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "quotes":
                ok, err = _import_quote_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "recurring":
                ok, err = _import_recurring_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "projects":
                name = row_get(row, col_map, "name")
                if name is None or not str(name).strip():
                    savepoint.commit()
                    continue
                payload = Project(
                    name=_excel_str(name),
                    client_id=resolve_client_id(db, row, col_map),
                    pole=_excel_str(row_get(row, col_map, "pole"), "Consulting"),
                    status=_excel_str(row_get(row, col_map, "status"), "planifié"),
                    progress=_excel_int(row_get(row, col_map, "progress")),
                    budget=_excel_float(row_get(row, col_map, "budget")),
                    billed=_excel_float(row_get(row, col_map, "billed")),
                    start_date=_excel_date(row_get(row, col_map, "start_date")),
                    end_date=_excel_date(row_get(row, col_map, "end_date")),
                    description=_excel_str(row_get(row, col_map, "description")),
                )
                stamp_company(payload, company_id)
                if dry_run:
                    pending_rows.append({"row": line_no, "type": "projects", "name": payload.name})
                else:
                    db.add(payload)
                imported += 1
            elif sheet_type == "transactions":
                label = compose_transaction_label(row, col_map)
                amt = row_get(row, col_map, "amount")
                if amt is None or (hasattr(amt, "__float__") and pd.isna(amt)):
                    savepoint.commit()
                    continue
                payload = Transaction(
                    date=_excel_date(row_get(row, col_map, "date")),
                    label=_excel_str(label),
                    type=_excel_str(row_get(row, col_map, "type_tx") or row_get(row, col_map, "type"), "produit"),
                    category=_excel_str(row_get(row, col_map, "category")),
                    amount=_excel_float(row_get(row, col_map, "amount")),
                    account_code=_excel_str(row_get(row, col_map, "account_code")),
                    payment_method=_excel_str(row_get(row, col_map, "payment_method"), "virement"),
                    reference=_excel_str(row_get(row, col_map, "reference")),
                    notes=_excel_str(row_get(row, col_map, "notes")),
                )
                stamp_company(payload, company_id)
                if dry_run:
                    pending_rows.append({"row": line_no, "type": "transactions", "label": payload.label})
                else:
                    db.add(payload)
                imported += 1
            elif sheet_type == "deals":
                title = row_get(row, col_map, "title") or row_get(row, col_map, "name")
                if title is None or not str(title).strip():
                    savepoint.commit()
                    continue
                payload = Deal(
                    title=_excel_str(title),
                    client_id=resolve_client_id(db, row, col_map),
                    stage=_excel_str(row_get(row, col_map, "stage") or row_get(row, col_map, "status"), "lead"),
                    amount=_excel_float(row_get(row, col_map, "amount")),
                    probability=_excel_int(row_get(row, col_map, "probability"), 20),
                    pole=_excel_str(row_get(row, col_map, "pole"), "Consulting"),
                    close_date=_excel_date(row_get(row, col_map, "close_date")),
                    notes=_excel_str(row_get(row, col_map, "notes")),
                )
                stamp_company(payload, company_id)
                if dry_run:
                    pending_rows.append({"row": line_no, "type": "deals", "title": payload.title})
                else:
                    db.add(payload)
                imported += 1
            elif sheet_type == "employees":
                if _import_employee_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no
                ):
                    imported += 1
            savepoint.commit()
        except Exception as e:
            savepoint.rollback()
            msg = str(e)
            errors.append(f"Ligne {line_no}: {msg}")
            rejected_rows.append({"row": line_no, "error": msg})

    total = len(rows)
    if dry_run:
        db.rollback()
        return {
            "ok": True,
            "imported": imported,
            "total": total,
            "errors": errors,
            "rejected_rows": rejected_rows,
            "preview_rows": pending_rows[:50],
            "message": f"Prévisualisation : {imported} ligne(s) valide(s) sur {total}",
        }
    if imported == 0:
        db.rollback()
        return {
            "ok": False,
            "imported": 0,
            "total": total,
            "errors": errors or [f"Aucune ligne importée — {_import_required_hint(sheet_type)}."],
            "rejected_rows": rejected_rows,
            "message": f"Aucune ligne importée. {_import_required_hint(sheet_type).capitalize()}.",
        }
    db.commit()
    return {
        "ok": True,
        "imported": imported,
        "total": total,
        "errors": errors,
        "rejected_rows": rejected_rows,
        "message": f"{imported}/{total} lignes importées en base",
    }


def _import_mapped_excel(
    db: Session,
    contents: bytes,
    sheet_type: str,
    filename: str = "",
    custom_map: Optional[dict] = None,
    dry_run: bool = False,
    sheet_name: Optional[str] = None,
    header_row: int = 0,
    company_id: Optional[int] = None,
) -> dict:
    from app.models import Deal, Invoice, Project, Transaction

    sheet_ref = _import_sheet_ref(sheet_name)
    df = load_spreadsheet(contents, filename, sheet_name=sheet_ref, header=header_row)
    df = df.dropna(how="all")
    from app.excel_mapper import ensure_import_mapping
    from app.import_smart import build_smart_mapping

    columns = [str(c) for c in df.columns]
    col_map = build_smart_mapping(columns, sheet_type)
    if custom_map:
        col_map.update({str(k): str(v) for k, v in custom_map.items() if v})
    col_map = ensure_import_mapping(columns, col_map, sheet_type)
    imported = 0
    errors = []
    rejected_rows = []
    pending_rows = []

    excel_row = header_row + 2

    for idx, row in df.iterrows():
        line_no = int(idx) + excel_row
        if _import_row_empty(row):
            continue
        # SAVEPOINT par ligne — voir commentaire équivalent dans _import_from_grid.
        savepoint = db.begin_nested()
        try:
            if sheet_type == "clients":
                ok, err = _import_client_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "invoices":
                ok, err = _import_invoice_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "quotes":
                ok, err = _import_quote_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "recurring":
                ok, err = _import_recurring_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no,
                    company_id=company_id,
                )
                if ok:
                    imported += 1
                elif err:
                    errors.append(f"Ligne {line_no}: {err}")
                    rejected_rows.append({"row": line_no, "error": err})
            elif sheet_type == "projects":
                name = row_get(row, col_map, "name")
                if pd.isna(name) or not str(name).strip():
                    continue
                payload = Project(
                    name=_excel_str(name),
                    client_id=resolve_client_id(db, row, col_map),
                    pole=_excel_str(row_get(row, col_map, "pole"), "Consulting"),
                    status=_excel_str(row_get(row, col_map, "status"), "planifié"),
                    progress=_excel_int(row_get(row, col_map, "progress")),
                    budget=_excel_float(row_get(row, col_map, "budget")),
                    billed=_excel_float(row_get(row, col_map, "billed")),
                    start_date=_excel_date(row_get(row, col_map, "start_date")),
                    end_date=_excel_date(row_get(row, col_map, "end_date")),
                    description=_excel_str(row_get(row, col_map, "description")),
                )
                stamp_company(payload, company_id)
                if dry_run:
                    pending_rows.append({"row": line_no, "type": "projects", "name": payload.name})
                else:
                    db.add(payload)
                imported += 1
            elif sheet_type == "transactions":
                label = compose_transaction_label(row, col_map)
                amt = row_get(row, col_map, "amount")
                if amt is None or (hasattr(amt, "__float__") and pd.isna(amt)):
                    savepoint.commit()
                    continue
                payload = Transaction(
                    date=_excel_date(row_get(row, col_map, "date")),
                    label=_excel_str(label),
                    type=_excel_str(row_get(row, col_map, "type_tx") or row_get(row, col_map, "type"), "produit"),
                    category=_excel_str(row_get(row, col_map, "category")),
                    amount=_excel_float(row_get(row, col_map, "amount")),
                    account_code=_excel_str(row_get(row, col_map, "account_code")),
                    payment_method=_excel_str(row_get(row, col_map, "payment_method"), "virement"),
                    reference=_excel_str(row_get(row, col_map, "reference")),
                    notes=_excel_str(row_get(row, col_map, "notes")),
                )
                stamp_company(payload, company_id)
                if dry_run:
                    pending_rows.append({"row": line_no, "type": "transactions", "label": payload.label})
                else:
                    db.add(payload)
                imported += 1
            elif sheet_type == "deals":
                title = row_get(row, col_map, "title") or row_get(row, col_map, "name")
                if pd.isna(title) or not str(title).strip():
                    continue
                payload = Deal(
                    title=_excel_str(title),
                    client_id=resolve_client_id(db, row, col_map),
                    stage=_excel_str(row_get(row, col_map, "stage") or row_get(row, col_map, "status"), "lead"),
                    amount=_excel_float(row_get(row, col_map, "amount")),
                    probability=_excel_int(row_get(row, col_map, "probability"), 20),
                    pole=_excel_str(row_get(row, col_map, "pole"), "Consulting"),
                    close_date=_excel_date(row_get(row, col_map, "close_date")),
                    notes=_excel_str(row_get(row, col_map, "notes")),
                )
                stamp_company(payload, company_id)
                if dry_run:
                    pending_rows.append({"row": line_no, "type": "deals", "title": payload.title})
                else:
                    db.add(payload)
                imported += 1
            elif sheet_type == "employees":
                if _import_employee_row(
                    db, row, col_map, dry_run=dry_run, pending_rows=pending_rows, line_no=line_no
                ):
                    imported += 1
            savepoint.commit()
        except Exception as e:
            savepoint.rollback()
            msg = str(e)
            errors.append(f"Ligne {line_no}: {msg}")
            rejected_rows.append({"row": line_no, "error": msg})

    if dry_run:
        db.rollback()
        return {
            "ok": True,
            "imported": imported,
            "total": len(df),
            "errors": errors,
            "rejected_rows": rejected_rows,
            "preview_rows": pending_rows[:50],
            "message": f"Prévisualisation : {imported} ligne(s) valide(s) sur {len(df)}",
        }

    if imported == 0:
        db.rollback()
        return {
            "ok": False,
            "imported": 0,
            "total": len(df),
            "errors": errors or ["Aucune ligne importée — vérifiez le type de données et le mapping des colonnes."],
            "rejected_rows": rejected_rows,
            "message": f"Aucune ligne importée. {_import_required_hint(sheet_type).capitalize()}.",
        }

    db.commit()
    return {
        "ok": True,
        "imported": imported,
        "total": len(df),
        "errors": errors,
        "rejected_rows": rejected_rows,
        "message": f"{imported}/{len(df)} lignes importées en base",
    }


@router.post("/attachments", response_model=AttachmentOut)
async def upload_attachment(
    file: UploadFile = File(...),
    entity_type: str = Form("client"),
    entity_id: Optional[int] = Form(None),
    import_batch_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("attachments")),
):
    allowed = IMAGE_EXT | SPREADSHEET_EXT | {".pdf", ".doc", ".docx"}
    rel, mime, size = await _save_upload(file, entity_type, allowed_ext=allowed)
    att = Attachment(
        filename=file.filename or "fichier",
        stored_path=rel,
        mime_type=mime,
        size_bytes=size,
        entity_type=entity_type,
        entity_id=entity_id,
        import_batch_id=import_batch_id,
        uploaded_by=user.id,
        created_at=date.today(),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return _attachment_out(att, db)


def _assert_attachment_access(att: Attachment, user: User, db: Session) -> None:
    if user.role == "admin":
        return
    if att.uploaded_by == user.id:
        return
    if has_module_action(user.role, "imports", "view", db):
        return
    raise HTTPException(403, "Accès refusé à ce fichier")


@router.get("/attachments", response_model=List[AttachmentOut])
def list_attachments(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    import_batch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Attachment)
    if user.role != "admin" and not has_module_action(user.role, "imports", "view", db):
        q = q.filter(Attachment.uploaded_by == user.id)
    if entity_type:
        q = q.filter(Attachment.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(Attachment.entity_id == entity_id)
    if import_batch_id is not None:
        q = q.filter(Attachment.import_batch_id == import_batch_id)
    items = q.order_by(Attachment.id.desc()).limit(100).all()
    return [_attachment_out(a, db) for a in items]


@router.get("/attachments/{aid}/file")
def get_attachment_file(
    aid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from fastapi.responses import FileResponse
    att = db.query(Attachment).filter(Attachment.id == aid).first()
    if not att:
        raise HTTPException(404, "Fichier introuvable")
    _assert_attachment_access(att, user, db)
    path = data_root() / att.stored_path
    if not path.exists():
        raise HTTPException(404, "Fichier absent du disque")
    return FileResponse(path, media_type=att.mime_type, filename=att.filename)


@router.delete("/attachments/{aid}")
def delete_attachment(
    aid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    att = db.query(Attachment).filter(Attachment.id == aid).first()
    if not att:
        raise HTTPException(404)
    # Suppression : admin, uploader, ou droit import / clients
    if user.role != "admin" and att.uploaded_by != user.id:
        if not (
            has_module_action(user.role, "imports", "view", db)
            or has_module_action(user.role, "clients", "update", db)
            or has_module_action(user.role, "data.import", "create", db)
        ):
            raise HTTPException(403, "Suppression non autorisée")
    path = data_root() / att.stored_path
    if path.exists():
        path.unlink()
    db.delete(att)
    db.commit()
    return {"ok": True}


# ——— Dossiers clientèle PC (serveur) ———
@router.get("/clientele-dossiers")
def list_clientele_dossiers(
    _: User = Depends(require_permission("data.import")),
):
    """Liste les dossiers disponibles sous data/clientele_dossiers/."""
    root = clientele_dossiers_root()
    dossiers = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        files = []
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in SPREADSHEET_EXT:
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
        dossiers.append({
            "id": d.name,
            "label": d.name.replace("_", " ").replace("-", " ").title(),
            "path": str(d.relative_to(root)),
            "file_count": len(files),
            "files": files,
        })
    # Fichier legacy à la racine data/
    legacy = data_root() / "clientele_pc.xlsx"
    if legacy.exists():
        dossiers.insert(0, {
            "id": "__legacy__",
            "label": "Fichier par défaut (racine)",
            "path": "",
            "file_count": 1,
            "files": [{"name": "clientele_pc.xlsx", "size": legacy.stat().st_size, "modified": legacy.stat().st_mtime}],
        })
    return {"dossiers": dossiers, "root": str(root)}


def _resolve_clientele_dossier_file(dossier_id: str, filename: str) -> Path:
    """Résout en toute sécurité un fichier sous data/clientele_dossiers/.

    Rejette toute tentative de traversée de chemin (`..`, séparateurs, chemins
    absolus) dans `dossier_id`/`filename` — ces deux valeurs viennent d'un champ
    de formulaire librement modifiable par le client. Le nom de dossier doit
    en plus correspondre à un dossier réellement listé par /clientele-dossiers.
    """
    if dossier_id == "__legacy__":
        return data_root() / "clientele_pc.xlsx"

    root = clientele_dossiers_root().resolve()
    if not dossier_id or not filename or "/" in dossier_id or "\\" in dossier_id or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Nom de dossier ou de fichier invalide")
    if dossier_id in (".", "..") or filename in (".", ".."):
        raise HTTPException(400, "Nom de dossier ou de fichier invalide")

    candidate = (root / dossier_id / filename).resolve()
    if root not in candidate.parents:
        raise HTTPException(400, "Chemin de fichier invalide")
    if not (root / dossier_id).is_dir():
        raise HTTPException(404, "Dossier introuvable")
    if candidate.suffix.lower() not in SPREADSHEET_EXT:
        raise HTTPException(400, "Type de fichier non autorisé")
    return candidate


@router.post("/clientele-dossiers/preview")
async def preview_clientele_dossier(
    dossier_id: str = Form(...),
    filename: str = Form(...),
    _: User = Depends(require_permission("data.import")),
):
    """Aperçu matriciel d'un fichier Excel stocké sur le serveur."""
    path = _resolve_clientele_dossier_file(dossier_id, filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Fichier introuvable dans le dossier")
    contents = path.read_bytes()
    from app.excel_clientele import analyze_clientele
    result = analyze_clientele(contents, filename=filename)
    if not result.get("ok", True) and not result.get("board"):
        raise HTTPException(400, result.get("message") or "Format clientèle non reconnu")
    return result


@router.post("/clientele-dossiers/import")
async def import_clientele_dossier(
    dossier_id: str = Form(...),
    filename: str = Form(...),
    mode: str = Form("merge"),
    board_json: Optional[str] = Form(None),
    all_sheets: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("data.import")),
):
    """Importe un fichier Excel depuis un dossier clientèle PC (avec matrice éditée optionnelle)."""
    if board_json:
        from app.import_service import import_clientele_board_data
        try:
            board = json.loads(board_json)
        except json.JSONDecodeError:
            raise HTTPException(400, "board_json invalide")
        return import_clientele_board_data(
            db, board, filename=filename,
            mode=mode if mode in ("merge", "replace") else "merge",
            auto_commit=False,
        )

    path = _resolve_clientele_dossier_file(dossier_id, filename)
    if dossier_id == "__legacy__":
        filename = "clientele_pc.xlsx"
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Fichier introuvable dans le dossier")
    contents = path.read_bytes()
    from app.import_service import import_clientele_all_sheets, import_clientele_flexible
    if all_sheets:
        result = import_clientele_all_sheets(
            db, contents=contents, filename=filename,
            mode=mode if mode in ("merge", "replace") else "merge",
            auto_commit=False,
        )
    else:
        result = import_clientele_flexible(
            db, contents=contents, filename=filename, sheet_name=0,
            mode=mode if mode in ("merge", "replace") else "merge", auto_commit=False,
        )
    from app.database import ensure_session_active
    ensure_session_active(db)
    return result
