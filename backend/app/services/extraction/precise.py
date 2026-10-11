"""Precise extraction via Claude Haiku 4.5 (PRD 6.2, 16.6.2). One call returns transcription + fields."""

import base64
import io
import json
import logging
import re
from typing import Any

import anthropic
from pypdf import PdfReader, PdfWriter

from app.errors import DocumentError, ErrorCode
from app.services import retry
from app.services.extraction.base import ExtractionResult
from app.services.fields.canonical import filter_fields, unknown_keys

log = logging.getLogger("docclassify.precise")

HAIKU_TIMEOUT_S = 90.0
MAX_TOKENS = 4096

HAIKU_SYSTEM_PROMPT = (
    "You are a precise document transcription engine for scanned business documents.\n"
    "You output ONLY a single JSON object and nothing else — no prose, no markdown fences."
)

HAIKU_USER_PROMPT = """Transcribe the full text of this document in reading order, preserving line breaks.
Then extract the fields listed below if, and only if, they are explicitly present.
Return exactly this JSON shape:

{
  "raw_text": "<full transcription>",
  "fields": {
    "document_number": "<e.g. invoice/PO/order/quote number>",
    "document_date": "<date as written>",
    "due_date": "<as written>",
    "issuer_name": "<company that issued the document>",
    "recipient_name": "<company/person it is addressed to>",
    "reference_number": "<related PO/order/invoice reference>",
    "subtotal": "<as written>",
    "tax_amount": "<as written>",
    "total_amount": "<as written>",
    "currency": "<ISO 4217 code only if explicitly shown or unambiguous>",
    "payment_terms": "<as written>",
    "line_items_summary": "<'N line items: desc x qty; desc x qty; ...' max 300 chars>"
  }
}

Rules: omit any field you cannot find (do not output null or empty strings);
copy values exactly as written; do not infer or calculate; do not classify the document."""

CORRECTIVE_PROMPT = "Your previous output was not valid JSON matching the required shape. Output only the JSON object."

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S | re.I)


class BadOutputError(Exception):
    pass


def strip_code_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text.strip()


def parse_payload(text: str) -> tuple[str, dict[str, Any]]:
    """Post-processing steps 1-2: strip fences, json.loads, validate shape."""
    try:
        payload = json.loads(strip_code_fences(text))
    except json.JSONDecodeError as exc:
        raise BadOutputError("not JSON") from exc
    if not isinstance(payload, dict):
        raise BadOutputError("top level is not an object")
    raw_text = payload.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise BadOutputError("raw_text missing or empty")
    fields = payload.get("fields", {})
    if fields is None:
        fields = {}
    if not isinstance(fields, dict):
        raise BadOutputError("fields is not an object")
    return raw_text, fields


def truncate_pdf(data: bytes, max_pages: int) -> tuple[bytes, int]:
    """Drop pages beyond `max_pages` before sending (PRD 7.7). Returns (bytes, pages kept)."""
    try:
        reader = PdfReader(io.BytesIO(data))
        total = len(reader.pages)
    except Exception as exc:
        raise DocumentError(ErrorCode.CORRUPT_FILE, type(exc).__name__) from None
    if total <= max_pages:
        return data, total
    writer = PdfWriter()
    for page in reader.pages[:max_pages]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), max_pages


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return retry.is_retryable_status(exc.status_code)
    return False


def _retry_after(exc: BaseException) -> float | None:
    if isinstance(exc, anthropic.APIStatusError):
        raw = exc.response.headers.get("retry-after")
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None
    return None


def _map_error(exc: BaseException) -> DocumentError:
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return DocumentError(ErrorCode.HAIKU_AUTH_ERROR, f"status {exc.status_code}")
    return DocumentError(ErrorCode.HAIKU_UNAVAILABLE, type(exc).__name__)


class PreciseExtractor:
    def __init__(self, *, api_key: str, model: str, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._model = model
        # SDK retries disabled: the PRD 7.9 policy is applied by `retry.with_retry`.
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, timeout=HAIKU_TIMEOUT_S, max_retries=0)

    async def aclose(self) -> None:
        await self._client.close()

    async def _call(self, content_block: dict[str, Any], corrective: bool) -> str:
        user_content: list[dict[str, Any]] = [content_block, {"type": "text", "text": HAIKU_USER_PROMPT}]
        if corrective:
            user_content.append({"type": "text", "text": CORRECTIVE_PROMPT})

        def _log_retry(attempt: int, exc: BaseException) -> None:
            log.warning("haiku retry", extra={"attempt": attempt, "upstream_status": getattr(exc, "status_code", None)})

        try:
            msg = await retry.with_retry(
                lambda: self._client.messages.create(
                    model=self._model,
                    max_tokens=MAX_TOKENS,
                    temperature=0,
                    system=HAIKU_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],  # type: ignore[typeddict-item]
                ),
                should_retry=_should_retry,
                retry_after=_retry_after,
                on_retry=_log_retry,
            )
        except anthropic.APIError as exc:
            mapped = _map_error(exc)
            log.warning(
                "haiku request failed",
                extra={"error_code": mapped.code.value, "upstream_status": getattr(exc, "status_code", None)},
            )
            raise mapped from None
        return "".join(b.text for b in msg.content if b.type == "text")

    async def extract(self, data: bytes, mime_type: str, filename: str, max_pages: int) -> ExtractionResult:
        if mime_type == "image/jpeg":
            page_count = 1
            block: dict[str, Any] = {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(data).decode()},
            }
        else:
            data, page_count = truncate_pdf(data, max_pages)
            block = {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(data).decode()},
            }

        for corrective in (False, True):
            text = await self._call(block, corrective)
            try:
                raw_text, fields = parse_payload(text)
            except BadOutputError:
                continue
            extra = unknown_keys(fields)
            if extra:
                # Observation for DECISIONS.md item 11: key names only, never values.
                log.info("haiku returned non-canonical keys", extra={"unknown_keys": extra})
            return ExtractionResult(raw_text=raw_text, page_count=page_count, fields=filter_fields(fields))
        raise DocumentError(ErrorCode.HAIKU_BAD_OUTPUT, "invalid JSON after corrective retry")
