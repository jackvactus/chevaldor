"""États comptables : grand livre, balance, bilan simplifié."""
from collections import defaultdict
from sqlalchemy.orm import Session
from app.models_erp import JournalLine, JournalEntry, SupplierInvoice, TreasuryMovement, BankAccount
from app.models import Account, Transaction, Invoice, Client


def grand_livre(db: Session, account_code: str = None):
    q = db.query(JournalLine, JournalEntry).join(
        JournalEntry, JournalLine.entry_id == JournalEntry.id
    ).filter(JournalEntry.status == "validée")
    if account_code:
        q = q.filter(JournalLine.account_code == account_code)
    rows = []
    for line, entry in q.order_by(JournalEntry.date, JournalLine.id).all():
        rows.append({
            "date": str(entry.date) if entry.date else "",
            "journal": entry.journal,
            "reference": entry.reference,
            "account_code": line.account_code,
            "label": line.label or entry.label,
            "debit": line.debit,
            "credit": line.credit,
        })
    return rows


def balance_generale(db: Session, fiscal_year: int = None, period: str = None):
    totals = defaultdict(lambda: {"debit": 0.0, "credit": 0.0, "label": ""})
    accounts = {a.code: a.label for a in db.query(Account).all()}
    q = db.query(JournalLine, JournalEntry).join(
        JournalEntry, JournalLine.entry_id == JournalEntry.id
    ).filter(JournalEntry.status == "validée")
    if fiscal_year:
        q = q.filter(JournalEntry.fiscal_year == fiscal_year)
    if period:
        try:
            q = q.filter(JournalEntry.period == int(period))
        except (TypeError, ValueError):
            pass
    lines = q.all()
    for line, _ in lines:
        totals[line.account_code]["debit"] += line.debit or 0
        totals[line.account_code]["credit"] += line.credit or 0
        totals[line.account_code]["label"] = accounts.get(line.account_code, line.account_code)
    result = []
    for code, t in sorted(totals.items()):
        solde = t["debit"] - t["credit"]
        result.append({
            "account_code": code,
            "label": t["label"],
            "debit": round(t["debit"], 2),
            "credit": round(t["credit"], 2),
            "balance": round(solde, 2),
        })
    return result


def bilan_simplifie(db: Session, fiscal_year: int = None, period: str = None):
    balance = balance_generale(db, fiscal_year=fiscal_year, period=period)
    actif = sum(r["balance"] for r in balance if r["balance"] > 0 and r["account_code"].startswith(("2", "3", "4", "5")))
    passif = sum(-r["balance"] for r in balance if r["balance"] < 0 or r["account_code"].startswith(("1",)))
    from sqlalchemy import func
    creances = db.query(func.coalesce(func.sum(Invoice.amount - Invoice.paid), 0)).filter(
        Invoice.status.in_(["envoyée", "en retard"])
    ).scalar() or 0
    dettes = db.query(func.coalesce(func.sum(SupplierInvoice.amount - SupplierInvoice.paid), 0)).filter(
        SupplierInvoice.status.in_(["validée", "en retard"])
    ).scalar() or 0
    return {
        "actif_comptable": round(actif, 2),
        "passif_comptable": round(passif, 2),
        "creances_clients": float(creances),
        "dettes_fournisseurs": float(dettes),
        "lines": balance,
    }


