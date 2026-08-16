"""Migrations SQLite légères (colonnes / tables manquantes)."""

import re



from sqlalchemy import inspect, text

from app.database import engine, Base





def ensure_schema_compatibility(engine_instance=None) -> None:
    if engine_instance is None:
        engine_instance = engine

    import app.models  # noqa: F401

    import app.models_erp  # noqa: F401

    import app.models_prefs  # noqa: F401

    import app.models_currency  # noqa: F401

    import app.models_rbac  # noqa: F401

    import app.models_stock  # noqa: F401

    import app.models_enterprise  # noqa: F401

    import app.models_cms  # noqa: F401

    import app.models_calendar  # noqa: F401

    import app.models_syscohada  # noqa: F401

    import app.models_accounting  # noqa: F401

    import app.models_business_ext  # noqa: F401

    import app.models_platform  # noqa: F401

    import app.models_enterprise_suite  # noqa: F401

    Base.metadata.create_all(bind=engine_instance)

    insp = inspect(engine_instance)
    with engine_instance.begin() as conn:
        _add_column(conn, insp, "invoices", "description", "TEXT DEFAULT ''")
        _add_column(conn, insp, "supplier_invoices", "description", "TEXT DEFAULT ''")


def run_migrations():
    ensure_schema_compatibility(engine)

    import app.models_prefs  # noqa: F401

    import app.models_currency  # noqa: F401

    import app.models_rbac  # noqa: F401

    import app.models_stock  # noqa: F401

    import app.models_enterprise  # noqa: F401

    import app.models_cms  # noqa: F401

    import app.models_calendar  # noqa: F401

    import app.models_syscohada  # noqa: F401

    import app.models_accounting  # noqa: F401

    import app.models_business_ext  # noqa: F401

    import app.models_platform  # noqa: F401

    import app.models_enterprise_suite  # noqa: F401

    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)

    with engine.begin() as conn:

        _add_column(conn, insp, "quotes", "vat_rate", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "invoices", "vat_rate", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "quotes", "deal_id", "INTEGER")
        _add_column(conn, insp, "quotes", "notes", "TEXT DEFAULT ''")

        _add_column(conn, insp, "invoices", "quote_id", "INTEGER")
        _add_column(conn, insp, "invoices", "doc_type", "VARCHAR DEFAULT 'invoice'")
        _add_column(conn, insp, "invoices", "related_invoice_id", "INTEGER")
        _add_column(conn, insp, "invoices", "is_archived", "BOOLEAN DEFAULT 0")
        _add_column(conn, insp, "clients", "is_archived", "BOOLEAN DEFAULT 0")
        _add_column(conn, insp, "suppliers", "is_archived", "BOOLEAN DEFAULT 0")
        _add_column(conn, insp, "system_settings", "closed_fiscal_years_json", "TEXT DEFAULT '[]'")

        _add_column(conn, insp, "accounts", "class_code", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "accounts", "parent_code", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "accounts", "level", "INTEGER DEFAULT 2")

        _add_column(conn, insp, "invoices", "credit_note_type", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "invoices", "journal_entry_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoices", "journal_entry_id", "INTEGER")
        _add_column(conn, insp, "journal_entries", "source_type", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "journal_entries", "source_id", "INTEGER")
        _add_column(conn, insp, "journal_entries", "accounting_transaction_id", "INTEGER")
        _add_column(conn, insp, "journal_lines", "letter_code", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "clients", "account_code", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "clients", "payment_terms", "INTEGER DEFAULT 30")
        _add_column(conn, insp, "suppliers", "account_code", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "journal_entries", "reversed_by_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoices", "doc_type", "VARCHAR DEFAULT 'invoice'")
        _add_column(conn, insp, "supplier_invoices", "related_supplier_invoice_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoices", "purchase_order_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoices", "goods_receipt_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoices", "three_way_status", "VARCHAR DEFAULT 'pending'")
        _add_column(conn, insp, "supplier_invoices", "three_way_detail", "TEXT DEFAULT ''")
        _add_column(conn, insp, "document_lines", "product_type", "VARCHAR DEFAULT 'SERVICE'")
        _add_column(conn, insp, "document_lines", "stock_item_id", "INTEGER")
        _add_column(conn, insp, "document_lines", "account_code", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "document_lines", "sale_account", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "document_lines", "purchase_account", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "stock_items", "product_accounting_type", "VARCHAR DEFAULT 'MERCHANDISE'")
        _add_column(conn, insp, "stock_items", "stock_category_id", "INTEGER")
        _add_column(conn, insp, "stock_items", "purchase_account", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "stock_items", "sale_account", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "stock_items", "stock_account", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "stock_items", "vat_account", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "system_settings", "inventory_method", "VARCHAR DEFAULT 'PERMANENT'")

        _add_column(conn, insp, "stock_items", "purchase_account_id", "INTEGER")
        _add_column(conn, insp, "stock_items", "sale_account_id", "INTEGER")
        _add_column(conn, insp, "stock_items", "stock_account_id", "INTEGER")
        _add_column(conn, insp, "stock_items", "vat_account_id", "INTEGER")
        _add_column(conn, insp, "document_lines", "account_id", "INTEGER")
        _add_column(conn, insp, "document_lines", "sale_account_id", "INTEGER")
        _add_column(conn, insp, "document_lines", "purchase_account_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoice_lines", "account_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoice_lines", "purchase_account_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoice_lines", "stock_account_id", "INTEGER")
        _add_column(conn, insp, "supplier_invoice_lines", "vat_account_id", "INTEGER")

        _add_column(conn, insp, "clients", "credit_limit", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "app_notifications", "category", "VARCHAR DEFAULT 'system'")

        _add_column(conn, insp, "app_notifications", "channel", "VARCHAR DEFAULT 'in_app'")

        _add_column(conn, insp, "audit_logs", "logged_at", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "audit_logs", "old_value", "TEXT DEFAULT ''")

        _add_column(conn, insp, "audit_logs", "new_value", "TEXT DEFAULT ''")

        _add_column(conn, insp, "stock_items", "qty_theoretical", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "stock_items", "qty_reserved", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "stock_items", "qty_on_order", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "stock_items", "max_quantity", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "stock_items", "safety_stock", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "stock_items", "reorder_point", "FLOAT DEFAULT 0")

        _add_column(conn, insp, "stock_items", "warehouse_id", "INTEGER")

        _add_column(conn, insp, "stock_items", "expiry_date", "DATE")

        _add_column(conn, insp, "stock_movements", "logged_at", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "stock_movements", "movement_kind", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "stock_movements", "qty_before", "FLOAT")

        _add_column(conn, insp, "stock_movements", "qty_after", "FLOAT")

        _add_column(conn, insp, "stock_movements", "warehouse_id", "INTEGER")

        _add_column(conn, insp, "stock_movements", "warehouse_to_id", "INTEGER")

        _add_column(conn, insp, "stock_movements", "user_id", "INTEGER")

        _add_column(conn, insp, "stock_movements", "user_email", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "employees", "gender", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "employees", "contract_type", "VARCHAR DEFAULT 'CDI'")
        _add_column(conn, insp, "employees", "manager_id", "INTEGER")
        _add_column(conn, insp, "goods_receipts", "purchase_request_id", "INTEGER")
        _add_column(conn, insp, "goods_receipts", "purchase_order_id", "INTEGER")

        _TENANT_TABLES = (
            "clients", "deals", "quotes", "invoices", "projects", "suppliers", "supplier_invoices",
        )
        for tbl in _TENANT_TABLES:
            _add_column(conn, insp, tbl, "company_id", "INTEGER")
        _backfill_company_id(conn, insp)
        _record_schema_version(conn, "20260616_tenant_metrics_workflow")

        _create_indexes(conn)

        _add_column(conn, insp, "user_preferences", "display_currency_code", "VARCHAR DEFAULT 'XOF'")
        _add_column(conn, insp, "user_preferences", "theme_mode", "VARCHAR DEFAULT 'dark'")
        _add_column(conn, insp, "user_preferences", "color_palette", "VARCHAR DEFAULT 'peya'")
        _add_column(conn, insp, "user_preferences", "custom_theme_json", "TEXT DEFAULT '{}'")
        _add_column(conn, insp, "user_preferences", "font_scale", "VARCHAR DEFAULT '1'")
        _add_column(conn, insp, "system_settings", "appearance_json", "TEXT DEFAULT '{}'")
        _add_column(conn, insp, "system_settings", "documents_json", "TEXT DEFAULT '{}'")
        _add_column(conn, insp, "system_settings", "storage_json", "TEXT DEFAULT '{}'")
        _add_column(conn, insp, "system_settings", "integrations_json", "TEXT DEFAULT '{}'")

        _add_column(conn, insp, "users", "username", "VARCHAR")

        _add_column(conn, insp, "users", "first_name", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "users", "last_name", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "users", "department", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "users", "must_change_password", "BOOLEAN DEFAULT 0")

        _add_column(conn, insp, "users", "password_expires_at", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "users", "last_password_change", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "users", "updated_at", "VARCHAR DEFAULT ''")

        _add_column(conn, insp, "user_groups", "group_type", "VARCHAR DEFAULT 'permission'")
        _add_column(conn, insp, "user_groups", "extra_emails", "TEXT DEFAULT ''")
        _add_column(conn, insp, "user_group_members", "employee_id", "INTEGER")

        if "users" in insp.get_table_names():

            _backfill_usernames(conn)

        _migrate_cms_slug_locale(conn, insp)
        _add_column(conn, insp, "cms_media", "display_name", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "cms_media", "webp_path", "VARCHAR DEFAULT ''")
        _add_column(conn, insp, "cms_media", "width", "INTEGER DEFAULT 0")
        _add_column(conn, insp, "cms_media", "height", "INTEGER DEFAULT 0")

        _migrate_enterprise_dates_audit(conn, insp)
        _migrate_ocr_columns(conn, insp)
        _migrate_business_suite(conn, insp)
        _record_schema_version(conn, "20260618_business_suite")
        _migrate_platform(conn, insp)
        _record_schema_version(conn, "20260619_platform_enterprise")
        _migrate_treasury_p1(conn, insp)
        _record_schema_version(conn, "20260620_treasury_p1")
        _migrate_crm_p2(conn, insp)
        _record_schema_version(conn, "20260621_crm_p2")
        _migrate_enterprise_suite(conn, insp)
        _record_schema_version(conn, "20260622_enterprise_suite")
        _migrate_document_lines_display(conn, insp)
        _record_schema_version(conn, "20260720_document_lines_display")
        _migrate_crm_advanced_company(conn, insp)
        _record_schema_version(conn, "20260721_crm_advanced_company")
        _add_column(conn, insp, "stock_movements", "unit_cost", "FLOAT")
        _record_schema_version(conn, "20260721_stock_movement_unit_cost")
        _migrate_zero_client_type_discounts(conn, insp)
        _record_schema_version(conn, "20260720_zero_client_type_discount")
        _migrate_journal_client(conn, insp)
        _record_schema_version(conn, "20260723_journal_client")
        _migrate_discount_amount(conn, insp)
        _record_schema_version(conn, "20260725_discount_amount")




