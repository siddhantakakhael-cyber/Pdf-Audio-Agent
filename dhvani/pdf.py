from __future__ import annotations

import io
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image

from .config import MAX_PAGES, MAX_TEXT_CHARS, TESSDATA, ocr_assets_ready
from .text import TextError, clean_text


class Cancelled(Exception):
    pass


@dataclass
class Extraction:
    text: str
    pages: int
    ocr_pages: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_ocr_lock = threading.Lock()
_ocr_api = None


def _get_ocr_api():
    global _ocr_api
    if _ocr_api is None:
        import tesserocr

        _ocr_api = tesserocr.PyTessBaseAPI(
            path=str(TESSDATA) + "/",
            lang="hin+eng",
            psm=tesserocr.PSM.AUTO,
            oem=tesserocr.OEM.LSTM_ONLY,
        )
    return _ocr_api


def ocr_image(image: Image.Image) -> str:
    with _ocr_lock:
        api = _get_ocr_api()
        api.SetImage(image.convert("RGB"))
        try:
            return api.GetUTF8Text() or ""
        finally:
            api.Clear()


def extract_pdf(
    path: Path,
    *,
    ocr: bool = True,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Extraction:
    def check_cancel() -> None:
        if cancelled and cancelled():
            raise Cancelled()

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise TextError("PDF open nahi ho payi. File corrupt ya password-protected ho sakti hai.") from exc
    with doc:
        if doc.needs_pass:
            raise TextError("PDF password-protected hai. Pehle password hatakar unlocked copy upload karein.")
        if doc.page_count == 0:
            raise TextError("PDF mein koi page nahi hai.")
        if doc.page_count > MAX_PAGES:
            raise TextError(f"PDF mein {doc.page_count} pages hain. Ek baar mein {MAX_PAGES} pages tak; PDF ko parts mein baantein.")
        result = Extraction(text="", pages=doc.page_count)
        if ocr and not ocr_assets_ready():
            result.warnings.append("OCR models missing hain. `python scripts/setup_assets.py` chalayein; scanned pages skip ho sakte hain.")
        parts: list[str] = []
        total = 0
        for index, page in enumerate(doc):
            check_cancel()
            page_text = page.get_text("text", sort=True).strip()
            image_coverage = 0.0
            if ocr and ocr_assets_ready() and len(clean_text(page_text)) < 200:
                try:
                    page_area = float(page.rect.get_area()) or 1.0
                    image_coverage = sum(
                        max(0.0, (pymupdf.Rect(info["bbox"]) & page.rect).get_area())
                        for info in page.get_image_info()
                    ) / page_area
                except Exception:
                    image_coverage = 0.0
            if ocr and ocr_assets_ready() and (len(clean_text(page_text)) < 20 or image_coverage > 0.5):
                try:
                    pix = page.get_pixmap(dpi=180, alpha=False)
                    image = Image.open(io.BytesIO(pix.tobytes("png")))
                    recognized = ocr_image(image)
                    if len(clean_text(recognized)) > len(clean_text(page_text)):
                        page_text = recognized
                        result.ocr_pages.append(index + 1)
                except Exception:
                    result.warnings.append(f"Page {index + 1} ka OCR fail hua; available text hi rakha gaya.")
            page_text = clean_text(page_text)
            if not page_text:
                result.empty_pages.append(index + 1)
            parts.append(page_text)
            total += len(page_text) + 2
            if total > MAX_TEXT_CHARS:
                raise TextError(f"Text limit {MAX_TEXT_CHARS:,} characters cross ho gayi. PDF ko chhote parts mein upload karein.")
            if progress:
                progress(index + 1, doc.page_count)
        check_cancel()
        result.text = clean_text("\n\n".join(p for p in parts if p))
        if result.empty_pages:
            shown = ", ".join(map(str, result.empty_pages[:12]))
            more = "…" if len(result.empty_pages) > 12 else ""
            result.warnings.append(f"In pages par readable text nahi mila: {shown}{more}. Audio mein ye pages shamil nahi hain.")
        if result.ocr_pages:
            result.warnings.append(f"{len(result.ocr_pages)} pages OCR se padhe gaye. Matra/spelling ke liye text review zaroor karein.")
        if not result.text:
            raise TextError("PDF se text nahi mila. Scanned PDF ke liye OCR on karein; phir bhi fail ho to saaf scan ya text paste karein.")
        return result
