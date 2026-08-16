"""Tests unitaires — politique et mots de passe temporaires."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.password_service import (
    DEFAULT_POLICY,
    generate_temp_password,
    validate_password_strength,
)


def test_validate_password_ok():
    assert validate_password_strength("Peya@2026", DEFAULT_POLICY) == []


def test_validate_password_fails_short():
    errs = validate_password_strength("short", DEFAULT_POLICY)
    assert any("caractères" in e for e in errs)


def test_temp_password_meets_default_policy():
    for _ in range(20):
        temp = generate_temp_password()
        assert temp.startswith("Temp#")
        assert validate_password_strength(temp, DEFAULT_POLICY) == []