def _migrate_business_suite(conn, insp) -> None:
    """Phases A-F — brouillard, types clients, recouvrement, contrats."""
    _add_column(conn, insp, "journal_entries", "value_date", "DATE")
    _add_column(conn, insp, "journal_entries", "created_at", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "journal_entries", "created_by", "INTEGER")
    _add_column(conn, insp, "journal_entries", "updated_at", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "journal_entries", "updated_by", "INTEGER")
    _add_column(conn, insp, "clients", "client_type_id", "INTEGER")
    _add_column(conn, insp, "clients", "default_discount_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "clients", "default_vat_pct", "FLOAT DEFAULT 18")
    _add_column(conn, insp, "clients", "default_commission_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "clients", "default_withholding_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "invoices", "delivery_date", "DATE")
    _add_column(conn, insp, "invoices", "discount_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "invoices", "commission_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "invoices", "withholding_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "invoices", "recurring_plan_id", "INTEGER")
    _add_column(conn, insp, "document_lines", "discount_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "deals", "sales_rep_id", "INTEGER")
    _add_column(conn, insp, "crm_leads", "sales_rep_id", "INTEGER")
    if "invoice_recurring" in insp.get_table_names():
        for col, typedef in (
            ("template_invoice_id", "INTEGER"),
            ("end_date", "DATE"),
            ("last_generated_at", "VARCHAR DEFAULT ''"),
            ("notes", "TEXT DEFAULT ''"),
        ):
            _add_column(conn, insp, "invoice_recurring", col, typedef)

def _migrate_ocr_columns(conn, insp) -> None:
    if "ocr_extractions" not in insp.get_table_names():
        return
    for col, typedef in (
        ("corrected_json", "TEXT DEFAULT ''"),
        ("document_type", "VARCHAR DEFAULT 'unknown'"),
        ("confidence_score", "FLOAT DEFAULT 0"),
        ("validation_json", "TEXT DEFAULT '[]'"),
        ("status", "VARCHAR DEFAULT 'pending'"),
        ("applied_entity_type", "VARCHAR DEFAULT ''"),
        ("applied_entity_id", "INTEGER"),
    ):
        _add_column(conn, insp, "ocr_extractions", col, typedef)


def _migrate_enterprise_dates_audit(conn, insp) -> None:
    """Colonnes dates + audit sur tables métier principales."""
    audit_cols = [
        ("payment_terms_days", "INTEGER DEFAULT 30"),
        ("issued_at", "VARCHAR DEFAULT ''"),
        ("payment_date", "DATE"),
        ("validated_at", "VARCHAR DEFAULT ''"),
        ("cancelled_at", "VARCHAR DEFAULT ''"),
        ("created_at", "VARCHAR DEFAULT ''"),
        ("updated_at", "VARCHAR DEFAULT ''"),
        ("created_by", "INTEGER"),
        ("updated_by", "INTEGER"),
    ]
    for table in ("invoices", "supplier_invoices", "quotes", "clients", "suppliers"):
        if table not in insp.get_table_names():
            continue
        for col, typedef in audit_cols:
            _add_column(conn, insp, table, col, typedef)


def _email_local_part(email: str) -> str:

    if not email:

        return "user"

    local = email.split("@", 1)[0].lower()

    return re.sub(r"[^a-z0-9]", "", local)[:20] or "user"





def _backfill_usernames(conn):

    """Attribue un username unique à chaque utilisateur existant."""

    rows = conn.execute(text("SELECT id, email, username FROM users ORDER BY id")).fetchall()

    taken: set[str] = set()

    for uid, email, username in rows:

        current = (username or "").strip().lower()

        if current and current not in taken:

            taken.add(current)

            if current != username:

                conn.execute(

                    text("UPDATE users SET username = :u WHERE id = :id"),

                    {"u": current, "id": uid},

                )

            continue

        base = _email_local_part(email or "")

        candidate = base

        n = 0

        while candidate in taken:

            n += 1

            candidate = f"{base[:16]}{n}"

        taken.add(candidate)

        conn.execute(

            text("UPDATE users SET username = :u WHERE id = :id"),

            {"u": candidate, "id": uid},

        )





def _migrate_cms_slug_locale(conn, insp) -> None:
    """Recrée cms_pages si contrainte unique obsolète (slug seul au lieu slug+locale)."""
    if "cms_pages" not in insp.get_table_names():
        return
    # This migration inspects SQLite's sqlite_master; skip on non-sqlite dialects
    if conn.dialect.name != 'sqlite':
        return
    row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='cms_pages'")
    ).fetchone()
    ddl = (row[0] or "") if row else ""
    if "uq_cms_page_slug_locale" in ddl:
        return
    for t in ("cms_page_versions", "cms_pages"):
        conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
    from app.models_cms import CmsPage, CmsPageVersion

    CmsPage.__table__.create(conn, checkfirst=True)
    CmsPageVersion.__table__.create(conn, checkfirst=True)


def _add_column(conn, insp, table: str, column: str, col_def: str):

    if table not in insp.get_table_names():

        return

    cols = {c["name"] for c in insp.get_columns(table)}

    if column in cols:

        return

    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


def _backfill_company_id(conn, insp) -> None:
    """Rattache les enregistrements existants à la société par défaut."""
    if "companies" not in insp.get_table_names():
        return
    # use boolean literal for Postgres compatibility
    row = conn.execute(text("SELECT id FROM companies WHERE is_default IS TRUE LIMIT 1")).fetchone()
    if not row:
        row = conn.execute(text("SELECT id FROM companies ORDER BY id LIMIT 1")).fetchone()
    if not row:
        return
    cid = row[0]
    for tbl in (
        "clients", "deals", "quotes", "invoices", "projects", "suppliers", "supplier_invoices",
    ):
        if tbl not in insp.get_table_names():
            continue
        conn.execute(
            text(f"UPDATE {tbl} SET company_id = :cid WHERE company_id IS NULL"),
            {"cid": cid},
        )


def _record_schema_version(conn, version: str) -> None:
    from datetime import datetime, timezone

    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version VARCHAR PRIMARY KEY, applied_at VARCHAR NOT NULL)"
    ))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # Use dialect-appropriate upsert/ignore: SQLite supports "INSERT OR IGNORE",
    # Postgres uses "ON CONFLICT DO NOTHING".
    dialect = conn.dialect.name if hasattr(conn, 'dialect') else ''
    if dialect == 'sqlite':
        conn.execute(
            text("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
            {"v": version, "t": now},
        )
    else:
        conn.execute(
            text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :t) ON CONFLICT (version) DO NOTHING"),
            {"v": version, "t": now},
        )


