"""Tests validateurs métier et dates."""
from datetime import date

import pytest

from app.date_service import compute_due_date, parse_iso_date, utc_now_iso
from app.field_validators import clean_email, clean_text, validate_due_after_invoice


def test_compute_due_date():
    assert compute_due_date(date(2026, 6, 15), 30) == date(2026, 7, 15)
    assert compute_due_date(date(2026, 6, 15), 0) == date(2026, 6, 15)


def test_due_before_invoice_raises():
    with pytest.raises(ValueError):
        validate_due_after_invoice(date(2026, 1, 1), date(2026, 6, 1))


def test_clean_text_min_length():
    with pytest.raises(ValueError):
        clean_text("ab", min_len=3)


def test_clean_email():
    assert clean_email("  Test@Example.COM ") == "test@example.com"


def test_parse_iso_date():
    assert parse_iso_date("2026-06-15") == date(2026, 6, 15)
    assert parse_iso_date("") is None


def test_utc_now_iso():
    assert utc_now_iso().endswith("Z")
