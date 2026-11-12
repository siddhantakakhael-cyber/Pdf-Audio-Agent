from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .config import (
    DEFAULT_VOICE,
    MAX_JSON_BYTES,
    MAX_PAGES,
    MAX_PDF_BYTES,
    MAX_TEXT_CHARS,
    SAMPLE_TEXT,
    SAMPLES,
    VOICE_OPTIONS,
    ensure_dirs,
    local_assets_ready,
    ocr_assets_ready,
)
from .jobs import JobError, JobManager
from .pdf import Cancelled
from .text import TextError, clean_text, roman_hindi, validate_text
from .tts import TTSError, chunk_extension, finalize_mp3, synthesize_chunk

STATIC = Path(__file__).resolve().parent / "static"
SESSION_RE = re.compile(r"^[A-Za-z0-9-]{32,64}$")
manager: JobManager | None = None
_sample_lock = threading.Lock()
_sample_calls: dict[str, deque] = defaultdict(deque)


def get_manager() -> JobManager:
    if manager is None:
        raise HTTPException(503, "Server abhi start ho raha hai.")
    return manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager
    ensure_dirs()
    manager = JobManager()
    manager.cleanup()

    async def housekeeping() -> None:
        while True:
            await asyncio.sleep(600)
            await run_in_threadpool(get_manager().cleanup)
            cutoff = time.time() - 3600
            for path in SAMPLES.glob("*"):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)

    task = asyncio.create_task(housekeeping())
    yield
    task.cancel()
    manager.shutdown()
    manager = None


app = FastAPI(title="Dhvani — Hindi PDF to MP3", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(JobError)
async def job_error_handler(request: Request, exc: JobError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)


@app.exception_handler(TextError)
async def text_error_handler(request: Request, exc: TextError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "Request check karein: file, text, voice ya speed valid nahi hai."}, status_code=422)


def session_id(request: Request) -> str:
    value = request.headers.get("x-dhvani-session", "")
    if not SESSION_RE.fullmatch(value):
        raise HTTPException(400, "Browser session missing hai. Page refresh karein.")
    return value


def require_client(request: Request) -> None:
    if request.headers.get("x-dhvani-client") != "web":
        raise HTTPException(403, "Yeh action Dhvani web client se karein.")


async def limited_json(request: Request) -> dict:
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > MAX_JSON_BYTES:
            raise HTTPException(413, "Request bahut badi hai. Text ko chhote parts mein bhejein.")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Valid JSON body chahiye.") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "JSON object chahiye.")
    return value


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.svg")
async def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "local_ready": local_assets_ready(),
        "ocr_ready": ocr_assets_ready(),
        "default_voice": DEFAULT_VOICE,
        "sample_text": SAMPLE_TEXT,
        "voices": [
            {"id": key, **value, "ready": local_assets_ready() if value["engine"] == "local" else True}
            for key, value in VOICE_OPTIONS.items()
        ],
        "limits": {"pdf_mb": MAX_PDF_BYTES // (1024 * 1024), "pages": MAX_PAGES, "characters": MAX_TEXT_CHARS},
        "privacy": "Local mode mein text third-party ko nahi bheja jata. Online mode mein text Microsoft Edge TTS ko jata hai.",
    }


@app.post("/api/jobs")
async def upload_pdf(request: Request, file: UploadFile = File(...), ocr: bool = Form(True)):
    require_client(request)
    session = session_id(request)
    data = bytearray()
    try:
        while part := await file.read(1024 * 1024):
            data.extend(part)
            if len(data) > MAX_PDF_BYTES:
                raise HTTPException(413, f"PDF limit {MAX_PDF_BYTES // (1024 * 1024)} MB hai. Chhoti PDF upload karein.")
    finally:
        await file.close()
    if not data:
        raise HTTPException(400, "PDF file khaali hai.")
    try:
        return await run_in_threadpool(get_manager().create_pdf, session, file.filename or "document.pdf", bytes(data), ocr)
    except TextError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/text-jobs")
async def create_text(request: Request):
    require_client(request)
    session = session_id(request)
    body = await limited_json(request)
    text = validate_text(body.get("text", ""))
    return await run_in_threadpool(get_manager().create_text, session, text)


@app.get("/api/jobs")
async def list_jobs(request: Request):
    return {"jobs": get_manager().list(session_id(request))}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    return get_manager().public(job_id, session_id(request))


