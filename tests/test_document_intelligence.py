"""Tests moteur d'intelligence documentaire."""
from app.services.document_intelligence import (
    DOC_INVOICE,
    DOC_BANK,
    DOC_LEDGER,
    analyze_document_text,
    detect_document_type,
    extract_invoice,
    validate_extraction,
)


def test_detect_invoice():
    text = """
    FACTURE N° FAC-2024-001
    Date : 15/03/2024
    Fournisseur : SARL TECH TOGO
    Total HT : 100 000
    TVA : 18 000
    Total TTC : 118 000 FCFA
    """
    doc_type, score = detect_document_type(text)
    assert doc_type == DOC_INVOICE
    assert score >= 0.35


def test_invoice_totals_validation_error():
    data = extract_invoice("""
    FACTURE FAC-1
    Total HT : 100000
    TVA : 18000
    Total TTC : 200000
    """)
    issues = validate_extraction(data)
    assert any(i["code"] == "TOTAL_MISMATCH" for i in issues)


def test_invoice_totals_validation_ok():
    data = extract_invoice("""
    FACTURE FAC-2
    Total HT : 100000
    TVA : 18000
    Total TTC : 118000
    """)
    issues = validate_extraction(data)
    assert not any(i["severity"] == "error" and i["code"] == "TOTAL_MISMATCH" for i in issues)


def test_bank_statement_detection():
    text = "RELEVE BANCAIRE\nCompte : 123456789\nSolde initial : 50000\nSolde final : 48000"
    doc_type, _ = detect_document_type(text)
    assert doc_type == DOC_BANK


def test_ledger_unbalanced():
    data = analyze_document_text("""
    Journal OD
    01/01/2024 601000 Achat 100000 0
    01/01/2024 401000 Fournisseur 0 50000
    """, document_type=DOC_LEDGER)
    assert any(i.get("code") == "LEDGER_UNBALANCED" for i in data.get("validation", []))


def test_precision_estimate_present():
    data = analyze_document_text("FACTURE FAC-99\nTotal TTC : 50000 FCFA\nFournisseur : Test SA")
    assert "precision_estimate" in data
    assert 0 < data["precision_estimate"] <= 0.99