def _create_indexes(conn) -> None:
    """Index de performance critiques (phase 3)."""
    stmts = [
        "CREATE INDEX IF NOT EXISTS idx_invoices_status_date ON invoices(status, date)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_client_date ON invoices(client_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_supplier_invoices_status_date ON supplier_invoices(status, date)",
        "CREATE INDEX IF NOT EXISTS idx_supplier_invoices_supplier_date ON supplier_invoices(supplier_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_item_date ON stock_movements(item_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_warehouse_date ON stock_movements(warehouse_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_goods_receipts_supplier_date ON goods_receipts(supplier_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_purchase_requests_status_date ON purchase_requests(status, date)",
        "CREATE INDEX IF NOT EXISTS idx_purchase_orders_status_date ON purchase_orders(status, date)",
        "CREATE INDEX IF NOT EXISTS idx_journal_entries_fy_period ON journal_entries(fiscal_year, period, status)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_module_date ON audit_logs(module, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_clients_company ON clients(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_company ON suppliers(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_company_date ON invoices(company_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_supplier_invoices_company_date ON supplier_invoices(company_id, date)",
    ]
    for sql in stmts:
        conn.execute(text(sql))


def _migrate_platform(conn, insp) -> None:
    """Phase P0 — tables plateforme (create_all gère la création initiale)."""
    pass


