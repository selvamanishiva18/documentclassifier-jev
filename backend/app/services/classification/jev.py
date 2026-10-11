"""Jev (TypeSafe System One) classification client (PRD 6.3, 16.6.1)."""

import logging
import math
import time
from dataclasses import dataclass, field

import httpx2
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    JSONValue,
    RetryPolicy,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAuthenticationError,
    TypeSafeBadRequestError,
    TypeSafeNotFoundError,
    TypeSafePermissionDeniedError,
    TypeSafeRateLimitError,
    TypeSafeUnprocessableEntityError,
)

from app.errors import DocumentError, ErrorCode
from app.services import retry
from app.services.classification.categories import CATEGORY_KEYS, CRITERIA, INSTRUCTIONS, LABELS

log = logging.getLogger("docclassify.jev")

QUESTION_NAME = "document_type"
JEV_TIMEOUT_S = 30.0
PROBABILITY_TOLERANCE = 0.01


@dataclass
class ClassificationOutcome:
    document_type: str
    document_type_label: str
    confidence: float
    probabilities: dict[str, float]
    model: str
    duration_ms: int
    warnings: list[str] = field(default_factory=list)


def build_questions() -> dict[str, Choice]:
    return {QUESTION_NAME: Choice(instructions=INSTRUCTIONS, criteria=dict(CRITERIA))}


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, TypeSafeAPIConnectionError):  # includes timeouts
        return True
    if isinstance(exc, TypeSafeAPIResponseValidationError):
        return False
    if isinstance(exc, TypeSafeAPIError):
        return retry.is_retryable_status(exc.status)
    return False


def _retry_after(exc: BaseException) -> float | None:
    if isinstance(exc, TypeSafeRateLimitError) and exc.retry_after_ms is not None:
        return exc.retry_after_ms / 1000
    return None


def _map_error(exc: BaseException) -> DocumentError:
    if isinstance(exc, TypeSafeAPIResponseValidationError):
        return DocumentError(ErrorCode.JEV_INVALID_RESPONSE, f"invalid field {exc.field_path}")
    if isinstance(exc, TypeSafeAuthenticationError | TypeSafePermissionDeniedError):
        return DocumentError(ErrorCode.JEV_AUTH_ERROR, f"status {exc.status}")
    if isinstance(exc, TypeSafeUnprocessableEntityError | TypeSafeBadRequestError | TypeSafeNotFoundError):
        return DocumentError(ErrorCode.JEV_BAD_REQUEST, f"status {exc.status}")
    return DocumentError(ErrorCode.JEV_UNAVAILABLE, type(exc).__name__)


def validate_answer(choice: object, probabilities: object, confidence: object) -> list[str]:
    """Enforce the 16.5 invariants. Returns warnings; raises JEV_INVALID_RESPONSE on violation."""
    invalid = ErrorCode.JEV_INVALID_RESPONSE
    if not isinstance(choice, str) or choice not in CATEGORY_KEYS:
        raise DocumentError(invalid, "choice is not one of the eleven option keys")
    if not isinstance(probabilities, dict) or set(probabilities) != set(CATEGORY_KEYS):
        raise DocumentError(invalid, "probabilities key set mismatch")
    values = list(probabilities.values())
    if not all(isinstance(v, int | float) and math.isfinite(v) for v in values):
        raise DocumentError(invalid, "non-numeric probability")
    if abs(sum(values) - 1.0) > PROBABILITY_TOLERANCE:
        raise DocumentError(invalid, "probabilities do not sum to 1")
    if not isinstance(confidence, int | float) or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise DocumentError(invalid, "confidence out of range")
    warnings: list[str] = []
    if probabilities[choice] < max(values):
        warnings.append("choice_not_argmax")
    return warnings


class JevClassifier:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        # Retries are owned by `retry.with_retry` so the exact PRD 7.9 policy applies; SDK retries are disabled.
        self._client = AsyncTypeSafeClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=JEV_TIMEOUT_S,
            retry=RetryPolicy(max_retries=0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def classify(self, text: str, filename: str, page_count: int) -> ClassificationOutcome:
        state: dict[str, JSONValue] = {"document_text": text, "filename": filename, "page_count": page_count}
        started = time.perf_counter()

        def _log_retry(attempt: int, exc: BaseException) -> None:
            log.warning("jev retry", extra={"attempt": attempt, "upstream_status": getattr(exc, "status", None)})

        try:
            resp = await retry.with_retry(
                lambda: self._client.system_one(model=self._model, state=state, questions=build_questions()),
                should_retry=_should_retry,
                retry_after=_retry_after,
                on_retry=_log_retry,
            )
        except (TypeSafeAPIError, TypeSafeAPIConnectionError) as exc:
            mapped = _map_error(exc)
            log.warning(
                "jev request failed",
                extra={"error_code": mapped.code.value, "upstream_status": getattr(exc, "status", None)},
            )
            raise mapped from None
        duration_ms = int((time.perf_counter() - started) * 1000)

        answer = resp.choices.get(QUESTION_NAME)
        if answer is None:
            raise DocumentError(ErrorCode.JEV_INVALID_RESPONSE, "missing document_type answer")
        probabilities = dict(answer.probabilities)
        warnings = validate_answer(answer.choice, probabilities, answer.confidence)
        return ClassificationOutcome(
            document_type=answer.choice,
            document_type_label=LABELS[answer.choice],
            confidence=float(answer.confidence),
            probabilities={k: float(v) for k, v in probabilities.items()},
            model=resp.model,
            duration_ms=duration_ms,
            warnings=warnings,
        )
