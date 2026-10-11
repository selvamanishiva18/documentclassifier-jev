"""Extractor protocol shared by the Fast and Precise methods (PRD 6.2)."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ExtractionResult:
    raw_text: str
    page_count: int
    ocr_mean_confidence: float | None = None
    # Precise mode returns fields in the same call; Fast mode leaves this None and the heuristic extractor runs.
    fields: dict[str, str] | None = None
    warnings: list[str] = field(default_factory=list)


class Extractor(Protocol):
    async def extract(self, data: bytes, mime_type: str, filename: str, max_pages: int) -> ExtractionResult: ...


def non_whitespace_len(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())
