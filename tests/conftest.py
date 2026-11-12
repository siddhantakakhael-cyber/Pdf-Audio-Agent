from __future__ import annotations

import pathlib
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dhvani.app import app  # noqa: E402
from dhvani.config import local_assets_ready, ocr_assets_ready  # noqa: E402

SESSION = "22222222-2222-4222-8222-222222222222"
HEADERS = {"X-Dhvani-Session": SESSION, "X-Dhvani-Client": "web"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        c.headers.update(HEADERS)
        yield c
        for job in c.get("/api/jobs").json()["jobs"]:
            if job["status"] not in {"extracting", "queued", "generating"}:
                c.delete(f"/api/jobs/{job['id']}")


@pytest.fixture
def hindi_pdf(tmp_path):
    import pymupdf

    font = ROOT / "tests" / "assets" / "NotoSansDevanagari.ttf"
    path = tmp_path / "hindi.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="NotoHindi", fontfile=str(font))
    text = "नमस्ते! यह ध्वनि का परीक्षण है।\nयह किताब हिन्दी में है और हम इसे आवाज़ में बदलेंगे।\nधीरे-धीरे हर बात साफ़ और आसान।"
    page.insert_textbox(pymupdf.Rect(50, 60, 540, 760), text, fontname="NotoHindi", fontsize=18)
    doc.save(path)
    doc.close()
    return path


def wait_job(client, job_id, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"ready", "completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"Job timed out: {job_id}")


requires_local = pytest.mark.skipif(not local_assets_ready(), reason="Run scripts/setup_assets.py for local TTS tests")
requires_ocr = pytest.mark.skipif(not ocr_assets_ready(), reason="Run scripts/setup_assets.py for OCR tests")
