"""Regenerate the tiny synthetic binary fixtures: `python -m tests.fixtures.make_fixtures` (from backend/)."""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from tests.fixtures.texts import INVOICE_PAGES, QUOTATION_TEXT, RECEIPT_TEXT

HERE = Path(__file__).parent


def text_pdf(pages: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    for page in pages:
        y = height - 60
        for line in page.splitlines():
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


def text_image(text: str, font_size: int = 36) -> Image.Image:
    font = ImageFont.load_default(size=font_size)
    lines = text.splitlines()
    img = Image.new("RGB", (1400, 80 + len(lines) * (font_size + 18)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 40 + i * (font_size + 18)), line, fill="black", font=font)
    return img


def jpeg_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, dpi=(300, 300))
    return buf.getvalue()


def main() -> None:
    (HERE / "invoice.pdf").write_bytes(text_pdf(INVOICE_PAGES))
    (HERE / "quotation.pdf").write_bytes(text_pdf([QUOTATION_TEXT]))
    (HERE / "long_21_pages.pdf").write_bytes(text_pdf([f"Page {i} of a long statement document" for i in range(1, 22)]))
    (HERE / "receipt.jpg").write_bytes(jpeg_bytes(text_image(RECEIPT_TEXT)))
    (HERE / "blank.jpg").write_bytes(jpeg_bytes(Image.new("RGB", (600, 400), "white")))

    img_pdf = io.BytesIO()
    text_image(RECEIPT_TEXT).save(img_pdf, format="PDF", resolution=150)
    (HERE / "image_only.pdf").write_bytes(img_pdf.getvalue())

    png = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(png, format="PNG")
    (HERE / "renamed_png.jpg").write_bytes(png.getvalue())
    (HERE / "corrupt.pdf").write_bytes(b"%PDF-1.4\nthis is not really a pdf\n")


if __name__ == "__main__":
    main()
