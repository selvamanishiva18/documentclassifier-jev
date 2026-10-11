import pytesseract
import pytest
from PIL import Image

from app.errors import DocumentError, ErrorCode
from app.services.extraction import fast
from app.services.extraction.fast import OcrOutput, extract_sync
from tests.conftest import fixture_bytes, requires_poppler, requires_tesseract
from tests.fixtures.texts import INVOICE_PAGES


def _forbid_ocr(*_args: object, **_kwargs: object) -> OcrOutput:
    raise AssertionError("OCR must not be called for a text-layer PDF")


def test_text_layer_pdf_uses_pdfplumber_without_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fast, "ocr_image", _forbid_ocr)
    monkeypatch.setattr(fast, "_rasterize_page", _forbid_ocr)
    result = extract_sync(fixture_bytes("invoice.pdf"), "application/pdf", 20)
    assert result.page_count == 2
    assert "INV-2026-0412" in result.raw_text
    assert "\n\n--- page 2 ---\n\n" in result.raw_text
    assert result.raw_text.index("INV-2026-0412") < result.raw_text.index("--- page 2 ---")
    assert "Lids 500" in result.raw_text.split("--- page 2 ---")[1]
    assert result.ocr_mean_confidence is None  # no page needed OCR


def test_image_only_pdf_triggers_ocr_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    rasterized: list[int] = []

    def fake_raster(_data: bytes, page_number: int) -> Image.Image:
        rasterized.append(page_number)
        return Image.new("L", (10, 10), 255)

    monkeypatch.setattr(fast, "_rasterize_page", fake_raster)
    monkeypatch.setattr(fast, "ocr_image", lambda _img: OcrOutput("OCR TEXT FROM IMAGE PAGE 12345", [80.0, 90.0]))
    result = extract_sync(fixture_bytes("image_only.pdf"), "application/pdf", 20)
    assert rasterized == [1]
    assert result.raw_text == "OCR TEXT FROM IMAGE PAGE 12345"
    assert result.ocr_mean_confidence == 85.0


def test_pdf_pages_beyond_cap_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fast, "_rasterize_page", lambda _d, _n: Image.new("L", (10, 10), 255))
    monkeypatch.setattr(fast, "ocr_image", lambda _img: OcrOutput("x" * 30, [50.0]))
    result = extract_sync(fixture_bytes("long_21_pages.pdf"), "application/pdf", 20)
    assert result.page_count == 20
    assert "--- page 20 ---" in result.raw_text
    assert "--- page 21 ---" not in result.raw_text


def test_psm_fallback_when_primary_output_short(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_once(_img: Image.Image, psm: int) -> OcrOutput:
        calls.append(psm)
        return OcrOutput("short" if psm == 6 else "a much longer fallback transcription", [70.0])

    monkeypatch.setattr(fast, "_ocr_once", fake_once)
    monkeypatch.setattr(fast, "_osd_rotate", lambda img: img)
    out = fast.ocr_image(Image.new("RGB", (10, 10), "white"))
    assert calls == [6, 3]
    assert out.text == "a much longer fallback transcription"


def test_no_psm_fallback_when_primary_sufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_once(_img: Image.Image, psm: int) -> OcrOutput:
        calls.append(psm)
        return OcrOutput("this primary output is long enough", [70.0])

    monkeypatch.setattr(fast, "_ocr_once", fake_once)
    monkeypatch.setattr(fast, "_osd_rotate", lambda img: img)
    fast.ocr_image(Image.new("RGB", (10, 10), "white"))
    assert calls == [6]


def test_osd_rotation_applied_when_confident(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytesseract, "image_to_osd", lambda *_a, **_k: "Rotate: 90\nOrientation confidence: 5.1\n")
    rotated = fast._osd_rotate(Image.new("L", (40, 10), 255))
    assert rotated.size == (10, 40)


def test_osd_rotation_skipped_when_low_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytesseract, "image_to_osd", lambda *_a, **_k: "Rotate: 90\nOrientation confidence: 0.4\n")
    assert fast._osd_rotate(Image.new("L", (40, 10), 255)).size == (40, 10)


def test_mean_confidence_from_image_to_data(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {
        "text": ["", "TOTAL", "46.85", "PAID"],
        "conf": [-1, 90, 80, 70],
        "block_num": [0, 1, 1, 1],
        "par_num": [0, 1, 1, 1],
        "line_num": [0, 1, 1, 2],
    }
    monkeypatch.setattr(pytesseract, "image_to_data", lambda *_a, **_k: data)
    out = fast._ocr_once(Image.new("L", (10, 10), 255), 6)
    assert out.text == "TOTAL 46.85\nPAID"
    assert out.confidences == [90.0, 80.0, 70.0]


def test_tesseract_missing_maps_to_ocr_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_a: object, **_k: object) -> None:
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(fast, "ocr_image", missing)
    with pytest.raises(DocumentError) as err:
        extract_sync(fixture_bytes("receipt.jpg"), "image/jpeg", 20)
    assert err.value.code == ErrorCode.OCR_FAILED


def test_unreadable_pdf_is_corrupt() -> None:
    with pytest.raises(DocumentError) as err:
        extract_sync(fixture_bytes("corrupt.pdf"), "application/pdf", 20)
    assert err.value.code == ErrorCode.CORRUPT_FILE


@requires_tesseract
def test_real_ocr_on_synthetic_jpeg() -> None:
    result = extract_sync(fixture_bytes("receipt.jpg"), "image/jpeg", 20)
    assert "OFFICEWORKS" in result.raw_text.upper()
    assert "46.85" in result.raw_text
    assert result.ocr_mean_confidence is not None and 0 <= result.ocr_mean_confidence <= 100


@requires_tesseract
def test_real_ocr_blank_image_yields_almost_no_text() -> None:
    result = extract_sync(fixture_bytes("blank.jpg"), "image/jpeg", 20)
    assert len("".join(result.raw_text.split())) < 10  # processor maps this to EMPTY_TEXT


@requires_tesseract
@requires_poppler
def test_real_image_only_pdf_ocr() -> None:
    result = extract_sync(fixture_bytes("image_only.pdf"), "application/pdf", 20)
    assert "46.85" in result.raw_text


def test_invoice_fixture_pages_match_text_module() -> None:
    assert len(INVOICE_PAGES) == 2
