"""Smoke test API — enregistrements CRUD principaux (à lancer : python scripts/smoke_test_api.py)."""
import json
import sys
import time
import urllib.error
import urllib.request

UID = str(int(time.time()))

BASE = "http://localhost:8001"
EMAIL = "admin@peyacompany.com"
PASSWORD = "Password1234@"


class Client:
    def __init__(self):
        self.token = None
        self.ids = {}

    def call(self, name, method, path, body=None, expect=(200, 201, 204)):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                st = res.status
                raw = res.read()
                ct = res.headers.get("Content-Type", "")
                out = json.loads(raw) if raw and "json" in ct else (raw[:80] if raw else None)
        except urllib.error.HTTPError as e:
            st = e.code
            try:
                out = json.loads(e.read().decode())
            except Exception:
                out = e.read().decode()[:200]
        ok = st in (expect if isinstance(expect, tuple) else (expect,))
        detail = out.get("detail", out) if isinstance(out, dict) else out
        status = "OK" if ok else "FAIL"
        msg = str(detail)[:80] if not ok else ""
        print(f"  [{status}] {name}: {st} {msg}".encode("ascii", "replace").decode())
        return ok, st, out


def main():
    c = Client()
    results = []

    def run(name, method, path, body=None, expect=(200, 201), store_key=None):
        ok, st, out = c.call(name, method, path, body, expect)
        results.append((name, ok))
        if ok and store_key and isinstance(out, dict) and "id" in out:
            c.ids[store_key] = out["id"]
        return ok, out

    print("=== PEYA ERP — Smoke test API ===\n")

    ok, out = run("health", "GET", "/api/health")
    if not ok:
        print("\nServeur inaccessible. Lancez: cd backend && python main.py")
        sys.exit(1)

    ok, login = run("login", "POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    if not ok:
        sys.exit(1)
    c.token = login["access_token"]

    # Lecture
    for name, path in [
        ("GET dashboard", "/api/dashboard"),
        ("GET clients", "/api/clients"),
        ("GET deals", "/api/deals"),
        ("GET quotes", "/api/quotes"),
        ("GET invoices", "/api/invoices"),
        ("GET projects", "/api/projects"),
        ("GET trainings", "/api/trainings"),
        ("GET stock", "/api/stock"),
        ("GET transactions", "/api/transactions"),
        ("GET accounts", "/api/accounts"),
        ("GET accounting summary", "/api/accounting/summary"),
        ("GET company", "/api/company"),
        ("GET clientele summary", "/api/clientele/summary"),
        ("GET charts sales", "/api/charts/sales-monthly"),
        ("GET charts pipeline", "/api/charts/pipeline-stages"),
        ("GET search", "/api/search?q=test"),
        ("GET notifications", "/api/notifications"),
        ("GET settings", "/api/settings/me"),
        ("GET erp dashboard", "/api/erp/dashboard/full"),
        ("GET suppliers", "/api/erp/suppliers"),
        ("GET banks", "/api/erp/bank-accounts"),
        ("GET employees", "/api/erp/employees"),
        ("GET audit", "/api/erp/audit-logs"),
    ]:
        run(name, "GET", path)

    # CRUD avec dates vides
    run("POST client", "POST", "/api/clients", {
        "name": "Smoke Client", "type": "Entreprise", "status": "actif",
    }, store_key="client")
    cid = c.ids.get("client")

    run("POST deal (date vide)", "POST", "/api/deals", {
        "title": "Smoke Deal", "client_id": cid, "stage": "lead",
        "amount": 1000, "probability": 30, "close_date": "", "notes": "",
    }, store_key="deal")

    run("POST quote (dates vides)", "POST", "/api/quotes", {
        "number": f"SMK-DEV-{UID}", "client_id": cid, "title": "Smoke",
        "date": "", "valid_until": "", "amount": 500, "status": "brouillon",
    }, store_key="quote")
    qid = c.ids.get("quote")

    if qid:
        run("PUT quote lines", "PUT", f"/api/quotes/{qid}/lines", {
            "lines": [{"description": "Ligne test", "quantity": 1, "unit_price": 500, "vat_rate": 0}],
        })
        run("POST convert quote", "POST", f"/api/quotes/{qid}/convert-to-invoice", None, store_key="invoice")
    else:
        results.extend([("PUT quote lines", False), ("POST convert quote", False)])
    iid = c.ids.get("invoice")

    run("POST invoice direct", "POST", "/api/invoices", {
        "number": f"SMK-FAC-{UID}", "client_id": cid, "date": "",
        "due_date": "", "amount": 200, "status": "brouillon",
    })

    run("POST project", "POST", "/api/projects", {
        "name": "Smoke Projet", "client_id": cid,
        "start_date": "", "end_date": "", "status": "planifié",
    }, store_key="project")
    pid = c.ids.get("project")

    run("POST task", "POST", "/api/tasks", {
        "project_id": pid, "label": "Tâche smoke", "date": "", "done": False,
    }, store_key="task")

    run("POST training", "POST", "/api/trainings", {
        "title": "Formation smoke", "start_date": "", "end_date": "",
        "duration": 1, "status": "planifiée",
    }, store_key="training")
    tid = c.ids.get("training")

    run("POST trainee", "POST", "/api/trainees", {
        "training_id": tid, "firstname": "Jean", "lastname": "Test",
    })

    run("POST stock item", "POST", "/api/stock", {
        "sku": f"SMK-{UID}", "name": "Article smoke", "quantity": 10,
    }, store_key="stock")
    sid = c.ids.get("stock")

    run("POST stock movement", "POST", "/api/stock-movements", {
        "item_id": sid, "type": "entrée", "quantity": 5, "date": "",
    })

    run("POST account", "POST", "/api/accounts", {
        "code": f"SMK{UID[-6:]}", "label": "Compte smoke", "type": "charge",
    })

    run("POST transaction", "POST", "/api/transactions", {
        "label": "Charge smoke", "type": "charge", "amount": 50, "date": "",
    })

    run("POST clientele client", "POST", "/api/clientele/clients", {
        "name": "Clientèle Smoke", "phone": "0696000000",
    }, store_key="clt")

    run("POST activity", "POST", "/api/activities", {
        "client_id": cid, "type": "note", "subject": "Smoke", "date": "",
    })

    if cid:
        run("GET client 360", "GET", f"/api/clients/{cid}/360")

    if c.ids.get("deal"):
        run("PATCH deal stage", "PATCH", f"/api/deals/{c.ids['deal']}/stage", {"stage": "qualified"})

    # ERP
    run("POST supplier", "POST", "/api/erp/suppliers", {
        "name": "Fournisseur Smoke", "code": f"FSMK{UID[-4:]}",
    }, store_key="supplier")
    sup = c.ids.get("supplier")

    run("POST supplier invoice", "POST", "/api/erp/supplier-invoices", {
        "number": f"FF-SMK-{UID}", "supplier_id": sup, "amount": 300,
        "date": "", "due_date": "",
    })

    run("POST bank", "POST", "/api/erp/bank-accounts", {
        "name": "Compte Smoke", "balance": 1000,
    }, store_key="bank")
    bid = c.ids.get("bank")

    run("POST treasury", "POST", "/api/erp/treasury-movements", {
        "type": "entrée", "bank_account_id": bid, "amount": 100,
        "label": "Smoke", "date": "",
    })

    run("POST cost center", "POST", "/api/erp/cost-centers", {
        "code": f"CC-{UID[-6:]}", "name": "Centre smoke",
    })

    run("POST budget", "POST", "/api/erp/budgets", {
        "name": "Budget smoke", "year": 2026, "amount_planned": 5000,
    })

    run("POST employee", "POST", "/api/erp/employees", {
        "matricule": f"EMP-{UID}", "firstname": "Marie", "lastname": "Smoke",
        "hire_date": "",
    }, store_key="employee")
    eid = c.ids.get("employee")

    run("POST leave", "POST", "/api/erp/leave-requests", {
        "employee_id": eid, "start_date": "", "end_date": "", "type": "congé",
    })

    run("PUT settings", "PUT", "/api/settings/me", {"theme": "dark", "language": "fr"})

    if iid:
        run("POST invoice payment", "POST", f"/api/invoices/{iid}/payment", {"amount": 100})

    run("POST sync overdue", "POST", "/api/invoices/sync-overdue", {})

  # PDF (200 ou fichier)
    if qid:
        c.call("GET quote PDF", "GET", f"/api/quotes/{qid}/pdf", expect=(200,))

    passed = sum(1 for _, ok in results if ok)
    failed = [(n, ok) for n, ok in results if not ok]
    print(f"\n=== Résultat : {passed}/{len(results)} OK ===")
    if failed:
        print("Échecs :", ", ".join(n for n, _ in failed))
        sys.exit(1)
    print("Tous les tests smoke sont passés (API).")
    print("Note : l'interface navigateur (boutons, modals) n'est pas couverte par ce script.")


if __name__ == "__main__":
    main()