@app.get("/api/jobs/{job_id}/text")
async def job_text(job_id: str, request: Request, download: bool = False, roman: bool = False):
    mgr = get_manager()
    session = session_id(request)
    job = mgr.get(job_id, session)
    text = await run_in_threadpool(mgr.read_text, job_id, session)
    if roman:
        text = await run_in_threadpool(roman_hindi, text)
    if download:
        suffix = "-hinglish.txt" if roman else "-text.txt"
        filename = Path(job["filename"]).stem + suffix
        return Response(
            text, media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    return {"text": text, "revision": job["revision"], "roman": roman}


@app.put("/api/jobs/{job_id}/text")
async def edit_text(job_id: str, request: Request):
    require_client(request)
    session = session_id(request)
    body = await limited_json(request)
    return await run_in_threadpool(get_manager().edit_text, job_id, session, body.get("text", ""))


@app.post("/api/jobs/{job_id}/generate")
async def generate(job_id: str, request: Request):
    require_client(request)
    session = session_id(request)
    body = await limited_json(request)
    voice = body.get("voice", DEFAULT_VOICE)
    speed = body.get("speed", 1.0)
    if not isinstance(voice, str):
        raise HTTPException(400, "Voice ID string honi chahiye.")
    return await run_in_threadpool(get_manager().request_generate, job_id, session, voice, speed)


@app.post("/api/jobs/{job_id}/retry")
async def retry(job_id: str, request: Request):
    require_client(request)
    session = session_id(request)
    body = await limited_json(request)
    voice = body.get("voice")
    speed = body.get("speed")
    if voice is not None and not isinstance(voice, str):
        raise HTTPException(400, "Voice ID string honi chahiye.")
    return await run_in_threadpool(get_manager().retry, job_id, session, voice, speed)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str, request: Request):
    require_client(request)
    return get_manager().cancel(job_id, session_id(request))


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, request: Request):
    require_client(request)
    await run_in_threadpool(get_manager().delete, job_id, session_id(request))
    return {"deleted": True}


@app.get("/api/jobs/{job_id}/download")
async def download(job_id: str, request: Request):
    mgr = get_manager()
    job = mgr.get(job_id, session_id(request))
    path = mgr._dir(job_id) / "audio.mp3"
    if job["status"] != "completed" or not path.exists():
        raise HTTPException(409, "MP3 abhi ready nahi hai. Job complete hone ka wait karein.")
    return FileResponse(path, media_type="audio/mpeg", filename=job["audio"]["filename"])


@app.post("/api/sample")
async def sample(request: Request):
    require_client(request)
    session = session_id(request)
    body = await limited_json(request)
    voice = body.get("voice", DEFAULT_VOICE)
    speed = body.get("speed", 1.0)
    if not isinstance(voice, str) or voice not in VOICE_OPTIONS:
        raise HTTPException(400, "Unknown voice.")
    if not isinstance(speed, (int, float)) or not 0.75 <= float(speed) <= 1.5:
        raise HTTPException(400, "Speed 0.75x–1.5x honi chahiye.")
    text = clean_text(body.get("text") or SAMPLE_TEXT)
    if not text or len(text) > 300:
        raise HTTPException(400, "Sample text 1–300 characters ka rakhein.")
    now = time.time()
    calls = _sample_calls[session]
    while calls and calls[0] < now - 60:
        calls.popleft()
    if len(calls) >= 8:
        raise HTTPException(429, "Bahut saare sample requests. Ek minute baad try karein.")
    calls.append(now)
    speed = round(float(speed), 2)
    key = hashlib.sha256(f"{voice}:{speed}:{text}".encode()).hexdigest()[:24]
    output = SAMPLES / f"{key}.mp3"

    def make_sample():
        with _sample_lock:
            if output.exists():
                return output
            chunk = SAMPLES / f"{key}.chunk{chunk_extension(voice)}"
            try:
                synthesize_chunk(text, voice, speed, chunk)
                finalize_mp3([chunk], output, "Dhvani sample")
            finally:
                chunk.unlink(missing_ok=True)
            return output

    try:
        path = await run_in_threadpool(make_sample)
        return FileResponse(path, media_type="audio/mpeg", filename="dhvani-sample.mp3")
    except (TTSError, Cancelled) as exc:
        raise HTTPException(503, str(exc) or "Sample cancelled.") from exc


app.mount("/static", StaticFiles(directory=STATIC), name="static")
