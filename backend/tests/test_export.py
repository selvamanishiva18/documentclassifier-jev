import csv
import io
import json
from datetime import UTC, datetime

from app.schemas import Batch, Classification, DocumentMetadata, DocumentResult, Extraction, Summary
from app.services.export import CSV_HEADER, export_batch, export_csv, export_json
from tests.conftest import uniform_probabilities

T0 = datetime(2026, 10, 4, 3, 12, 45, 120000, tzinfo=UTC)

EXPECTED_HEADER = (
    "filename,status,document_type,document_type_label,confidence,extraction_method,document_number,document_date,"
    "due_date,issuer_name,recipient_name,reference_number,subtotal,tax_amount,total_amount,currency,payment_terms,"
    "line_items_summary,warnings,error_code"
)


def _meta() -> DocumentMetadata:
    return DocumentMetadata(mime_type="application/pdf", size_bytes=10, page_count=1, uploaded_at=T0)


def make_batch(status: str = "completed_with_errors") -> Batch:
    done = DocumentResult(
        document_id="d_1",
        filename="inv_0412.pdf",
        status="completed",
        warnings=["pdf_truncated_to_20_pages", "text_truncated_for_classification"],
        document_metadata=_meta(),
        extraction=Extraction(
            method="precise", duration_ms=10, ocr_mean_confidence=None, raw_text="x", truncated_for_classification=False
        ),
        classification=Classification(
            document_type="invoice_from_supplier",
            document_type_label="Invoice from Supplier",
            confidence=0.91,
            probabilities=uniform_probabilities("invoice_from_supplier", 0.91),
            model="jev-1.13.0",
            duration_ms=5,
        ),
        extracted_fields={
            "document_number": "INV-2026-0412",
            "issuer_name": 'Acme "Best", Supplies',
            "line_items_summary": "2 line items: A x1;\nB x2",
            "total_amount": "1,298.00",
        },
    )
    failed = DocumentResult(
        document_id="d_2",
        filename="scan003.jpg",
        status="failed",
        error_code="EMPTY_TEXT",
        error_message="No readable text was found in scan003.jpg.",
        document_metadata=_meta(),
    )
    terminal = status in ("completed", "completed_with_errors", "cancelled")
    return Batch(
        batch_id="b_1",
        status=status,
        extraction_method="precise",
        created_at=T0,
        completed_at=T0 if terminal else None,
        expires_at=T0 if terminal else None,
        summary=Summary(total=2, completed=1, failed=1, cancelled=0, average_confidence=0.91, total_duration_ms=15)
        if terminal
        else None,
        documents=[done, failed],
    )


def test_json_equals_store_object() -> None:
    batch = make_batch()
    assert json.loads(export_json(batch)) == batch.model_dump(mode="json")
    assert export_json(batch).startswith('{\n  "batch_id"')  # 2-space pretty print


def test_json_timestamps_iso_ms_z() -> None:
    data = export_batch(make_batch())
    assert data["created_at"] == "2026-10-04T03:12:45.120Z"


def test_json_excludes_non_terminal_documents() -> None:
    batch = make_batch(status="processing")
    batch.documents[1].status = "extracting"
    batch.documents[1].error_code = None
    data = export_batch(batch)
    assert [d["document_id"] for d in data["documents"]] == ["d_1"]


def test_csv_header_exact() -> None:
    assert ",".join(CSV_HEADER) == EXPECTED_HEADER
    assert export_csv(make_batch()).split("\r\n")[0] == EXPECTED_HEADER


def test_csv_rows_and_quoting() -> None:
    text = export_csv(make_batch())
    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert len(rows) == 3
    header, done, failed = rows
    row = dict(zip(header, done, strict=True))
    assert row["filename"] == "inv_0412.pdf"
    assert row["status"] == "completed"
    assert row["document_type"] == "invoice_from_supplier"
    assert row["document_type_label"] == "Invoice from Supplier"
    assert row["confidence"] == "0.91"
    assert row["extraction_method"] == "precise"
    assert row["issuer_name"] == 'Acme "Best", Supplies'
    assert row["line_items_summary"] == "2 line items: A x1;\nB x2"
    assert row["warnings"] == "pdf_truncated_to_20_pages;text_truncated_for_classification"
    assert row["due_date"] == ""
    assert '"Acme ""Best"", Supplies"' in text  # RFC 4180 quote escaping
    frow = dict(zip(header, failed, strict=True))
    assert frow["status"] == "failed"
    assert frow["error_code"] == "EMPTY_TEXT"
    assert frow["document_type"] == "" and frow["confidence"] == ""
    assert frow["extraction_method"] == "precise"


def test_csv_header_only_when_no_terminal_docs() -> None:
    batch = make_batch(status="processing")
    for d in batch.documents:
        d.status = "queued"
        d.error_code = None
    assert export_csv(batch) == EXPECTED_HEADER + "\r\n"
