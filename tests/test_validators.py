"""Tests MontantXOF et dates FR."""
import pytest
from datetime import date

from app.validators import parse_date_input, parse_montant_xof


def test_montant_espaces():
    assert parse_montant_xof("1 000 000") == 1000000
    assert parse_montant_xof("1.000.000") == 1000000


def test_montant_vide():
    assert parse_montant_xof("") == 0
    assert parse_montant_xof(None) == 0


def test_montant_negatif():
    with pytest.raises(ValueError):
        parse_montant_xof(-100)


def test_date_fr():
    assert parse_date_input("15/06/2026") == date(2026, 6, 15)
    assert parse_date_input("2026-06-15") == date(2026, 6, 15)
    assert parse_date_input("") is None


def test_date_invalide():
    with pytest.raises(ValueError):
        parse_date_input("32/13/2026")
