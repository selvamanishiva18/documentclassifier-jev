"""Batch routes (PRD 16.4)."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.datastructures import UploadFile
from ulid import ULID

from app.config import Settings
from app.errors import ApiError, ErrorCode, message_for
from app.schemas import Batch, BatchCreated, BatchCreatedDocument, DocumentMetadata, DocumentResult
from app.services.export import export_csv, export_json
from app.services.processor import BatchProcessor
from app.services.validation import ValidatedFile, validate_file
from app.store import BatchRecord, BatchStore, StoredFile

log = logging.getLogger("docclassify.api")

router = APIRouter(prefix="/batches")

READ_CHUNK = 1024 * 1024
FORM_FILE_FIELDS = ("files[]", "files")
MAX_FORM_PARTS = 1000


def get_store(request: Request) -> BatchStore:
    store: BatchStore = request.app.state.store
    return store


def get_processor(request: Request) -> BatchProcessor:
    processor: BatchProcessor = request.app.state.processor
    return processor


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


StoreDep = Annotated[BatchStore, Depends(get_store)]
ProcessorDep = Annotated[BatchProcessor, Depends(get_processor)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"


def _client_ip(request: Request) -> str:
    # The bundled nginx overwrites X-Real-IP with the peer address, so it is trustworthy behind that proxy.
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _batch_json(batch: Batch, status_code: int = 200) -> JSONResponse:
    return JSONResponse(batch.model_dump(mode="json"), status_code=status_code)


def _require_record(store: BatchStore, batch_id: str) -> BatchRecord:
    record = store.get(batch_id)
    if record is None:
        raise ApiError(ErrorCode.BATCH_NOT_FOUND)
    return record


async def _read_upload(upload: UploadFile, max_bytes: int) -> tuple[bytes | None, int]:
    """Read in chunks; stop retaining bytes once over the limit (the rest is drained to measure size)."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(READ_CHUNK):
        size += len(chunk)
        if size <= max_bytes:
            chunks.append(chunk)
        else:
            chunks.clear()
    await upload.close()
    return (b"".join(chunks) if size <= max_bytes else None), size


@router.post("", status_code=202)
async def create_batch(
    request: Request, store: StoreDep, processor: ProcessorDep, settings: SettingsDep
) -> JSONResponse:
    form = await request.form(max_files=MAX_FORM_PARTS, max_fields=MAX_FORM_PARTS)
    uploads = [f for name in FORM_FILE_FIELDS for f in form.getlist(name) if isinstance(f, UploadFile)]
    method = form.get("extraction_method")

    if not uploads:
        raise ApiError(ErrorCode.NO_FILES)
    if len(uploads) > settings.max_files_per_batch:
        raise ApiError(ErrorCode.TOO_MANY_FILES)
    if method not in ("fast", "precise"):
        raise ApiError(ErrorCode.INVALID_METHOD)
    if method == "precise" and not settings.haiku_configured:
        raise ApiError(ErrorCode.PRECISE_NOT_CONFIGURED)
    limiter = request.app.state.rate_limiter
    if not processor.has_capacity() or not limiter.allowed(_client_ip(request)):
        raise ApiError(ErrorCode.SERVER_BUSY)

    validated: list[ValidatedFile] = []
    for upload in uploads:
        data, size = await _read_upload(upload, settings.max_file_size_bytes)
        filename = upload.filename or "upload"
        validated.append(
            await asyncio.to_thread(
                validate_file, filename, data, size, settings.max_file_size_bytes, settings.max_pdf_pages
            )
        )

    # Re-check after the (possibly slow) reads: another batch may have taken the last slot.
    if not processor.has_capacity():
        raise ApiError(ErrorCode.SERVER_BUSY)

    now = store.clock()
    documents: list[DocumentResult] = []
    files: dict[str, StoredFile] = {}
    for v in validated:
        doc_id = _new_id("d")
        meta = DocumentMetadata(
            mime_type=v.mime_type,
            size_bytes=v.size_bytes,
            page_count=v.pages_processed,
            uploaded_at=now,
        )
        doc = DocumentResult(
            document_id=doc_id, filename=v.filename, status="queued", document_metadata=meta, warnings=list(v.warnings)
        )
        if v.error_code is not None:
            doc.status = "failed"
            doc.error_code = v.error_code.value
            doc.error_message = message_for(v.error_code, v.filename)
        elif v.data is not None and v.mime_type is not None:
            files[doc_id] = StoredFile(v.data, v.mime_type, v.pages_processed)
        documents.append(doc)

    batch = Batch(batch_id=_new_id("b"), status="queued", extraction_method=method, created_at=now, documents=documents)
    record = BatchRecord(batch=batch, files=files)
    store.add(record)
    limiter.record(_client_ip(request))
    log.info("batch created", extra={"batch_id": batch.batch_id, "stage": "queued"})

    if files:
        processor.start(record)
    else:
        processor.finalize(record)  # every file invalid: immediately terminal as completed_with_errors

    created = BatchCreated(
        batch_id=record.batch.batch_id,
        status=record.batch.status,
        documents=[
            BatchCreatedDocument(
                document_id=d.document_id, filename=d.filename, status=d.status, error_code=d.error_code
            )
            for d in record.batch.documents
        ],
    )
    return JSONResponse(created.model_dump(mode="json", exclude_none=True), status_code=202)