def _migrate_treasury_p1(conn, insp) -> None:
    """Phase P1 — trésorerie unifiée."""
    _add_column(conn, insp, "bank_accounts", "account_type", "VARCHAR DEFAULT 'bank'")
    _add_column(conn, insp, "treasury_movements", "payment_method", "VARCHAR DEFAULT ''")


def _migrate_crm_p2(conn, insp) -> None:
    """Phase P2 — messages tickets (tables via create_all)."""
    pass


def _migrate_enterprise_suite(conn, insp) -> None:
    """Phases P3–P5 — stock avancé, maintenance, consolidation, GED, connecteurs."""
    _add_column(conn, insp, "stock_items", "barcode", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "stock_items", "created_at", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "stock_items", "updated_at", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "tasks", "kanban_status", "VARCHAR DEFAULT 'todo'")
    _add_column(conn, insp, "document_files", "ocr_result_json", "TEXT DEFAULT ''")
    _add_column(conn, insp, "esign_requests", "signing_token", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "esign_requests", "provider_ref", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "esign_requests", "signing_url", "VARCHAR DEFAULT ''")


def _migrate_crm_advanced_company(conn, insp) -> None:
    """Cloisonnement multi-société pour le CRM avancé (leads/activités/campagnes).

    Ces tables n'avaient aucune colonne `company_id` : le filtrage par société
    (`filter_by_company`) y était un no-op silencieux quel que soit le code appliqué
    dans les routers — voir CLAUDE.md §3.1/§M2.
    """
    _add_column(conn, insp, "crm_leads", "company_id", "INTEGER")
    _add_column(conn, insp, "crm_activities", "company_id", "INTEGER")
    _add_column(conn, insp, "crm_campaigns", "company_id", "INTEGER")


