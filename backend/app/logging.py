"""Structured JSON logging. Logs never include document text, extracted fields, or API keys."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Only these `extra=` keys are emitted; anything else passed as extra is dropped so content cannot leak by accident.
CONTEXT_KEYS = (
    "batch_id",
    "document_id",
    "stage",
    "duration_ms",
    "error_code",
    "method",
    "path",
    "status_code",
    "upstream_status",
    "attempt",
    "fields_found",
    "unknown_keys",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in CONTEXT_KEYS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info and record.exc_info[0] is not None:
            # Exception type only: messages/tracebacks from upstream SDKs can echo request content.
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


class StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg,unused-ignore]
    """Writes to whatever `sys.stdout` is at emit time (stays valid when stdout is swapped, e.g. under pytest)."""

    @property
    def stream(self) -> Any:
        return sys.stdout

    @stream.setter
    def stream(self, _value: Any) -> None:
        pass


def configure_logging(level: str = "INFO") -> None:
    handler = StdoutHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party request/wire logging can include headers or bodies; keep it quiet.
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "anthropic", "typesafe_sdk", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger("docclassify")
