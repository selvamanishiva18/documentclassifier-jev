"""JSON / CSV export builders (PRD 6.4, 16.4)."""

import csv
import io
import json
from typing import Any

from app.schemas import TERMINAL_DOCUMENT_STATUSES, Batch
from app.services.fields.canonical import CANONICAL_FIELDS

CSV_HEADER: tuple[str, ...] = (
    "filename",
    "status",
    "document_type",
    "document_type_label",
    "confidence",
    "extraction_method",
    *CANONICAL_FIELDS,
    "warnings",
    "error_code",
)


def export_batch(batch: Batch) -> dict[str, Any]:
    """The batch object, restricted to documents that are terminal at call time."""
    data = batch.model_dump(mode="json")
    data["documents"] = [d for d in data["documents"] if d["status"] in TERMINAL_DOCUMENT_STATUSES]
    return data


def export_json(batch: Batch) -> str:
    return json.dumps(export_batch(batch), indent=2, ensure_ascii=False)


def export_csv(batch: Batch) -> str:
    buf = io.StringIO(newline="")
    # RFC 4180: comma separator, CRLF line endings, quote only fields containing , " or newlines.
    writer = csv.writer(buf, dialect="excel", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for doc in batch.documents:
        if doc.status not in TERMINAL_DOCUMENT_STATUSES:
            continue
        cls = doc.classification
        row: list[str] = [
            doc.filename,
            doc.status,
            cls.document_type if cls else "",
            cls.document_type_label if cls else "",
            repr(cls.confidence) if cls else "",
            batch.extraction_method,
            *(doc.extracted_fields.get(k, "") for k in CANONICAL_FIELDS),
            ";".join(doc.warnings),
            doc.error_code or "",
        ]
        writer.writerow(row)
    return buf.getvalue()
