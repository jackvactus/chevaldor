"""Vérifie serveur + persistance SQLite."""
import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

DB = Path(__file__).parent.parent / "peya_company.db"
BASE = "http://localhost:8001"


def req(path, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    results = []
    results.append(("Fichier SQLite", DB.is_file(), str(DB.resolve())))

    st, health = req("/api/health")
    results.append(("API health", st == 200 and health.get("db_exists"), health))

    st, login = req("/api/auth/login", "POST", {"email": "admin@peyacompany.com", "password": "Password1234@"})
    token = login.get("access_token") if st == 200 else None
    results.append(("Login admin", st == 200 and bool(token), st))

    if not token:
        _print(results)
        return

    for label, path in [
        ("GET clients", "/api/clients"),
        ("GET invoices", "/api/invoices"),
        ("GET imports", "/api/data/imports"),
        ("GET settings/system", "/api/settings/system"),
        ("GET notifications", "/api/notifications"),
        ("GET status", "/api/status"),
    ]:
        st, data = req(path, token=token)
        results.append((label, st == 200, st))

    st, created = req(
        "/api/clients",
        "POST",
        {"name": "Test DB Connect", "type": "Entreprise", "status": "actif"},
        token,
    )
    cid = created.get("id")
    results.append(("POST client", st == 200 and cid, f"id={cid}"))

    if cid:
        st, clients = req("/api/clients", token=token)
        found = any(c.get("id") == cid for c in clients) if isinstance(clients, list) else False
        results.append(("Client persiste en base", st == 200 and found, "OK" if found else "NON TROUVE"))
        req(f"/api/clients/{cid}", "DELETE", token=token)

    if DB.is_file():
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        n_tables = len(cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        counts = {}
        for table in ("clients", "invoices", "users", "import_batches", "system_settings", "smtp_settings"):
            try:
                counts[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                counts[table] = "n/a"
        conn.close()
        results.append(("SQLite direct", True, f"{n_tables} tables, {counts}"))

    _print(results)


def _print(results):
    print("=== VERIFICATION BASE DE DONNEES ===")
    ok = sum(1 for _, o, _ in results if o)
    for name, good, detail in results:
        print(f"{'OK' if good else 'FAIL'} | {name} | {detail}")
    print(f"=== {ok}/{len(results)} controles OK ===")


if __name__ == "__main__":
    main()
