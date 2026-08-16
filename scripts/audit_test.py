"""Tests d'audit automatisés (sans serveur HTTP requis)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.migrate import run_migrations
from app.database import SessionLocal
from app.permissions import has_module_action, flatten_role_permissions, get_role_matrix
from app.commercial_guards import INVOICE_LOCKED_STATUSES
from app.models import Invoice, Quote, User
from app.auth import hash_password, token_expire_hours


def check(name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg.encode("ascii", "replace").decode())
    return ok


def main():
    print("=== AUDIT ERP Peya — Tests automatisés ===\n")
    run_migrations()
    db = SessionLocal()
    results = []

    print("--- Sécurité & permissions ---")
    results.append(check("Viewer ne peut pas supprimer factures", not has_module_action("viewer", "invoices", "delete", db)))
    results.append(check("Viewer peut voir factures", has_module_action("viewer", "invoices", "view", db)))
    results.append(check("Commercial peut modifier factures", has_module_action("commercial", "invoices", "update", db)))
    results.append(check("Admin = toutes actions", has_module_action("admin", "invoices", "delete", db)))
    perms = flatten_role_permissions("commercial", db)
    results.append(check("Permissions commercial exposées", "invoices" in perms or "invoices.update" in perms))
    mx = get_role_matrix("manager", db)
    results.append(check("Matrice manager chargeable", isinstance(mx, dict) and "clients" in mx))
    results.append(check("JWT timeout depuis settings", token_expire_hours(db) >= 1))

    print("\n--- Verrous métier ---")
    results.append(check("Statuts facture verrouillés définis", "envoyée" in INVOICE_LOCKED_STATUSES and "payée" in INVOICE_LOCKED_STATUSES))

    print("\n--- Modules présents ---")
    from app.models_rbac import RoleMatrixOverride
    from app.models_enterprise import UserGroup
    from app.services.mail_groups import group_recipient_emails
    from app.services.password_service import validate_password_strength, generate_temp_password

    results.append(check("Table role_matrix_overrides", db.query(RoleMatrixOverride).count() >= 0))
    results.append(check("Groupes mail (modèle)", hasattr(UserGroup, "group_type")))
    tp = generate_temp_password()
    results.append(check("MDP temporaire conforme", len(validate_password_strength(tp)) == 0))

    print("\n--- Fichiers audit ---")
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    for rel in (
        "api_guards.py",
        "commercial_guards.py",
        "services/mail_groups.py",
        "routers/roles_rbac.py",
    ):
        results.append(check(f"Fichier {rel}", os.path.isfile(os.path.join(root, rel))))

    print("\n--- Couverture API main.py (échantillon) ---")
    import inspect
    import main as main_mod

    src = inspect.getsource(main_mod)
    results.append(check("main: require_action clients", 'require_action("clients"' in src))
    results.append(check("main: require_action invoices", 'require_action("invoices"' in src))
    results.append(check("main: assert_invoice_mutable", "assert_invoice_mutable" in src))
    results.append(check("main: log_audit factures", 'log_audit(db, "delete", "ventes", "invoice"' in src))
    unprotected = "def list_projects" in src and 'require_action("projects"' not in src
    if 'require_action("projects", "view")' in src:
        unprotected = False
    results.append(check("main: projects encore non protégés (écart connu)", unprotected))

    db.close()
    passed = sum(results)
    total = len(results)
    print(f"\n=== Résultat tests : {passed}/{total} PASS ===")
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
