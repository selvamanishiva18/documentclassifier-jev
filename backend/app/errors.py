"""Stable error codes and user-facing messages (PRD Section 16.8)."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    NO_FILES = "NO_FILES"
    INVALID_METHOD = "INVALID_METHOD"
    PRECISE_NOT_CONFIGURED = "PRECISE_NOT_CONFIGURED"
    SERVER_BUSY = "SERVER_BUSY"
    CORRUPT_FILE = "CORRUPT_FILE"
    EMPTY_TEXT = "EMPTY_TEXT"
    OCR_FAILED = "OCR_FAILED"
    HAIKU_UNAVAILABLE = "HAIKU_UNAVAILABLE"
    HAIKU_AUTH_ERROR = "HAIKU_AUTH_ERROR"
    HAIKU_BAD_OUTPUT = "HAIKU_BAD_OUTPUT"
    JEV_UNAVAILABLE = "JEV_UNAVAILABLE"
    JEV_AUTH_ERROR = "JEV_AUTH_ERROR"
    JEV_BAD_REQUEST = "JEV_BAD_REQUEST"
    JEV_INVALID_RESPONSE = "JEV_INVALID_RESPONSE"
    BATCH_NOT_FOUND = "BATCH_NOT_FOUND"
    BATCH_EXPIRED = "BATCH_EXPIRED"
    BATCH_STATE_CONFLICT = "BATCH_STATE_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_FILE_TYPE: "Only JPG, JPEG, and PDF files are supported.",
    ErrorCode.FILE_TOO_LARGE: "{filename} is larger than 10 MB and was skipped.",
    ErrorCode.TOO_MANY_FILES: "You can process up to 20 files per batch.",
    ErrorCode.UPLOAD_TOO_LARGE: "The upload is too large. Keep the total under 220 MB.",
    ErrorCode.NO_FILES: "Add at least one file to continue.",
    ErrorCode.INVALID_METHOD: "Choose Fast or Precise extraction.",
    ErrorCode.PRECISE_NOT_CONFIGURED: "Precise mode is not configured on this server.",
    ErrorCode.SERVER_BUSY: "The server is busy. Try again in a moment.",
    ErrorCode.CORRUPT_FILE: "{filename} could not be read. The file may be corrupted.",
    ErrorCode.EMPTY_TEXT: "No readable text was found in {filename}.",
    ErrorCode.OCR_FAILED: "Could not read text from {filename}. Try the Precise method for low-quality scans.",
    ErrorCode.HAIKU_UNAVAILABLE: "The Precise extraction service is temporarily unavailable. Try again or use Fast.",
    ErrorCode.HAIKU_AUTH_ERROR: "Precise extraction is not configured correctly on this server.",
    ErrorCode.HAIKU_BAD_OUTPUT: "Precise extraction returned an unexpected result for {filename}. Try again.",
    ErrorCode.JEV_UNAVAILABLE: "The classification service is temporarily unavailable. Try again in a few minutes.",
    ErrorCode.JEV_AUTH_ERROR: "Classification is not configured correctly on this server. Contact the administrator.",
    ErrorCode.JEV_BAD_REQUEST: "The document could not be classified.",
    ErrorCode.JEV_INVALID_RESPONSE: "The classification service returned an unexpected result.",
    ErrorCode.BATCH_NOT_FOUND: "This batch has expired. Upload the files again to process them.",
    ErrorCode.BATCH_EXPIRED: "The original files have been cleared and cannot be retried.",
    ErrorCode.BATCH_STATE_CONFLICT: "This action is not available while the batch is in its current state.",
    ErrorCode.INTERNAL_ERROR: "Something went wrong processing {filename}. Try again.",
}

HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_FILE_TYPE: 400,
    ErrorCode.FILE_TOO_LARGE: 400,
    ErrorCode.TOO_MANY_FILES: 400,
    ErrorCode.UPLOAD_TOO_LARGE: 413,
    ErrorCode.NO_FILES: 400,
    ErrorCode.INVALID_METHOD: 400,
    ErrorCode.PRECISE_NOT_CONFIGURED: 503,
    ErrorCode.SERVER_BUSY: 429,
    ErrorCode.BATCH_NOT_FOUND: 404,
    ErrorCode.BATCH_EXPIRED: 410,
    ErrorCode.BATCH_STATE_CONFLICT: 409,
    ErrorCode.INTERNAL_ERROR: 500,
}

# File-level validation failures: retrying cannot change the outcome, and the bytes are not retained.
VALIDATION_CODES = frozenset({ErrorCode.INVALID_FILE_TYPE, ErrorCode.FILE_TOO_LARGE, ErrorCode.CORRUPT_FILE})


def message_for(code: ErrorCode, filename: str = "the upload") -> str:
    return MESSAGES[code].format(filename=filename)


class ApiError(Exception):
    """A batch-scoped error returned as the HTTP error body."""

    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = HTTP_STATUS.get(code, 400)


class DocumentError(Exception):
    """A document-scoped failure; recorded on the DocumentResult, never aborts the batch."""

    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail
