import asyncio
from collections.abc import MutableMapping
from datetime import timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.api import limits
from app.errors import ErrorCode
from app.main import ConfigurationError, create_app
from app.services.extraction.base import ExtractionResult
from tests.conftest import (
    SENTINEL_ANTHROPIC_KEY,
    SENTINEL_JEV_KEY,
    FakeClassifier,
    FakeExtractor,
    fixture_bytes,
    make_settings,
    upload,
    wait_terminal,
)


def files(*names: str) -> list[tuple[str, bytes]]:
    return [(n, fixture_bytes(n)) for n in names]


def assert_error(resp: httpx.Response, status: int, code: ErrorCode) -> None:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["error_code"] == code.value
    assert body["error_message"]


async def test_happy_path(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files("receipt.jpg", "invoice.pdf")))
    assert resp.status_code == 202
    created = resp.json()
    assert created["batch_id"].startswith("b_")
    assert created["status"] in ("queued", "processing")
    assert [d["filename"] for d in created["documents"]] == ["receipt.jpg", "invoice.pdf"]
    assert all(d["document_id"].startswith("d_") and "error_code" not in d for d in created["documents"])

    batch = await wait_terminal(client, created["batch_id"])
    assert batch["status"] == "completed"
    assert batch["extraction_method"] == "fast"
    assert batch["created_at"].endswith("Z")
    assert batch["summary"]["total"] == 2 and batch["summary"]["completed"] == 2
    doc = batch["documents"][0]
    assert set(doc) >= {"document_metadata", "extraction", "classification", "extracted_fields"}
    assert doc["document_metadata"]["mime_type"] == "image/jpeg"
    assert doc["classification"]["document_type"] == "invoice_from_supplier"
    assert batch["documents"][1]["document_metadata"]["mime_type"] == "application/pdf"


async def test_files_array_field_name_also_accepted(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post(
        "/api/batches",
        data={"extraction_method": "fast"},
        files=[("files[]", ("receipt.jpg", fixture_bytes("receipt.jpg"), "image/jpeg"))],
    )
    assert resp.status_code == 202


async def test_no_files(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", data={"extraction_method": "fast"}, files=[])
    assert_error(resp, 400, ErrorCode.NO_FILES)


async def test_too_many_files(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files(*["receipt.jpg"] * 21)))
    assert_error(resp, 400, ErrorCode.TOO_MANY_FILES)


@pytest.mark.parametrize("method", ["", "slow", "FAST"])
async def test_invalid_method(app_factory: Any, client_for: Any, method: str) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files("receipt.jpg"), method=method))
    assert_error(resp, 400, ErrorCode.INVALID_METHOD)


async def test_body_too_large(app_factory: Any, client_for: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "UPLOAD_BODY_LIMIT_BYTES", 50_000)
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files("receipt.jpg")))  # ~75 KB
    assert_error(resp, 413, ErrorCode.UPLOAD_TOO_LARGE)
    assert resp.json()["error_message"] == "The upload is too large. Keep the total under 220 MB."


