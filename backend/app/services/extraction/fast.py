"""Fast extraction: Pytesseract for images, pdfplumber + OCR fallback for PDFs (PRD 6.2, 7.8)."""

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field

import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image, ImageOps

from app.errors import DocumentError, ErrorCode
from app.services.extraction.base import ExtractionResult, non_whitespace_len

log = logging.getLogger("docclassify.fast")

OCR_TIMEOUT_S = 60
RASTER_DPI = 300
MIN_PAGE_CHARS = 20  # below this, a PDF page's text layer is ignored and the page is OCR'd; also the PSM fallback gate
PRIMARY_PSM = 6
FALLBACK_PSM = 3
OEM = 1  # LSTM engine
OSD_MIN_CONFIDENCE = 2.0
PAGE_SEPARATOR = "\n\n--- page {n} ---\n\n"


@dataclass
class OcrOutput:
    text: str
    confidences: list[float] = field(default_factory=list)


def _osd_rotate(img: Image.Image) -> Image.Image:
    """Auto-rotate using Tesseract OSD when its orientation confidence is high enough."""
    try:
        osd = pytesseract.image_to_osd(img, config="--psm 0", timeout=OCR_TIMEOUT_S)
    except (pytesseract.TesseractError, RuntimeError):
        return img  # OSD fails on sparse text; carry on unrotated
    rotate = re.search(r"Rotate:\s+(\d+)", osd)
    conf = re.search(r"Orientation confidence:\s+([\d.]+)", osd)
    if rotate and conf and int(rotate.group(1)) and float(conf.group(1)) >= OSD_MIN_CONFIDENCE:
        return img.rotate(-int(rotate.group(1)), expand=True)
    return img


def _ocr_once(img: Image.Image, psm: int) -> OcrOutput:
    data = pytesseract.image_to_data(
        img,
        lang="eng",
        config=f"--oem {OEM} --psm {psm}",
        output_type=pytesseract.Output.DICT,
        timeout=OCR_TIMEOUT_S,
    )
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        conf = float(data["conf"][i])
        if not str(word).strip():
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines.setdefault(key, []).append(str(word))
        if conf >= 0:
            confidences.append(conf)
    text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
    return OcrOutput(text, confidences)


def ocr_image(img: Image.Image) -> OcrOutput:
    """Grayscale + OSD rotation, then `--psm 6`, falling back to `--psm 3` when output is < 20 chars."""
    gray = ImageOps.exif_transpose(img).convert("L")
    gray = _osd_rotate(gray)
    out = _ocr_once(gray, PRIMARY_PSM)
    if non_whitespace_len(out.text) < MIN_PAGE_CHARS:
        fallback = _ocr_once(gray, FALLBACK_PSM)
        if non_whitespace_len(fallback.text) > non_whitespace_len(out.text):
            out = fallback
    return out


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def extract_jpeg(data: bytes) -> ExtractionResult:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise DocumentError(ErrorCode.CORRUPT_FILE, type(exc).__name__) from None
    out = ocr_image(img)
    return ExtractionResult(raw_text=out.text, page_count=1, ocr_mean_confidence=_mean(out.confidences))


def _rasterize_page(data: bytes, page_number: int) -> Image.Image:
    images = convert_from_bytes(
        data, dpi=RASTER_DPI, first_page=page_number, last_page=page_number, grayscale=True, timeout=OCR_TIMEOUT_S
    )
    if not images:
        raise DocumentError(ErrorCode.OCR_FAILED, f"page {page_number} did not rasterize")
    return images[0]


def extract_pdf(data: bytes, max_pages: int) -> ExtractionResult:
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError(ErrorCode.CORRUPT_FILE, type(exc).__name__) from None
    texts: list[str] = []
    confidences: list[float] = []
    with pdf:
        pages = pdf.pages[:max_pages]
        for n, page in enumerate(pages, start=1):
            text = page.extract_text() or ""
            if non_whitespace_len(text) < MIN_PAGE_CHARS:
                out = ocr_image(_rasterize_page(data, n))
                text = out.text
                confidences.extend(out.confidences)
            texts.append(text)
        page_count = len(pages)
    raw = texts[0] if texts else ""
    for n, text in enumerate(texts[1:], start=2):
        raw += PAGE_SEPARATOR.format(n=n) + text
    return ExtractionResult(raw_text=raw, page_count=page_count, ocr_mean_confidence=_mean(confidences))


def extract_sync(data: bytes, mime_type: str, max_pages: int) -> ExtractionResult:
    try:
        if mime_type == "image/jpeg":
            return extract_jpeg(data)
        return extract_pdf(data, max_pages)
    except DocumentError:
        raise
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, RuntimeError, OSError) as exc:
        # RuntimeError covers pytesseract's timeout; OSError covers missing Poppler / process failures.
        raise DocumentError(ErrorCode.OCR_FAILED, type(exc).__name__) from None
    except Exception as exc:  # pdf2image raises its own exception hierarchy
        if type(exc).__module__.startswith("pdf2image"):
            raise DocumentError(ErrorCode.OCR_FAILED, type(exc).__name__) from None
        raise


class FastExtractor:
    def __init__(self, tesseract_cmd: str = "tesseract") -> None:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    async def extract(self, data: bytes, mime_type: str, filename: str, max_pages: int) -> ExtractionResult:
        # OCR is CPU-bound; run it off the event loop so status polling stays responsive.
        return await asyncio.to_thread(extract_sync, data, mime_type, max_pages)


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True
