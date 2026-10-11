from app.errors import ErrorCode
from app.services.validation import (
    PDF_TRUNCATED_WARNING,
    ValidatedFile,
    count_pdf_pages,
    sniff_mime,
    validate_file,
)
from tests.conftest import fixture_bytes

MB = 1024 * 1024


def _validate(name: str, data: bytes | None = None, max_bytes: int = 10 * MB, max_pages: int = 20) -> ValidatedFile:
    data = fixture_bytes(name) if data is None else data
    return validate_file(name, data, len(data), max_bytes, max_pages)


def test_accepts_jpeg_by_magic_bytes() -> None:
    v = _validate("receipt.jpg")
    assert v.error_code is None
    assert v.mime_type == "image/jpeg"
    assert v.pages_processed == 1


def test_accepts_pdf_by_magic_bytes() -> None:
    v = _validate("invoice.pdf")
    assert v.error_code is None
    assert v.mime_type == "application/pdf"
    assert v.total_pages == 2
    assert v.pages_processed == 2
    assert v.warnings == ()


def test_magic_bytes_win_over_extension() -> None:
    v = validate_file("scan.pdf", fixture_bytes("receipt.jpg"), 10, 10 * MB, 20)
    assert v.mime_type == "image/jpeg"


def test_rejects_renamed_png() -> None:
    assert _validate("renamed_png.jpg").error_code == ErrorCode.INVALID_FILE_TYPE


def test_sniff_mime() -> None:
    assert sniff_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff_mime(b"%PDF-1.7") == "application/pdf"
    assert sniff_mime(b"\x89PNG\r\n") is None
    assert sniff_mime(b"") is None


def test_rejects_oversize_file() -> None:
    v = validate_file("big.pdf", None, 11 * MB, 10 * MB, 20)
    assert v.error_code == ErrorCode.FILE_TOO_LARGE
    assert v.data is None


def test_size_limit_is_inclusive() -> None:
    data = fixture_bytes("invoice.pdf")
    assert validate_file("x.pdf", data, len(data), len(data), 20).error_code is None
    assert validate_file("x.pdf", data, len(data), len(data) - 1, 20).error_code == ErrorCode.FILE_TOO_LARGE


def test_corrupt_pdf() -> None:
    assert _validate("corrupt.pdf").error_code == ErrorCode.CORRUPT_FILE


def test_corrupt_jpeg() -> None:
    v = validate_file("x.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 20, 24, 10 * MB, 20)
    assert v.error_code == ErrorCode.CORRUPT_FILE


def test_counts_pdf_pages() -> None:
    assert count_pdf_pages(fixture_bytes("long_21_pages.pdf")) == 21
    assert count_pdf_pages(fixture_bytes("quotation.pdf")) == 1


def test_applies_page_cap_with_warning() -> None:
    v = _validate("long_21_pages.pdf")
    assert v.error_code is None
    assert v.total_pages == 21
    assert v.pages_processed == 20
    assert v.warnings == (PDF_TRUNCATED_WARNING,)
    assert PDF_TRUNCATED_WARNING == "pdf_truncated_to_20_pages"