async def test_body_too_large_while_streaming() -> None:
    """No Content-Length header: the limit is enforced on received bytes."""
    sent: list[MutableMapping[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        while (await receive()).get("more_body"):
            pass

    mw = limits.BodySizeLimitMiddleware(inner, limit_bytes=10)
    chunks = [{"type": "http.request", "body": b"x" * 8, "more_body": True}] * 3

    async def receive() -> dict[str, Any]:
        return chunks.pop(0)

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await mw({"type": "http", "headers": []}, receive, send)
    assert sent[0]["status"] == 413


async def test_precise_without_key(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory(make_settings(anthropic_api_key=SecretStr(""))))
    resp = await client.post("/api/batches", **upload(files("receipt.jpg"), method="precise"))
    assert_error(resp, 503, ErrorCode.PRECISE_NOT_CONFIGURED)


async def test_sixth_concurrent_batch_is_busy(app_factory: Any, client_for: Any) -> None:
    ext = FakeExtractor()
    ext.gate = asyncio.Event()
    client = await client_for(app_factory(extractor=ext))
    for _ in range(5):
        assert (await client.post("/api/batches", **upload(files("receipt.jpg")))).status_code == 202
    resp = await client.post("/api/batches", **upload(files("receipt.jpg")))
    assert_error(resp, 429, ErrorCode.SERVER_BUSY)
    ext.gate.set()


async def test_rate_limit_per_ip(app_factory: Any, client_for: Any) -> None:
    app = app_factory()
    app.state.rate_limiter.limit = 2
    client = await client_for(app)
    for _ in range(2):
        resp = await client.post("/api/batches", **upload(files("receipt.jpg")))
        await wait_terminal(client, resp.json()["batch_id"])
    resp = await client.post("/api/batches", **upload(files("receipt.jpg")))
    assert_error(resp, 429, ErrorCode.SERVER_BUSY)
    other = await client.post("/api/batches", headers={"x-real-ip": "10.0.0.9"}, **upload(files("receipt.jpg")))
    assert other.status_code == 202


async def test_mixed_valid_and_renamed_png(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files("receipt.jpg", "renamed_png.jpg")))
    assert resp.status_code == 202
    docs = resp.json()["documents"]
    assert docs[1]["status"] == "failed" and docs[1]["error_code"] == "INVALID_FILE_TYPE"
    batch = await wait_terminal(client, resp.json()["batch_id"])
    assert batch["status"] == "completed_with_errors"
    png = batch["documents"][1]
    assert png["error_message"] == "Only JPG, JPEG, and PDF files are supported."
    assert batch["documents"][0]["status"] == "completed"


async def test_per_file_size_and_corrupt(app_factory: Any, client_for: Any) -> None:
    settings = make_settings(max_file_size_mb=0)  # every non-empty file is "too large"
    client = await client_for(app_factory(settings))
    resp = await client.post("/api/batches", **upload(files("receipt.jpg")))
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "completed_with_errors"  # all invalid: immediately terminal
    assert body["documents"][0]["error_code"] == "FILE_TOO_LARGE"
    batch = (await client.get(f"/api/batches/{body['batch_id']}")).json()
    assert batch["documents"][0]["error_message"] == "receipt.jpg is larger than 10 MB and was skipped."
    assert batch["summary"]["failed"] == 1

    client2 = await client_for(app_factory())
    resp = await client2.post("/api/batches", **upload(files("corrupt.pdf")))
    assert resp.json()["documents"][0]["error_code"] == "CORRUPT_FILE"


async def test_pdf_truncation_warning(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files("long_21_pages.pdf")))
    batch = await wait_terminal(client, resp.json()["batch_id"])
    assert batch["documents"][0]["warnings"] == ["pdf_truncated_to_20_pages"]


async def test_get_during_processing_returns_full_object(app_factory: Any, client_for: Any) -> None:
    cls = FakeClassifier()
    ext = FakeExtractor()
    ext.texts = {}
    client = await client_for(app_factory(classifier=cls, extractor=ext))
    gate = asyncio.Event()

    original = ext.extract

    async def gated(data: bytes, mime_type: str, filename: str, max_pages: int) -> ExtractionResult:
        if filename == "invoice.pdf":
            await gate.wait()
        return await original(data, mime_type, filename, max_pages)

    ext.extract = gated  # type: ignore[method-assign]
    resp = await client.post("/api/batches", **upload(files("receipt.jpg", "invoice.pdf", "quotation.pdf")))
    batch_id = resp.json()["batch_id"]
    for _ in range(200):
        body = (await client.get(f"/api/batches/{batch_id}")).json()
        if body["documents"][1]["status"] == "extracting":
            break
        await asyncio.sleep(0.005)
    assert body["status"] == "processing"
    assert body["summary"] is None and body["completed_at"] is None
    assert body["documents"][0]["status"] == "completed"
    assert body["documents"][0]["classification"] is not None
    assert body["documents"][1]["status"] == "extracting"
    assert body["documents"][2]["status"] == "queued"

    partial = (await client.get(f"/api/batches/{batch_id}/export.json")).json()
    assert [d["filename"] for d in partial["documents"]] == ["receipt.jpg"]
    gate.set()
    await wait_terminal(client, batch_id)


