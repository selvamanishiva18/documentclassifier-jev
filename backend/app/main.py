"""FastAPI app: CORS, routers, lifespan (config check, cleanup scheduler)."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import batches, health
from app.api.limits import BodySizeLimitMiddleware, RateLimiter
from app.config import Settings, get_settings
from app.errors import ApiError, ErrorCode, message_for
from app.logging import configure_logging
from app.services.classification.jev import JevClassifier
from app.services.extraction.base import Extractor
from app.services.extraction.fast import FastExtractor, tesseract_available
from app.services.extraction.precise import PreciseExtractor
from app.services.processor import BatchProcessor, Classifier
from app.store import BatchStore

log = logging.getLogger("docclassify")


class ConfigurationError(RuntimeError):
    pass


def _error(code: ErrorCode, status: int) -> JSONResponse:
    return JSONResponse({"error_code": code.value, "error_message": message_for(code)}, status_code=status)


def create_app(
    settings: Settings | None = None,
    *,
    classifier: Classifier | None = None,
    extractors: dict[str, Extractor] | None = None,
    tesseract_check: Callable[[], bool] = tesseract_available,
    run_purge_loop: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not settings.jev_configured:
            log.error("configuration error: TYPESAFE_API_KEY is not set; refusing to start")
            raise ConfigurationError("TYPESAFE_API_KEY is required")
        owned: list[JevClassifier | PreciseExtractor] = []
        jev = classifier
        if jev is None:
            jev = JevClassifier(
                api_key=settings.typesafe_api_key.get_secret_value(),
                base_url=settings.typesafe_base_url,
                model=settings.jev_model,
            )
            owned.append(jev)
        exts = extractors
        if exts is None:
            exts = {"fast": FastExtractor(settings.tesseract_cmd)}
            if settings.haiku_configured:
                precise = PreciseExtractor(
                    api_key=settings.anthropic_api_key.get_secret_value(), model=settings.haiku_model
                )
                exts["precise"] = precise
                owned.append(precise)
        if not await asyncio.to_thread(tesseract_check):
            log.error("configuration error: tesseract binary not found; Fast mode will fail with OCR_FAILED")

        store = BatchStore()
        processor = BatchProcessor(
            store=store,
            classifier=jev,
            extractors=exts,
            text_cap=settings.classification_text_cap,
            max_pages=settings.max_pdf_pages,
            ttl_minutes=settings.batch_ttl_minutes,
            max_concurrent=settings.max_concurrent_batches,
        )
        app.state.store = store
        app.state.processor = processor
        purge_task = asyncio.create_task(store.run_purge_loop()) if run_purge_loop else None
        log.info("startup complete")
        try:
            yield
        finally:
            if purge_task is not None:
                purge_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await purge_task
            await processor.shutdown()
            store.clear()
            for client in owned:
                await client.aclose()

    app = FastAPI(
        title="Document Classification & Extraction System",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter()
    app.state.tesseract_check = tesseract_check

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.code, exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error(ErrorCode.BATCH_NOT_FOUND, 404)
        if exc.status_code == 405:
            return _error(ErrorCode.BATCH_STATE_CONFLICT, 405)
        return _error(ErrorCode.INTERNAL_ERROR, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error(ErrorCode.INVALID_METHOD, 400)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error", exc_info=exc)
        return _error(ErrorCode.INTERNAL_ERROR, 500)

    @app.middleware("http")
    async def _request_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.add_middleware(BodySizeLimitMiddleware)

    app.include_router(health.router, prefix="/api")
    app.include_router(batches.router, prefix="/api")
    return app


# Run with: uvicorn app.main:create_app --factory
