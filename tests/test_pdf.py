import pymupdf
import pytest

from dhvani.pdf import Cancelled, extract_pdf
from dhvani.text import TextError
from tests.conftest import requires_ocr


def test_digital_hindi_pdf(hindi_pdf):
    result = extract_pdf(hindi_pdf, ocr=False)
    assert result.pages == 1
    assert "नमस्ते" in result.text and "हिन्दी" in result.text
    assert not result.empty_pages


def test_password_pdf_rejected(tmp_path):
    path = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    doc.close()
    with pytest.raises(TextError, match="password"):
        extract_pdf(path)


def test_cancelled_extraction(hindi_pdf):
    with pytest.raises(Cancelled):
        extract_pdf(hindi_pdf, cancelled=lambda: True)


@requires_ocr
def test_scanned_hindi_pdf_ocr(hindi_pdf, tmp_path):
    src = pymupdf.open(hindi_pdf)
    pix = src[0].get_pixmap(dpi=220, alpha=False)
    scan = pymupdf.open()
    page = scan.new_page(width=src[0].rect.width, height=src[0].rect.height)
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / "scan.pdf"
    scan.save(path)
    scan.close()
    src.close()
    result = extract_pdf(path, ocr=True)
    assert result.ocr_pages == [1]
    assert len(result.text) > 50
    assert any("OCR" in w for w in result.warnings)
    assert sum('\u0900' <= c <= '\u097f' for c in result.text) > 30