async def test_404_unknown_and_after_purge(app_factory: Any, client_for: Any) -> None:
    app = app_factory()
    client = await client_for(app)
    assert_error(await client.get("/api/batches/b_nope"), 404, ErrorCode.BATCH_NOT_FOUND)
    resp = await client.post("/api/batches", **upload(files("receipt.jpg")))
    batch_id = resp.json()["batch_id"]
    batch = await wait_terminal(client, batch_id)
    assert batch["expires_at"]
    store = app.state.store
    real_clock = store.clock
    store.clock = lambda: real_clock() + timedelta(minutes=15, seconds=1)
    store.purge_expired()
    assert_error(await client.get(f"/api/batches/{batch_id}"), 404, ErrorCode.BATCH_NOT_FOUND)
    assert_error(await client.get(f"/api/batches/{batch_id}/export.csv"), 404, ErrorCode.BATCH_NOT_FOUND)
    assert_error(await client.post(f"/api/batches/{batch_id}/retry"), 410, ErrorCode.BATCH_EXPIRED)


async def test_cancel(app_factory: Any, client_for: Any) -> None:
    ext = FakeExtractor()
    ext.gate = asyncio.Event()
    client = await client_for(app_factory(extractor=ext))
    resp = await client.post("/api/batches", **upload(files("receipt.jpg", "invoice.pdf", "quotation.pdf")))
    batch_id = resp.json()["batch_id"]
    await asyncio.sleep(0.01)
    cancel = await client.post(f"/api/batches/{batch_id}/cancel")
    assert cancel.status_code == 202
    assert cancel.json()["batch_id"] == batch_id
    ext.gate.set()
    batch = await wait_terminal(client, batch_id)
    assert batch["status"] == "cancelled"
    assert [d["status"] for d in batch["documents"]] == ["completed", "cancelled", "cancelled"]
    assert_error(await client.post(f"/api/batches/{batch_id}/cancel"), 409, ErrorCode.BATCH_STATE_CONFLICT)


async def test_retry_conflicts_and_success(app_factory: Any, client_for: Any) -> None:
    cls = FakeClassifier()
    cls.fail_for = {"invoice.pdf": ErrorCode.JEV_UNAVAILABLE}
    cls.gate = asyncio.Event()
    client = await client_for(app_factory(classifier=cls))
    resp = await client.post("/api/batches", **upload(files("receipt.jpg", "invoice.pdf")))
    batch_id = resp.json()["batch_id"]
    await asyncio.sleep(0.01)
    assert_error(await client.post(f"/api/batches/{batch_id}/retry"), 409, ErrorCode.BATCH_STATE_CONFLICT)
    cls.gate.set()
    batch = await wait_terminal(client, batch_id)
    assert batch["status"] == "completed_with_errors"
    assert batch["documents"][1]["error_message"] == (
        "The classification service is temporarily unavailable. Try again in a few minutes."
    )

    cls.fail_for = {}
    cls.calls.clear()
    retry = await client.post(f"/api/batches/{batch_id}/retry")
    assert retry.status_code == 202
    assert retry.json()["documents"][1]["status"] in ("queued", "extracting", "classifying", "completed")
    batch = await wait_terminal(client, batch_id)
    assert batch["status"] == "completed"
    assert [c[1] for c in cls.calls] == ["invoice.pdf"]
    assert_error(await client.post(f"/api/batches/{batch_id}/retry"), 409, ErrorCode.BATCH_STATE_CONFLICT)


async def test_retry_with_only_validation_failures_conflicts(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files("receipt.jpg", "renamed_png.jpg")))
    batch_id = resp.json()["batch_id"]
    await wait_terminal(client, batch_id)
    assert_error(await client.post(f"/api/batches/{batch_id}/retry"), 409, ErrorCode.BATCH_STATE_CONFLICT)


