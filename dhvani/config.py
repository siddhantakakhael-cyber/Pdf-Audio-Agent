from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path(os.environ.get("DHVANI_RUNTIME", ROOT / ".runtime")).resolve()
# Generated PDFs/audio are ephemeral and excluded from Arena snapshots; models persist.
CACHE = Path(os.environ.get("DHVANI_CACHE", ROOT / ".cache" / "dhvani")).resolve()
JOBS = CACHE / "jobs"
SAMPLES = CACHE / "samples"
MODEL_DIR = RUNTIME / "models" / "priyamvada"
MODEL_PATH = MODEL_DIR / "hi_IN-priyamvada-medium.onnx"
MODEL_CONFIG = MODEL_DIR / "hi_IN-priyamvada-medium.onnx.json"
TOKENS_PATH = MODEL_DIR / "tokens.txt"
ESPEAK_DATA = RUNTIME / "piper" / "espeak-ng-data"
TESSDATA = RUNTIME / "tessdata"

MAX_PDF_BYTES = int(os.environ.get("DHVANI_MAX_PDF_MB", "25")) * 1024 * 1024
MAX_PAGES = int(os.environ.get("DHVANI_MAX_PAGES", "500"))
MAX_TEXT_CHARS = int(os.environ.get("DHVANI_MAX_TEXT_CHARS", "1000000"))
MAX_JSON_BYTES = 4 * 1024 * 1024
CHUNK_CHARS = 1000
JOB_TTL_SECONDS = int(os.environ.get("DHVANI_JOB_TTL_HOURS", "24")) * 3600
MAX_ACTIVE_PER_SESSION = 3
MAX_PENDING_GLOBAL = 12
WORKERS = max(1, min(4, int(os.environ.get("DHVANI_WORKERS", "2"))))

VOICE_OPTIONS = {
    "priyamvada": {"engine": "local", "label": "Priyamvada", "gender": "female"},
    "hi-IN-SwaraNeural": {"engine": "edge", "label": "Swara", "gender": "female"},
    "hi-IN-MadhurNeural": {"engine": "edge", "label": "Madhur", "gender": "male"},
}
DEFAULT_VOICE = "priyamvada"
SAMPLE_TEXT = (
    "नमस्ते! यह ध्वनि है, आपकी किताबों की नई आवाज़। "
    "कहानी के पन्ने अब चलते-फिरते भी सुनिए। धीरे-धीरे, हर बात साफ़ और आसान।"
)


def ensure_dirs() -> None:
    for path in (RUNTIME, CACHE, JOBS, SAMPLES, MODEL_DIR, TESSDATA):
        path.mkdir(parents=True, exist_ok=True)


def local_assets_ready() -> bool:
    return all(
        p.exists()
        for p in (
            MODEL_PATH,
            MODEL_CONFIG,
            TOKENS_PATH,
            ESPEAK_DATA / "phontab",
            ESPEAK_DATA / "hi_dict",
        )
    )


def ocr_assets_ready() -> bool:
    return all((TESSDATA / f"{lang}.traineddata").exists() for lang in ("hin", "eng"))
