import asyncio
from datetime import UTC, datetime, timedelta

from app.errors import ErrorCode
from app.schemas import Batch, DocumentMetadata, DocumentResult
from app.services.processor import BatchProcessor
from app.store import BatchRecord, BatchStore, StoredFile
from tests.conftest import FakeClassifier, FakeExtractor

T0 = datetime(2026, 10, 4, 3, 12, 45, 120000, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def make_record(names: list[str], method: str = "fast") -> BatchRecord:
    docs = []
    files = {}
    for i, name in enumerate(names):
        doc_id = f"d_{i}"
        mime = "application/pdf" if name.endswith(".pdf") else "image/jpeg"
        docs.append(
            DocumentResult(
                document_id=doc_id,
                filename=name,
                status="queued",
                document_metadata=DocumentMetadata(mime_type=mime, size_bytes=100, page_count=1, uploaded_at=T0),
            )
        )
        files[doc_id] = StoredFile(b"data", mime, 1)
    batch = Batch(batch_id="b_1", status="queued", extraction_method=method, created_at=T0, documents=docs)
    return BatchRecord(batch=batch, files=files)


def status_of(obj: Batch | DocumentResult) -> str:
    """Read status without mypy narrowing it from an earlier assert."""
    return obj.status


def make_processor(
    classifier: FakeClassifier | None = None, extractor: FakeExtractor | None = None, clock: Clock | None = None
) -> tuple[BatchProcessor, BatchStore]:
    store = BatchStore(clock=clock or Clock())
    ext = extractor or FakeExtractor()
    proc = BatchProcessor(
        store=store,
        classifier=classifier or FakeClassifier(),
        extractors={"fast": ext, "precise": ext},
        text_cap=20000,
        max_pages=20,
        ttl_minutes=15,
        max_concurrent=5,
    )
    return proc, store


async def test_sequential_order_preserved() -> None:
    ext = FakeExtractor()
    cls = FakeClassifier()
    proc, store = make_processor(cls, ext)
    rec = make_record(["a.jpg", "b.pdf", "c.jpg"])
    store.add(rec)
    await proc.run(rec)
    assert ext.calls == ["a.jpg", "b.pdf", "c.jpg"]
    assert [c[1] for c in cls.calls] == ["a.jpg", "b.pdf", "c.jpg"]
    assert rec.batch.status == "completed"
    assert [d.status for d in rec.batch.documents] == ["completed"] * 3


async def test_completed_document_shape() -> None:
    proc, _ = make_processor()
    rec = make_record(["inv.pdf"])
    await proc.run(rec)
    doc = rec.batch.documents[0]
    assert doc.extraction is not None and doc.extraction.method == "fast"
    assert doc.extraction.ocr_mean_confidence == 91.5
    assert doc.document_metadata.page_count == 2
    assert doc.classification is not None and doc.classification.model == "jev-1.13.0"
    assert doc.extracted_fields == {
        "document_number": "INV-1001",
        "issuer_name": "TAX INVOICE",
        "total_amount": "10.00",
        "currency": "AUD",
    }
    assert doc.error_code is None and doc.warnings == []


async def test_precise_fields_used_and_ocr_conf_null() -> None:
    ext = FakeExtractor(fields={"total_amount": "5.00", "bogus": "x"})
    proc, _ = make_processor(extractor=ext)
    rec = make_record(["a.jpg"], method="precise")
    await proc.run(rec)
    doc = rec.batch.documents[0]
    assert doc.extracted_fields == {"total_amount": "5.00"}
    assert doc.extraction is not None and doc.extraction.ocr_mean_confidence is None


async def test_one_failing_doc_does_not_stop_batch() -> None:
    ext = FakeExtractor()
    ext.crash_for = {"b.jpg"}
    cls = FakeClassifier()
    cls.fail_for = {"c.jpg": ErrorCode.JEV_UNAVAILABLE}
    proc, _ = make_processor(cls, ext)
    rec = make_record(["a.jpg", "b.jpg", "c.jpg", "d.jpg"])
    await proc.run(rec)
    statuses = [(d.status, d.error_code) for d in rec.batch.documents]
    assert statuses == [
        ("completed", None),
        ("failed", "INTERNAL_ERROR"),
        ("failed", "JEV_UNAVAILABLE"),
        ("completed", None),
    ]
    assert rec.batch.documents[1].error_message == "Something went wrong processing b.jpg. Try again."
    assert rec.batch.status == "completed_with_errors"


async def test_empty_text_fails_without_calling_jev() -> None:
    ext = FakeExtractor(text="  a b c  \n ")
    cls = FakeClassifier()
    proc, _ = make_processor(cls, ext)
    rec = make_record(["blank.jpg"])
    await proc.run(rec)
    doc = rec.batch.documents[0]
    assert doc.status == "failed"
    assert doc.error_code == "EMPTY_TEXT"
    assert doc.error_message == "No readable text was found in blank.jpg."
    assert cls.calls == []


async def test_text_gate_boundary_ten_chars_passes() -> None:
    ext = FakeExtractor(text="0123456789")
    proc, _ = make_processor(extractor=ext)
    rec = make_record(["x.jpg"])
    await proc.run(rec)
    assert rec.batch.documents[0].status == "completed"


async def test_classification_text_cap_and_warning() -> None:
    ext = FakeExtractor(text="x" * 25000)
    cls = FakeClassifier()
    proc, _ = make_processor(cls, ext)
    rec = make_record(["long.pdf"])
    await proc.run(rec)
    doc = rec.batch.documents[0]
    assert len(cls.calls[0][0]) == 20000
    assert doc.extraction is not None and len(doc.extraction.raw_text) == 20000
    assert doc.extraction.truncated_for_classification is True
    assert doc.warnings == ["text_truncated_for_classification"]


async def test_status_transitions_through_stages() -> None:
    ext = FakeExtractor()
    ext.gate = asyncio.Event()
    cls = FakeClassifier()
    cls.gate = asyncio.Event()
    proc, _ = make_processor(cls, ext)
    rec = make_record(["a.jpg"])
    task = asyncio.create_task(proc.run(rec))
    await asyncio.sleep(0)
    assert rec.batch.status == "processing"
    assert rec.batch.documents[0].status == "extracting"
    ext.gate.set()
    await asyncio.sleep(0.01)
    assert status_of(rec.batch.documents[0]) == "classifying"
    cls.gate.set()
    await task
    assert status_of(rec.batch.documents[0]) == "completed"


async def test_cancel_after_current_document() -> None:
    ext = FakeExtractor()
    ext.gate = asyncio.Event()
    proc, _ = make_processor(extractor=ext)
    rec = make_record(["a.jpg", "b.jpg", "c.jpg"])
    task = asyncio.create_task(proc.run(rec))
    await asyncio.sleep(0)
    rec.cancel_requested = True
    ext.gate.set()
    await task
    assert [d.status for d in rec.batch.documents] == ["completed", "cancelled", "cancelled"]
    assert rec.batch.status == "cancelled"
    assert rec.batch.summary is not None
    assert (rec.batch.summary.completed, rec.batch.summary.cancelled) == (1, 2)


async def test_summary_and_expiry() -> None:
    cls = FakeClassifier(confidence=0.9)
    clock = Clock()
    proc, _ = make_processor(cls, clock=clock)
    ext = proc.extractors["fast"]
    assert isinstance(ext, FakeExtractor)
    ext.crash_for = {"c.jpg"}
    rec = make_record(["a.jpg", "b.jpg", "c.jpg"])
    await proc.run(rec)
    s = rec.batch.summary
    assert s is not None
    assert (s.total, s.completed, s.failed, s.cancelled) == (3, 2, 1, 0)
    assert s.average_confidence == 0.9
    assert rec.batch.completed_at == T0
    assert rec.batch.expires_at == T0 + timedelta(minutes=15)


async def test_average_confidence_null_when_none_completed() -> None:
    ext = FakeExtractor(text="")
    proc, _ = make_processor(extractor=ext)
    rec = make_record(["a.jpg"])
    await proc.run(rec)
    assert rec.batch.summary is not None and rec.batch.summary.average_confidence is None
    assert rec.batch.status == "completed_with_errors"


async def test_average_confidence_three_dp() -> None:
    proc, _ = make_processor(FakeClassifier(confidence=0.91234))
    rec = make_record(["a.jpg"])
    await proc.run(rec)
    assert rec.batch.summary is not None and rec.batch.summary.average_confidence == 0.912


async def test_retry_requeues_only_failed() -> None:
    cls = FakeClassifier()
    cls.fail_for = {"b.jpg": ErrorCode.JEV_UNAVAILABLE}
    ext = FakeExtractor()
    proc, _ = make_processor(cls, ext)
    rec = make_record(["a.jpg", "b.jpg"])
    await proc.run(rec)
    assert rec.batch.status == "completed_with_errors"

    cls.fail_for = {}
    ext.calls.clear()
    requeued = proc.reopen_for_retry(rec)
    assert [d.filename for d in requeued] == ["b.jpg"]
    assert status_of(rec.batch) == "queued"
    assert rec.batch.completed_at is None and rec.batch.summary is None
    await proc.run(rec)
    assert ext.calls == ["b.jpg"]
    assert [d.status for d in rec.batch.documents] == ["completed", "completed"]
    assert status_of(rec.batch) == "completed"


async def test_ttl_purge_removes_batch() -> None:
    clock = Clock()
    proc, store = make_processor(clock=clock)
    rec = make_record(["a.jpg"])
    store.add(rec)
    await proc.run(rec)
    clock.now = T0 + timedelta(minutes=14, seconds=59)
    assert store.purge_expired() == []
    assert store.get("b_1") is not None
    clock.now = T0 + timedelta(minutes=15)
    assert store.purge_expired() == ["b_1"]
    assert store.get("b_1") is None
    assert store.was_purged("b_1")
    assert rec.files == {}


async def test_purge_ignores_running_batches() -> None:
    clock = Clock()
    _, store = make_processor(clock=clock)
    store.add(make_record(["a.jpg"]))
    clock.now = T0 + timedelta(days=1)
    assert store.purge_expired() == []


async def test_concurrency_limit() -> None:
    ext = FakeExtractor()
    ext.gate = asyncio.Event()
    proc, _ = make_processor(extractor=ext)
    proc.max_concurrent = 2
    records = [make_record(["a.jpg"]) for _ in range(2)]
    for r in records:
        proc.start(r)
    assert not proc.has_capacity()
    ext.gate.set()
    await asyncio.gather(*(r.task for r in records if r.task))
    assert proc.has_capacity()


async def test_missing_bytes_is_internal_error() -> None:
    proc, _ = make_processor()
    rec = make_record(["a.jpg"])
    rec.files.clear()
    await proc.run(rec)
    assert rec.batch.documents[0].error_code == "INTERNAL_ERROR"