@router.get("/{batch_id}")
async def get_batch(batch_id: str, store: StoreDep) -> JSONResponse:
    return _batch_json(_require_record(store, batch_id).batch)


@router.post("/{batch_id}/cancel", status_code=202)
async def cancel_batch(batch_id: str, store: StoreDep) -> JSONResponse:
    record = _require_record(store, batch_id)
    if record.batch.status not in ("queued", "processing"):
        raise ApiError(ErrorCode.BATCH_STATE_CONFLICT)
    record.cancel_requested = True
    log.info("cancel requested", extra={"batch_id": batch_id, "stage": "cancel"})
    return _batch_json(record.batch, 202)


@router.post("/{batch_id}/retry", status_code=202)
async def retry_batch(batch_id: str, store: StoreDep, processor: ProcessorDep) -> JSONResponse:
    record = store.get(batch_id)
    if record is None:
        raise ApiError(ErrorCode.BATCH_EXPIRED if store.was_purged(batch_id) else ErrorCode.BATCH_NOT_FOUND)
    if record.batch.status != "completed_with_errors":
        raise ApiError(ErrorCode.BATCH_STATE_CONFLICT)
    if not any(d.status == "failed" and d.document_id in record.files for d in record.batch.documents):
        # Only file-validation failures remain; their bytes were never retained, so they cannot be re-run.
        raise ApiError(ErrorCode.BATCH_STATE_CONFLICT)
    if not processor.has_capacity():
        raise ApiError(ErrorCode.SERVER_BUSY)
    processor.reopen_for_retry(record)
    processor.start(record)
    log.info("retry started", extra={"batch_id": batch_id, "stage": "retry"})
    return _batch_json(record.batch, 202)


@router.get("/{batch_id}/export.json")
async def export_json_route(batch_id: str, store: StoreDep) -> Response:
    record = _require_record(store, batch_id)
    return Response(
        export_json(record.batch),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="document-results-{batch_id}.json"'},
    )


@router.get("/{batch_id}/export.csv")
async def export_csv_route(batch_id: str, store: StoreDep) -> PlainTextResponse:
    record = _require_record(store, batch_id)
    return PlainTextResponse(
        export_csv(record.batch),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="document-results-{batch_id}.csv"'},
    )


@router.delete("/{batch_id}", status_code=204)
async def delete_batch(batch_id: str, store: StoreDep) -> Response:
    store.remove(batch_id)  # idempotent: deleting an unknown/expired batch is still a 204
    log.info("batch deleted", extra={"batch_id": batch_id, "stage": "delete"})
    return Response(status_code=204)
