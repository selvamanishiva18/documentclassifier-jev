"""Server-side file validation (PRD 6.1): magic bytes, size, count, PDF page count."""

import io
from dataclasses import dataclass

from PIL import Image
from pypdf import PdfReader

from app.errors import ErrorCode

JPEG_MAGIC = b"\xff\xd8\xff"
PDF_MAGIC = b"%PDF-"
PDF_TRUNCATED_WARNING = "pdf_truncated_to_20_pages"


@dataclass
class ValidatedFile:
    filename: str
    size_bytes: int
    mime_type: str | None = None
    data: bytes | None = None
    total_pages: int = 0
    pages_processed: int = 0
    error_code: ErrorCode | None = None
    warnings: tuple[str, ...] = ()


def sniff_mime(head: bytes) -> str | None:
    """Pure-Python magic-byte check; extension is ignored server-side."""
    if head.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if head.startswith(PDF_MAGIC):
        return "application/pdf"
    return None


def count_pdf_pages(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _jpeg_readable(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception:
        return False
    return True


def validate_file(filename: str, data: bytes | None, size_bytes: int, max_bytes: int, max_pages: int) -> ValidatedFile:
    """`data` is None when the upload exceeded `max_bytes` and was not retained."""
    if data is None or size_bytes > max_bytes:
        return ValidatedFile(filename, size_bytes, error_code=ErrorCode.FILE_TOO_LARGE)
    mime = sniff_mime(data[:8])
    if mime is None:
        return ValidatedFile(filename, size_bytes, error_code=ErrorCode.INVALID_FILE_TYPE)
    if mime == "image/jpeg":
        if not _jpeg_readable(data):
            return ValidatedFile(filename, size_bytes, mime, error_code=ErrorCode.CORRUPT_FILE)
        return ValidatedFile(filename, size_bytes, mime, data, total_pages=1, pages_processed=1)
    try:
        pages = count_pdf_pages(data)
    except Exception:
        return ValidatedFile(filename, size_bytes, mime, error_code=ErrorCode.CORRUPT_FILE)
    if pages < 1:
        return ValidatedFile(filename, size_bytes, mime, error_code=ErrorCode.CORRUPT_FILE)
    warnings = (PDF_TRUNCATED_WARNING,) if pages > max_pages else ()
    return ValidatedFile(
        filename, size_bytes, mime, data, total_pages=pages, pages_processed=min(pages, max_pages), warnings=warnings
    )
