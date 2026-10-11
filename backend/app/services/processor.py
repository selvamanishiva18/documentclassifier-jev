"""Per-batch orchestration (PRD 5.0, 6.5, 7.0, 8.0). Documents are processed sequentially in upload order."""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Protocol

from app.errors import DocumentError, ErrorCode, message_for
from app.schemas import Batch, Classification, DocumentResult, Extraction, Summary
from app.services.classification.jev import ClassificationOutcome
from app.services.extraction.base import Extractor, non_whitespace_len
from app.services.fields import heuristic
from app.services.fields.canonical import CANONICAL_FIELDS, filter_fields
from app.store import BatchRecord, BatchStore, StoredFile

log = logging.getLogger("docclassify.processor")

MIN_TEXT_CHARS = 10
TEXT_TRUNCATED_WARNING = "text_truncated_for_classification"


class Classifier(Protocol):
    async def classify(self, text: str, filename: str, page_count: int) -> ClassificationOutcome: ...


class BatchProcessor:
    def __init__(
        self,
        *,
        store: BatchStore,
        classifier: Classifier,
        extractors: dict[str, Extractor],
        text_cap: int,
        max_pages: int,
        ttl_minutes: int,
        max_concurrent: int,
    ) -> None:
        self.store = store
        self.classifier = classifier
        self.extractors = extractors
        self.text_cap = text_cap
        self.max_pages = max_pages
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_concurrent = max_concurrent
        self._running: set[asyncio.Task[None]] = set()

    # ---- concurrency -------------------------------------------------------------------------------------------

    @property
    def running_count(self) -> int:
        return len(self._running)

    def has_capacity(self) -> bool:
        return self.running_count < self.max_concurrent

    def start(self, record: BatchRecord) -> None:
        task = asyncio.create_task(self.run(record), name=f"batch-{record.batch.batch_id}")
        record.task = task
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def shutdown(self) -> None:
        for task in list(self._running):
            task.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)

    # ---- batch lifecycle ----------------------------------------------------------------------------------------

    async def run(self, record: BatchRecord) -> None:
        batch = record.batch
        batch.status = "processing"
        log.info("batch started", extra={"batch_id": batch.batch_id, "stage": "processing"})
        for doc in batch.documents:
            if doc.status != "queued":
                continue
            if record.cancel_requested:
                break
            await self.process_document(record, doc)
        if record.cancel_requested:
            for doc in batch.documents:
                if doc.status == "queued":
                    doc.status = "cancelled"
        self.finalize(record)

    def finalize(self, record: BatchRecord) -> None:
        batch = record.batch
        docs = batch.documents
        completed = [d for d in docs if d.status == "completed"]
        failed = [d for d in docs if d.status == "failed"]
        cancelled = [d for d in docs if d.status == "cancelled"]
        confidences = [d.classification.confidence for d in completed if d.classification is not None]
        duration = sum(
            (d.extraction.duration_ms if d.extraction else 0)
            + (d.classification.duration_ms if d.classification else 0)
            for d in docs
        )
        now = self.store.clock()
        summary = Summary(
            total=len(docs),
            completed=len(completed),
            failed=len(failed),
            cancelled=len(cancelled),
            average_confidence=round(sum(confidences) / len(confidences), 3) if confidences else None,
            total_duration_ms=duration,
        )
        if record.cancel_requested:
            status = "cancelled"
        elif failed:
            status = "completed_with_errors"
        else:
            status = "completed"
        # Assign the batch atomically so the terminal-field invariant holds at every step.
        record.batch = Batch.model_validate(
            {
                **batch.model_dump(exclude={"documents"}),
                "documents": batch.documents,
                "status": status,
                "completed_at": now,
                "expires_at": now + self.ttl,
                "summary": summary,
            }
        )
        record.cancel_requested = False
        log.info(
            "batch finished",
            extra={"batch_id": batch.batch_id, "stage": status, "duration_ms": duration},
        )

    def reopen_for_retry(self, record: BatchRecord) -> list[DocumentResult]:
        """Re-queue failed documents whose original bytes are still held. Returns the re-queued documents."""
        batch = record.batch
        retryable = [d for d in batch.documents if d.status == "failed" and d.document_id in record.files]
        record.batch = Batch.model_validate(
            {
                **batch.model_dump(exclude={"documents"}),
                "documents": batch.documents,
                "status": "queued",
                "completed_at": None,
                "expires_at": None,
                "summary": None,
            }
        )
        for doc in retryable:
            doc.status = "queued"
            doc.error_code = None
            doc.error_message = None
            doc.extraction = None
            doc.classification = None
            doc.extracted_fields = {}
            doc.warnings = [w for w in doc.warnings if w == "pdf_truncated_to_20_pages"]
        return retryable

    # ---- document pipeline --------------------------------------------------------------------------------------

    async def process_document(self, record: BatchRecord, doc: DocumentResult) -> None:
        ids = {"batch_id": record.batch.batch_id, "document_id": doc.document_id}
        stored = record.files.get(doc.document_id)
        try:
            if stored is None:
                raise DocumentError(ErrorCode.INTERNAL_ERROR, "original bytes missing")
            await self._run_pipeline(record, doc, stored)
            doc.status = "completed"
            log.info(
                "document completed",
                extra={**ids, "stage": "completed", "fields_found": len(doc.extracted_fields)},
            )
        except DocumentError as exc:
            self._fail(doc, exc.code)
            log.warning("document failed", extra={**ids, "stage": "failed", "error_code": exc.code.value})
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail(doc, ErrorCode.INTERNAL_ERROR)
            log.exception("document crashed", extra={**ids, "stage": "failed", "error_code": "INTERNAL_ERROR"})

    @staticmethod
    def _fail(doc: DocumentResult, code: ErrorCode) -> None:
        doc.status = "failed"
        doc.error_code = code.value
        doc.error_message = message_for(code, doc.filename)

    async def _run_pipeline(self, record: BatchRecord, doc: DocumentResult, stored: StoredFile) -> None:
        method = record.batch.extraction_method
        extractor = self.extractors.get(method)
        if extractor is None:
            raise DocumentError(ErrorCode.INTERNAL_ERROR, f"no extractor for {method}")

        # 1. extract
        doc.status = "extracting"
        started = time.perf_counter()
        result = await extractor.extract(stored.data, stored.mime_type, doc.filename, self.max_pages)
        extraction_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "extracted",
            extra={
                "batch_id": record.batch.batch_id,
                "document_id": doc.document_id,
                "stage": "extracting",
                "duration_ms": extraction_ms,
            },
        )

        raw_text = result.raw_text or ""
        truncated = len(raw_text) > self.text_cap
        classification_text = raw_text[: self.text_cap]
        for w in result.warnings:
            if w not in doc.warnings:
                doc.warnings.append(w)
        if truncated:
            doc.warnings.append(TEXT_TRUNCATED_WARNING)
        doc.document_metadata.page_count = result.page_count
        doc.extraction = Extraction(
            method=method,
            duration_ms=extraction_ms,
            ocr_mean_confidence=result.ocr_mean_confidence if method == "fast" else None,
            raw_text=classification_text,
            truncated_for_classification=truncated,
        )

        # 2. text gate
        if non_whitespace_len(raw_text) < MIN_TEXT_CHARS:
            raise DocumentError(ErrorCode.EMPTY_TEXT)

        # 3. fields (Precise: from the same Haiku call; Fast: heuristic over the full raw text)
        fields = result.fields if result.fields is not None else heuristic.extract(raw_text)
        extracted = filter_fields(fields)

        # 4. classify
        doc.status = "classifying"
        outcome = await self.classifier.classify(classification_text, doc.filename, result.page_count)
        for w in outcome.warnings:
            if w not in doc.warnings:
                doc.warnings.append(w)
        doc.classification = Classification(
            document_type=outcome.document_type,
            document_type_label=outcome.document_type_label,
            confidence=outcome.confidence,
            probabilities=outcome.probabilities,
            model=outcome.model,
            duration_ms=outcome.duration_ms,
        )
        doc.extracted_fields = {k: extracted[k] for k in CANONICAL_FIELDS if k in extracted}
