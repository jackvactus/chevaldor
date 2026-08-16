from pathlib import Path

from sqlalchemy import create_engine, inspect

from app import migrate


def test_ensure_schema_compatibility_adds_invoice_description_column(tmp_path: Path):
    db_path = tmp_path / "test_invoice_schema.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE invoices (id INTEGER PRIMARY KEY, number VARCHAR)")

    migrate.ensure_schema_compatibility(engine)

    columns = [col["name"] for col in inspect(engine).get_columns("invoices")]
    assert "description" in columns