def _line_amount(val) -> float:
    """Convertit débit/crédit en float (nombre, chaîne FR, vide)."""
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def normalize_journal_lines(raw) -> list[dict]:
    """Normalise les lignes d'écriture — liste ou dict indexé, montants typés."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        keys = list(raw.keys())
        if keys and all(str(k).isdigit() for k in keys):
            raw = [raw[k] for k in sorted(keys, key=lambda x: int(x))]
        elif keys and all(isinstance(v, dict) for v in raw.values()):
            raw = list(raw.values())
        else:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict] = []
    for item in raw:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        out.append({
            "account_code": str(item.get("account_code") or "").strip(),
            "label": str(item.get("label") or ""),
            "debit": _line_amount(item.get("debit")),
            "credit": _line_amount(item.get("credit")),
            "client_id": item.get("client_id"),
        })
    return out


def validate_entry_balance(lines) -> bool:
    norm = normalize_journal_lines(lines)
    if not norm:
        return False
    d = sum(l["debit"] for l in norm)
    c = sum(l["credit"] for l in norm)
    return abs(d - c) < 0.01 and d > 0


def compte_de_resultat(db: Session, fiscal_year: int = None):
    """Compte de résultat simplifié par classe de comptes."""
    balance = balance_generale(db, fiscal_year=fiscal_year)
    produits = sum(r["credit"] - r["debit"] for r in balance if r["account_code"].startswith(("7",)))
    charges = sum(r["debit"] - r["credit"] for r in balance if r["account_code"].startswith(("6",)))
    result = produits - charges
    lines = [
        {"label": "Produits d'exploitation", "amount": round(produits, 2)},
        {"label": "Charges d'exploitation", "amount": round(charges, 2)},
        {"label": "Résultat d'exploitation", "amount": round(result, 2)},
    ]
    t_prod = sum(t.amount or 0 for t in db.query(Transaction).filter(Transaction.type == "produit").all())
    t_chg = sum(t.amount or 0 for t in db.query(Transaction).filter(Transaction.type == "charge").all())
    if not balance:
        lines = [
            {"label": "Produits (transactions)", "amount": round(t_prod, 2)},
            {"label": "Charges (transactions)", "amount": round(t_chg, 2)},
            {"label": "Résultat net", "amount": round(t_prod - t_chg, 2)},
        ]
    return {"lines": lines, "net_result": round(result if balance else t_prod - t_chg, 2)}


def financial_ratios(db: Session):
    """Ratios financiers calculés depuis la base (aucune valeur fictive)."""
    bilan = bilan_simplifie(db)
    creances = float(bilan.get("creances_clients", 0) or 0)
    dettes = float(bilan.get("dettes_fournisseurs", 0) or 0)
    actif = float(bilan.get("actif_comptable", 0) or 0)
    passif = float(bilan.get("passif_comptable", 0) or 0)
    treso = float(sum(b.balance or 0 for b in db.query(BankAccount).all()))
    disponibilites = treso + creances

    if dettes > 0:
        liquidite_ratio = round(disponibilites / dettes, 2)
        liquidite_display = str(liquidite_ratio)
        liquidite_level = (
            "bonne" if liquidite_ratio >= 1.5
            else "moyenne" if liquidite_ratio >= 1.0
            else "tension"
        )
    else:
        liquidite_ratio = None
        liquidite_display = "—"
        liquidite_level = "aucune_dette"

    endettement = round(dettes / actif * 100, 1) if actif > 0 else 0.0
    resultat_net = compte_de_resultat(db).get("net_result", 0) or 0
    rentabilite = round(resultat_net / actif * 100, 1) if actif > 0 else 0.0

    return {
        "liquidite": liquidite_ratio,
        "liquidite_display": liquidite_display,
        "liquidite_level": liquidite_level,
        "endettement_pct": endettement,
        "rentabilite_pct": rentabilite,
        "creances": creances,
        "dettes": dettes,
        "tresorerie": round(treso, 2),
        "disponibilites": round(disponibilites, 2),
        "actif": round(actif, 2),
        "passif": round(passif, 2),
        "resultat_net": round(float(resultat_net), 2),
    }


def balance_auxiliaire_clients(db: Session) -> list:
    """Balance auxiliaire clients — soldes factures / paiements par client."""
    clients = {c.id: c.name for c in db.query(Client).filter(Client.is_archived == False).all()}  # noqa: E712
    totals = {}
    for inv in db.query(Invoice).filter(Invoice.is_archived == False, Invoice.client_id.isnot(None)).all():  # noqa: E712
        cid = inv.client_id
        if cid not in totals:
            totals[cid] = {"client_id": cid, "client_name": clients.get(cid, "—"), "debit": 0.0, "credit": 0.0}
        amt = inv.amount or 0
        paid = inv.paid or 0
        if getattr(inv, "doc_type", "invoice") == "credit_note":
            totals[cid]["credit"] += amt
        else:
            totals[cid]["debit"] += amt
            totals[cid]["credit"] += paid
    result = []
    for cid, t in sorted(totals.items(), key=lambda x: x[1]["client_name"]):
        balance = round(t["debit"] - t["credit"], 2)
        result.append({
            **t,
            "balance": balance,
            "status": "débiteur" if balance > 0 else ("créditeur" if balance < 0 else "soldé"),
        })
    return result


def balance_auxiliaire_suppliers(db: Session) -> list:
    """Balance auxiliaire fournisseurs."""
    from app.models_erp import Supplier, SupplierInvoice

    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    totals = {}
    for inv in db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id.isnot(None)).all():
        sid = inv.supplier_id
        if sid not in totals:
            totals[sid] = {"supplier_id": sid, "supplier_name": suppliers.get(sid, "—"), "debit": 0.0, "credit": 0.0}
        totals[sid]["debit"] += inv.amount or 0
        totals[sid]["credit"] += inv.paid or 0
    result = []
    for sid, t in sorted(totals.items(), key=lambda x: x[1]["supplier_name"]):
        balance = round(t["debit"] - t["credit"], 2)
        result.append({**t, "balance": balance, "status": "créditeur" if balance > 0 else "soldé"})
    return result


def balance_auxiliaire_gl(db: Session, prefix: str = "411") -> list:
    """Balance auxiliaire depuis le grand livre (comptes 411xxx / 401xxx)."""
    from collections import defaultdict
    from app.models import Client
    from app.models_erp import Supplier

    prefix = (prefix or "411").strip()
    totals = defaultdict(lambda: {"debit": 0.0, "credit": 0.0, "label": ""})

    q = db.query(JournalLine, JournalEntry).join(
        JournalEntry, JournalLine.entry_id == JournalEntry.id
    ).filter(JournalEntry.status == "validée", JournalLine.account_code.startswith(prefix))

    for ln, _ in q.all():
        totals[ln.account_code]["debit"] += ln.debit or 0
        totals[ln.account_code]["credit"] += ln.credit or 0

    name_map = {}
    if prefix.startswith("411"):
        for c in db.query(Client).all():
            if getattr(c, "account_code", None):
                name_map[c.account_code] = c.name
    elif prefix.startswith("401"):
        for s in db.query(Supplier).all():
            if getattr(s, "account_code", None):
                name_map[s.account_code] = s.name

    result = []
    for code, t in sorted(totals.items()):
        balance = round(t["debit"] - t["credit"], 2)
        if abs(balance) < 0.01 and t["debit"] == 0 and t["credit"] == 0:
            continue
        result.append({
            "account_code": code,
            "partner_name": name_map.get(code, code),
            "debit": round(t["debit"], 2),
            "credit": round(t["credit"], 2),
            "balance": balance,
            "source": "journal",
        })
    return result


def aged_balance_clients(db: Session) -> list:
    """Balance âgée clients depuis factures impayées."""
    from datetime import date
    today = date.today()
    buckets = ("0_30", "31_60", "61_90", "90_plus")
    clients = {c.id: c.name for c in db.query(Client).filter(Client.is_archived == False).all()}  # noqa: E712
    aging: dict[int, dict] = {}

    for inv in db.query(Invoice).filter(
        Invoice.is_archived == False,  # noqa: E712
        Invoice.status.in_(("envoyée", "en retard")),
        Invoice.doc_type != "credit_note",
    ).all():
        due = inv.due_date or inv.date or today
        days = (today - due).days if due else 0
        if days < 0:
            days = 0
        remaining = max((inv.amount or 0) - (inv.paid or 0), 0)
        if remaining < 0.01:
            continue
        cid = inv.client_id
        if cid not in aging:
            aging[cid] = {
                "client_id": cid,
                "client_name": clients.get(cid, "—"),
                "total": 0.0,
                **{b: 0.0 for b in buckets},
            }
        key = "0_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "90_plus"
        aging[cid][key] += remaining
        aging[cid]["total"] += remaining

    return [
        {**v, "total": round(v["total"], 2), **{b: round(v[b], 2) for b in buckets}}
        for v in sorted(aging.values(), key=lambda x: -x["total"])
    ]


def aged_balance_suppliers(db: Session) -> list:
    from datetime import date
    today = date.today()
    buckets = ("0_30", "31_60", "61_90", "90_plus")
    from app.models_erp import Supplier, SupplierInvoice
    suppliers = {s.id: s.name for s in db.query(Supplier).all()}
    aging: dict[int, dict] = {}

    for inv in db.query(SupplierInvoice).filter(
        SupplierInvoice.status.in_(("validée", "en retard", "payée")),
    ).all():
        remaining = max((inv.amount or 0) - (inv.paid or 0), 0)
        if remaining < 0.01:
            continue
        due = inv.due_date or inv.date or today
        days = max((today - due).days, 0) if due else 0
        sid = inv.supplier_id
        if sid not in aging:
            aging[sid] = {
                "supplier_id": sid,
                "supplier_name": suppliers.get(sid, "—"),
                "total": 0.0,
                **{b: 0.0 for b in buckets},
            }
        key = "0_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "90_plus"
        aging[sid][key] += remaining
        aging[sid]["total"] += remaining

    return [
        {**v, "total": round(v["total"], 2), **{b: round(v[b], 2) for b in buckets}}
        for v in sorted(aging.values(), key=lambda x: -x["total"])
    ]


def flux_tresorerie(db: Session):
    """Flux de trésorerie simplifié (encaissements / décaissements)."""
    encaissements = sum(i.paid or 0 for i in db.query(Invoice).all())
    decaissements = sum(s.paid or 0 for s in db.query(SupplierInvoice).all())
    mouvements = 0.0
    for m in db.query(TreasuryMovement).all():
        if m.type in ("caisse_entree", "banque_entree"):
            mouvements += m.amount or 0
        else:
            mouvements -= m.amount or 0
    return {
        "encaissements_clients": round(encaissements, 2),
        "decaissements_fournisseurs": round(decaissements, 2),
        "mouvements_tresorerie": round(mouvements, 2),
        "flux_net": round(encaissements - decaissements + mouvements, 2),
    }
