import asyncio
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import Settings
from app.errors import DocumentError, ErrorCode
from app.main import create_app
from app.services import retry
from app.services.classification.categories import CATEGORY_KEYS, LABELS
from app.services.classification.jev import ClassificationOutcome
from app.services.extraction.base import ExtractionResult

FIXTURES = Path(__file__).parent / "fixtures"
SENTINEL_JEV_KEY = "sk-jev-SENTINEL-0123456789"
SENTINEL_ANTHROPIC_KEY = "sk-ant-SENTINEL-0123456789"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def has_tesseract() -> bool:
    from app.services.extraction.fast import tesseract_available

    return tesseract_available()


def has_poppler() -> bool:
    return shutil.which("pdftoppm") is not None


requires_tesseract = pytest.mark.skipif(not has_tesseract(), reason="Tesseract binary not installed")
requires_poppler = pytest.mark.skipif(not has_poppler(), reason="Poppler (pdftoppm) not installed")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record backoff delays instead of sleeping."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(retry, "sleep", fake_sleep)
    return delays


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "typesafe_api_key": SecretStr(SENTINEL_JEV_KEY),
        "anthropic_api_key": SecretStr(SENTINEL_ANTHROPIC_KEY),
        "log_level": "INFO",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def uniform_probabilities(choice: str, p: float = 0.9) -> dict[str, float]:
    rest = (1.0 - p) / (len(CATEGORY_KEYS) - 1)
    return {k: (p if k == choice else rest) for k in CATEGORY_KEYS}


class FakeClassifier:
    def __init__(self, choice: str = "invoice_from_supplier", confidence: float = 0.9) -> None:
        self.choice = choice
        self.confidence = confidence
        self.calls: list[tuple[str, str, int]] = []
        self.fail_for: dict[str, ErrorCode] = {}
        self.gate: asyncio.Event | None = None

    async def classify(self, text: str, filename: str, page_count: int) -> ClassificationOutcome:
        self.calls.append((text, filename, page_count))
        if self.gate is not None:
            await self.gate.wait()
        if filename in self.fail_for:
            raise DocumentError(self.fail_for[filename])
        return ClassificationOutcome(
            document_type=self.choice,
            document_type_label=LABELS[self.choice],
            confidence=self.confidence,
            probabilities=uniform_probabilities(self.choice, self.confidence),
            model="jev-1.13.0",
            duration_ms=5,
        )


class FakeExtractor:
    def __init__(
        self, text: str = "TAX INVOICE\nInvoice No: INV-1001\nTotal AUD 10.00", fields: dict[str, str] | None = None
    ) -> None:
        self.text = text
        self.fields = fields
        self.calls: list[str] = []
        self.texts: dict[str, str] = {}
        self.crash_for: set[str] = set()
        self.fail_for: dict[str, ErrorCode] = {}
        self.gate: asyncio.Event | None = None

    async def extract(self, data: bytes, mime_type: str, filename: str, max_pages: int) -> ExtractionResult:
        self.calls.append(filename)
        if self.gate is not None:
            await self.gate.wait()
        if filename in self.crash_for:
            raise ValueError("boom")
        if filename in self.fail_for:
            raise DocumentError(self.fail_for[filename])
        pages = 1 if mime_type == "image/jpeg" else 2
        return ExtractionResult(
            raw_text=self.texts.get(filename, self.text),
            page_count=pages,
            ocr_mean_confidence=91.5,
            fields=self.fields,
        )


AppFactory = Callable[..., FastAPI]


@pytest.fixture
def app_factory() -> AppFactory:
    def _make(
        settings: Settings | None = None,
        classifier: Any = None,
        extractor: Any = None,
        tesseract: bool = True,
    ) -> FastAPI:
        ext = extractor or FakeExtractor()
        return create_app(
            settings or make_settings(),
            classifier=classifier or FakeClassifier(),
            extractors={"fast": ext, "precise": ext},
            tesseract_check=lambda: tesseract,
            run_purge_loop=False,
        )

    return _make


@pytest.fixture
async def client_for() -> AsyncIterator[Callable[[FastAPI], Any]]:
    stack: list[Any] = []

    async def _open(app: FastAPI) -> httpx.AsyncClient:
        ctx = app.router.lifespan_context(app)
        await ctx.__aenter__()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        stack.append((ctx, client))
        return client

    yield _open
    for ctx, client in reversed(stack):
        await client.aclose()
        await ctx.__aexit__(None, None, None)


async def wait_terminal(client: httpx.AsyncClient, batch_id: str) -> dict[str, Any]:
    async with asyncio.timeout(5):
        while True:
            resp = await client.get(f"/api/batches/{batch_id}")
            body: dict[str, Any] = resp.json()
            if body.get("status") in ("completed", "completed_with_errors", "cancelled"):
                return body
            await asyncio.sleep(0.01)


def upload(files: list[tuple[str, bytes]], method: str = "fast") -> dict[str, Any]:
    return {
        "data": {"extraction_method": method},
        "files": [("files", (name, data, "application/octet-stream")) for name, data in files],
    }
