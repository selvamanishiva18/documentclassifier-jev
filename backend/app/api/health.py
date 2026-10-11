"""Health endpoint (PRD 6.6 AC5)."""

import asyncio
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Request

from app.config import Settings
from app.schemas import HealthResponse

router = APIRouter()

PACKAGE_NAME = "docclassify-backend"


def backend_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    tesseract = await asyncio.to_thread(request.app.state.tesseract_check)
    return HealthResponse(
        tesseract=tesseract,
        jev_configured=settings.jev_configured,
        haiku_configured=settings.haiku_configured,
        version=backend_version(),
    )
