"""Authoritative API/data schemas (PRD Section 16.5)."""

import math
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from app.services.classification.categories import CATEGORY_KEYS
from app.services.fields.canonical import CANONICAL_FIELDS


def _iso_ms_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


Timestamp = Annotated[datetime, PlainSerializer(_iso_ms_z, return_type=str, when_used="json")]

BatchStatus = Literal["queued", "processing", "completed", "completed_with_errors", "cancelled"]
DocumentStatus = Literal["queued", "extracting", "classifying", "completed", "failed", "cancelled"]
ExtractionMethod = Literal["fast", "precise"]
MimeType = Literal["image/jpeg", "application/pdf"]

TERMINAL_DOCUMENT_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
TERMINAL_BATCH_STATUSES: frozenset[str] = frozenset({"completed", "completed_with_errors", "cancelled"})


class _Model(BaseModel):
    model_config = ConfigDict(validate_assignment=True)


class DocumentMetadata(_Model):
    mime_type: MimeType | None
    size_bytes: int
    page_count: int
    uploaded_at: Timestamp


class Extraction(_Model):
    method: ExtractionMethod
    duration_ms: int
    ocr_mean_confidence: float | None
    raw_text: str
    truncated_for_classification: bool


class Classification(_Model):
    document_type: str
    document_type_label: str
    confidence: float
    probabilities: dict[str, float]
    model: str
    duration_ms: int

    @field_validator("document_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in CATEGORY_KEYS:
            raise ValueError(f"unknown document_type {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not (math.isfinite(v) and 0.0 <= v <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        return v

    @field_validator("probabilities")
    @classmethod
    def _probabilities_shape(cls, v: dict[str, float]) -> dict[str, float]:
        if set(v) != set(CATEGORY_KEYS):
            raise ValueError("probabilities must contain exactly the eleven option keys")
        if abs(sum(v.values()) - 1.0) > 0.01:
            raise ValueError("probabilities must sum to 1 ± 0.01")
        return v


class DocumentResult(_Model):
    document_id: str
    filename: str
    status: DocumentStatus
    error_code: str | None = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    document_metadata: DocumentMetadata
    extraction: Extraction | None = None
    classification: Classification | None = None
    extracted_fields: dict[str, str] = Field(default_factory=dict)

    @field_validator("extracted_fields")
    @classmethod
    def _canonical_strings(cls, v: dict[str, str]) -> dict[str, str]:
        for key, value in v.items():
            if key not in CANONICAL_FIELDS:
                raise ValueError(f"non-canonical field {key!r}")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"field {key!r} must be a non-empty string")
        return v


class Summary(_Model):
    total: int
    completed: int
    failed: int
    cancelled: int
    average_confidence: float | None
    total_duration_ms: int


class Batch(_Model):
    batch_id: str
    status: BatchStatus
    extraction_method: ExtractionMethod
    created_at: Timestamp
    completed_at: Timestamp | None = None
    expires_at: Timestamp | None = None
    summary: Summary | None = None
    documents: list[DocumentResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def _terminal_fields(self) -> "Batch":
        # completed_at / expires_at / summary are null until the batch is terminal.
        if self.status not in TERMINAL_BATCH_STATUSES and (self.completed_at or self.expires_at or self.summary):
            raise ValueError("completed_at, expires_at and summary must be null until terminal")
        return self


class BatchCreatedDocument(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    error_code: str | None = None


class BatchCreated(BaseModel):
    batch_id: str
    status: BatchStatus
    documents: list[BatchCreatedDocument]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    tesseract: bool
    jev_configured: bool
    haiku_configured: bool
    version: str


class ErrorBody(BaseModel):
    error_code: str
    error_message: str
