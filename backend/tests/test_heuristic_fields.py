import pytest

from app.services.fields import heuristic
from app.services.fields.canonical import CANONICAL_FIELDS, filter_fields, unknown_keys
from tests.fixtures import texts


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (texts.INVOICE_TEXT, texts.INVOICE_EXPECTED),
        (texts.RECEIPT_TEXT, texts.RECEIPT_EXPECTED),
        (texts.QUOTATION_TEXT, texts.QUOTATION_EXPECTED),
    ],
    ids=["two_page_invoice", "pos_receipt", "quotation"],
)
def test_required_fixtures_exact(text: str, expected: dict[str, str]) -> None:
    out = heuristic.extract(text)
    assert out == expected
    assert all(isinstance(v, str) for v in out.values())
    assert set(out) <= set(CANONICAL_FIELDS)
    assert out.get("document_number") != out.get("reference_number") or "document_number" not in out


def test_document_and_reference_never_from_same_line() -> None:
    out = heuristic.extract("PO Number: PO-555 ref ABC-123\nSomething else")
    assert out["document_number"] == "PO-555"
    assert "reference_number" not in out


def test_reference_from_other_line() -> None:
    out = heuristic.extract("Invoice # 10045\nReference: ORD-77")
    assert out["document_number"] == "10045"
    assert out["reference_number"] == "ORD-77"


def test_empty_text_returns_empty() -> None:
    assert heuristic.extract("") == {}
    assert heuristic.extract("   \n  \n") == {}


def test_document_date_falls_back_to_first_date() -> None:
    out = heuristic.extract("Shop\n2026-10-01 receipt line")
    assert out["document_date"] == "2026-10-01"


def test_due_date_only_on_due_line() -> None:
    out = heuristic.extract("Invoice\nIssued 01/02/2026\nPayment due 15/02/2026")
    assert out["due_date"] == "15/02/2026"
    assert out["document_date"] == "01/02/2026"


def test_issuer_fallback_first_short_line() -> None:
    out = heuristic.extract("Joe's Plumbing\nSome text without company suffix")
    assert out["issuer_name"] == "Joe's Plumbing"


def test_recipient_inline_label() -> None:
    out = heuristic.extract("ACME Corp\nSold To: Widget World\nThanks")
    assert out["recipient_name"] == "Widget World"


def test_amounts_take_last_amount_on_line_and_strip_symbols() -> None:
    out = heuristic.extract("Shop\nTotal $ 5.00 $1,250.50")
    assert out["total_amount"] == "1,250.50"


def test_total_uses_last_matching_line() -> None:
    out = heuristic.extract("Shop\nTotal 10.00\nBalance due 7.50")
    assert out["total_amount"] == "7.50"


def test_tax_excludes_total_lines() -> None:
    out = heuristic.extract("Shop\nTotal tax inclusive 99.00\nVAT 9.00")
    assert out["tax_amount"] == "9.00"


def test_currency_requires_explicit_code() -> None:
    assert "currency" not in heuristic.extract("Shop\nTotal $10.00")
    assert heuristic.extract("Shop\nAmount in USD\nTotal 10.00")["currency"] == "USD"


@pytest.mark.parametrize(
    ("line", "terms"),
    [
        ("Terms: Net 14", "Net 14"),
        ("Due on receipt", "Due on receipt"),
        ("Payment: COD", "COD"),
        ("Pay in 7 days", "7 days"),
    ],
)
def test_payment_terms(line: str, terms: str) -> None:
    assert heuristic.extract(f"Shop\n{line}")["payment_terms"] == terms


def test_no_line_items_omits_key() -> None:
    assert "line_items_summary" not in heuristic.extract("Shop\nTotal 10.00")


def test_line_items_summary_lists_first_three() -> None:
    text = "Shop\nA item 1 1.00 1.00\nB item 2 1.00 2.00\nC item 3 1.00 3.00\nD item 4 1.00 4.00"
    assert heuristic.extract(text)["line_items_summary"] == "4 line items: A item x1; B item x2; C item x3"


def test_filter_fields_whitelist() -> None:
    raw = {"total_amount": "5.00", "vendor_abn": "123", "subtotal": "", "tax_amount": 4.0, "currency": None}
    assert filter_fields(raw) == {"total_amount": "5.00"}
    assert unknown_keys(raw) == ["vendor_abn"]