async def test_exports(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory())
    resp = await client.post("/api/batches", **upload(files("receipt.jpg")))
    batch_id = resp.json()["batch_id"]
    batch = await wait_terminal(client, batch_id)

    j = await client.get(f"/api/batches/{batch_id}/export.json")
    assert j.status_code == 200
    assert j.headers["content-type"].startswith("application/json")
    assert j.headers["content-disposition"] == f'attachment; filename="document-results-{batch_id}.json"'
    assert j.json() == batch

    c = await client.get(f"/api/batches/{batch_id}/export.csv")
    assert c.status_code == 200
    assert c.headers["content-type"] == "text/csv; charset=utf-8"
    assert c.headers["content-disposition"] == f'attachment; filename="document-results-{batch_id}.csv"'
    assert c.text.startswith("filename,status,document_type,")


async def test_delete_purges_immediately(app_factory: Any, client_for: Any) -> None:
    app = app_factory()
    client = await client_for(app)
    resp = await client.post("/api/batches", **upload(files("receipt.jpg")))
    batch_id = resp.json()["batch_id"]
    await wait_terminal(client, batch_id)
    d = await client.delete(f"/api/batches/{batch_id}")
    assert d.status_code == 204 and d.content == b""
    assert app.state.store.get(batch_id) is None
    assert_error(await client.get(f"/api/batches/{batch_id}"), 404, ErrorCode.BATCH_NOT_FOUND)


async def test_health(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory(tesseract=True))
    body = (await client.get("/api/health")).json()
    assert body == {
        "status": "ok",
        "tesseract": True,
        "jev_configured": True,
        "haiku_configured": True,
        "version": "1.0.0",
    }
    client2 = await client_for(app_factory(make_settings(anthropic_api_key=SecretStr("")), tesseract=False))
    body2 = (await client2.get("/api/health")).json()
    assert body2["tesseract"] is False and body2["haiku_configured"] is False


async def test_refuses_to_start_without_jev_key() -> None:
    app = create_app(make_settings(typesafe_api_key=SecretStr("")), run_purge_loop=False, tesseract_check=lambda: True)
    with pytest.raises(ConfigurationError):
        async with app.router.lifespan_context(app):
            pass


async def test_cors_restricted(app_factory: Any, client_for: Any) -> None:
    client = await client_for(app_factory(make_settings(allowed_origins="http://good.example")))
    ok = await client.get("/api/health", headers={"Origin": "http://good.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://good.example"
    bad = await client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


async def test_api_keys_never_in_responses_or_logs(
    app_factory: Any, client_for: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    cls = FakeClassifier()
    cls.fail_for = {"invoice.pdf": ErrorCode.JEV_AUTH_ERROR}
    ext = FakeExtractor()
    ext.crash_for = {"quotation.pdf"}
    client = await client_for(app_factory(classifier=cls, extractor=ext))
    bodies: list[str] = []
    resp = await client.post("/api/batches", **upload(files("receipt.jpg", "invoice.pdf", "quotation.pdf")))
    bodies.append(resp.text)
    batch_id = resp.json()["batch_id"]
    await wait_terminal(client, batch_id)
    for path in ("", "/export.json", "/export.csv"):
        bodies.append((await client.get(f"/api/batches/{batch_id}{path}")).text)
    bodies.append((await client.get("/api/health")).text)
    bodies.append((await client.post("/api/batches", data={"extraction_method": "x"}, files=[])).text)
    logs = capsys.readouterr().out
    assert logs  # structured logs were emitted
    for text in [*bodies, logs]:
        assert SENTINEL_JEV_KEY not in text
        assert SENTINEL_ANTHROPIC_KEY not in text
        assert "Traceback" not in text
    # logs exclude document content
    assert "INV-1001" not in logs and "TAX INVOICE" not in logs
