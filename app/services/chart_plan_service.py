"""Plan comptable SYSCOHADA — vue d'ensemble, arbre, recherche, fiche compte."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Account
from app.models_erp import JournalLine, JournalEntry
from app.syscohada.chart import SYSCOHADA_CHART
from app.syscohada.constants import ACCOUNT_CLASSES
from app.services.accounting_reports import balance_generale, grand_livre


def _official_codes() -> set[str]:
    return {a["code"] for a in SYSCOHADA_CHART}


def chart_overview(db: Session, fiscal_year: int | None = None) -> dict:
    """Statistiques plan officiel vs base + répartition par classe."""
    official = _official_codes()
    rows = db.query(Account).all()
    db_codes = {r.code for r in rows}
    missing = sorted(official - db_codes)
    extra = sorted(db_codes - official)

    used_q = db.query(JournalLine.account_code).join(
        JournalEntry, JournalLine.entry_id == JournalEntry.id
    ).filter(JournalEntry.status == "validée").distinct()
    used_codes = {r[0] for r in used_q.all() if r[0]}

    by_class: dict[str, dict] = {}
    for cls in ACCOUNT_CLASSES:
        code = cls["code"]
        cls_accounts = [r for r in rows if (r.class_code or (r.code[0] if r.code else "")) == code]
        by_class[code] = {
            "code": code,
            "label": cls["label"],
            "kind": cls["kind"],
            "description": cls.get("description", ""),
            "total": len(cls_accounts),
            "official": len([a for a in SYSCOHADA_CHART if a["class_code"] == code]),
            "used": len([a for a in cls_accounts if a.code in used_codes]),
            "auxiliary": len([a for a in cls_accounts if a.code not in official]),
        }

    balance = balance_generale(db, fiscal_year=fiscal_year) if fiscal_year else balance_generale(db)
    with_balance = sum(1 for b in balance if abs(b.get("balance", 0) or 0) >= 0.01)

    return {
        "official_total": len(official),
        "db_total": len(rows),
        "coverage_pct": round((len(official & db_codes) / max(len(official), 1)) * 100, 1),
        "missing_count": len(missing),
        "missing_sample": missing[:20],
        "extra_count": len(extra),
        "extra_sample": extra[:30],
        "auxiliary_count": len(extra),
        "used_count": len(used_codes & db_codes),
        "with_balance_count": with_balance,
        "classes": list(by_class.values()),
        "complete": len(missing) == 0,
    }


def search_accounts(
    db: Session,
    *,
    q: str = "",
    class_code: str | None = None,
    account_type: str | None = None,
    used_only: bool = False,
    with_balance: bool = False,
    fiscal_year: int | None = None,
    limit: int = 80,
    offset: int = 0,
) -> dict:
    """Recherche paginée dans le plan comptable."""
    query = db.query(Account)
    if class_code:
        query = query.filter(Account.class_code == class_code)
    if account_type:
        query = query.filter(Account.type == account_type)
    if q:
        raw = q.strip()
        if raw.isdigit():
            query = query.filter(Account.code.like(f"{raw}%"))
        else:
            like = f"%{raw}%"
            query = query.filter(
                (Account.code.like(like)) | (Account.label.ilike(like))
            )

    used_codes: set[str] = set()
    if used_only:
        used_codes = {
            r[0] for r in db.query(JournalLine.account_code).join(
                JournalEntry, JournalLine.entry_id == JournalEntry.id
            ).filter(JournalEntry.status == "validée").distinct().all() if r[0]
        }
        if used_codes:
            query = query.filter(Account.code.in_(used_codes))
        else:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

    balance_map: dict[str, float] = {}
    if with_balance:
        for row in balance_generale(db, fiscal_year=fiscal_year):
            if abs(row.get("balance", 0) or 0) >= 0.01:
                balance_map[row["account_code"]] = row["balance"]
        codes_bal = list(balance_map.keys())
        if codes_bal:
            query = query.filter(Account.code.in_(codes_bal))
        else:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

    total = query.count()
    accounts = query.order_by(Account.code).offset(offset).limit(min(limit, 200)).all()

    if not used_codes and (used_only is False):
        used_codes = {
            r[0] for r in db.query(JournalLine.account_code).filter(
                JournalLine.account_code.in_([a.code for a in accounts])
            ).distinct().all() if r[0]
        }
    if not balance_map and with_balance is False:
        for row in balance_generale(db, fiscal_year=fiscal_year):
            balance_map[row["account_code"]] = row.get("balance", 0)

    items = [
        _account_row(a, used=a.code in used_codes, balance=balance_map.get(a.code, 0))
        for a in accounts
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def build_class_tree(db: Session, class_code: str, fiscal_year: int | None = None) -> list[dict]:
    """Arbre hiérarchique pour une classe SYSCOHADA."""
    accounts = db.query(Account).filter(Account.class_code == class_code).order_by(Account.code).all()
    if not accounts:
        accounts = db.query(Account).filter(Account.code.like(f"{class_code}%")).order_by(Account.code).all()

    balance_map = {r["account_code"]: r.get("balance", 0) for r in balance_generale(db, fiscal_year=fiscal_year)}
    used_codes = {
        r[0] for r in db.query(JournalLine.account_code).join(
            JournalEntry, JournalLine.entry_id == JournalEntry.id
        ).filter(JournalEntry.status == "validée").distinct().all() if r[0]
    }

    nodes = {
        a.code: {
            **_account_row(a, used=a.code in used_codes, balance=balance_map.get(a.code, 0)),
            "children": [],
        }
        for a in accounts
    }
    roots: list[dict] = []
    attached: set[str] = set()

    for a in accounts:
        node = nodes[a.code]
        parent_code = (a.parent_code or "").strip()
        parent = parent_code if parent_code in nodes else None
        if not parent:
            for plen in range(len(a.code) - 1, 0, -1):
                prefix = a.code[:plen]
                if prefix in nodes:
                    parent = prefix
                    break
        if parent:
            nodes[parent]["children"].append(node)
            attached.add(a.code)
        else:
            roots.append(node)
            attached.add(a.code)

    for code, node in nodes.items():
        if code not in attached:
            roots.append(node)

    return sorted(roots, key=lambda x: x["code"])


def account_detail(db: Session, code: str, fiscal_year: int | None = None) -> dict:
    """Fiche compte — métadonnées, solde, mouvements récents, enfants."""
    acc = db.query(Account).filter(Account.code == code).first()
    if not acc:
        raise ValueError(f"Compte {code} introuvable")

    official = _official_codes()
    children = db.query(Account).filter(Account.parent_code == code).order_by(Account.code).limit(50).all()
    if not children:
        children = [
            c for c in db.query(Account).filter(Account.code.like(f"{code}%"), Account.code != code).order_by(Account.code).limit(40).all()
            if (c.parent_code or "") == code
        ]

    balance_rows = [r for r in balance_generale(db, fiscal_year=fiscal_year) if r["account_code"] == code]
    bal = balance_rows[0] if balance_rows else {"debit": 0, "credit": 0, "balance": 0}

    movements = grand_livre(db, account_code=code)[-15:]

    mv_count = db.query(func.count(JournalLine.id)).join(
        JournalEntry, JournalLine.entry_id == JournalEntry.id
    ).filter(JournalLine.account_code == code, JournalEntry.status == "validée").scalar() or 0

    return {
        "account": _account_row(acc, used=mv_count > 0, balance=bal.get("balance", 0)),
        "is_official": code in official,
        "is_auxiliary": code not in official,
        "debit": bal.get("debit", 0),
        "credit": bal.get("credit", 0),
        "balance": bal.get("balance", 0),
        "movements_count": mv_count,
        "movements": movements,
        "children": [_account_row(c) for c in children[:20]],
        "children_count": len(children),
    }


def export_chart_csv(db: Session) -> str:
    """Export CSV du plan en base."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["code", "label", "type", "class_code", "parent_code", "level", "official"])
    official = _official_codes()
    for a in db.query(Account).order_by(Account.code).all():
        w.writerow([
            a.code, a.label, a.type,
            a.class_code or "", a.parent_code or "", a.level or "",
            "oui" if a.code in official else "auxiliaire",
        ])
    return buf.getvalue()


def _account_row(acc: Account, *, used: bool = False, balance: float = 0) -> dict:
    return {
        "id": acc.id,
        "code": acc.code,
        "label": acc.label,
        "type": acc.type,
        "class_code": acc.class_code or (acc.code[0] if acc.code else ""),
        "parent_code": acc.parent_code or "",
        "level": acc.level or len(acc.code or ""),
        "used": used,
        "balance": round(balance or 0, 2),
    }