def _migrate_document_lines_display(conn, insp) -> None:
    """Persiste la référence article et l'unité sur les lignes de devis/facture.

    Ces deux champs étaient saisis dans l'éditeur de lignes mais jamais envoyés
    (devis) ou jamais lus par le modèle ORM (devis + factures) : l'article lié
    disparaissait visuellement à chaque réouverture d'un document existant.
    """
    _add_column(conn, insp, "document_lines", "reference", "VARCHAR DEFAULT ''")
    _add_column(conn, insp, "document_lines", "unit", "VARCHAR DEFAULT 'unité'")


def _migrate_zero_client_type_discounts(conn, insp) -> None:
    """Remise par défaut à 0 — plus d'héritage automatique depuis les types clients."""
    if "client_types" not in insp.get_table_names():
        return
    conn.execute(text(
        "UPDATE client_types SET default_discount_pct = 0 "
        "WHERE default_discount_pct IS NOT NULL AND default_discount_pct != 0"
    ))


def _migrate_journal_client(conn, insp) -> None:
    """Rattache les écritures/lignes journal à un client pour affichage et exports."""
    _add_column(conn, insp, "journal_entries", "client_id", "INTEGER")
    _add_column(conn, insp, "journal_entries", "observation", "TEXT DEFAULT ''")
    _add_column(conn, insp, "journal_lines", "client_id", "INTEGER")


def _migrate_discount_amount(conn, insp) -> None:
    """Remise en MONTANT (en plus du %, déjà existant) — ligne et document.
    Le moteur de calcul (document_calc_service.py) et le calcul JS (LineKit) supportaient déjà
    discount_amount ; seules les colonnes DB manquaient pour que la saisie soit persistée."""
    _add_column(conn, insp, "document_lines", "discount_amount", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "invoices", "discount_amount", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "quotes", "discount_pct", "FLOAT DEFAULT 0")
    _add_column(conn, insp, "quotes", "discount_amount", "FLOAT DEFAULT 0")

