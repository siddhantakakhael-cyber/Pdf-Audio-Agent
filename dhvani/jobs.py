from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import (
    CHUNK_CHARS,
    JOB_TTL_SECONDS,
    JOBS,
    MAX_ACTIVE_PER_SESSION,
    MAX_PENDING_GLOBAL,
    VOICE_OPTIONS,
    WORKERS,
    ensure_dirs,
)
from .pdf import Cancelled, extract_pdf
from .text import TextError, chunk_text, render_key, validate_text
from .tts import TTSError, chunk_extension, finalize_mp3, synthesize_chunk, valid_chunk

ACTIVE = {"extracting", "queued", "generating"}
JOB_ID = re.compile(r"^[a-f0-9]{32}$")


class JobError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return (name or "document.pdf")[:160]


def session_hash(session: str) -> str:
    return hashlib.sha256(session.encode()).hexdigest()


class JobManager:
    def __init__(self, root: Path = JOBS, workers: int = WORKERS):
        ensure_dirs()
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, threading.Event] = {}
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dhvani")
        self._closed = False
        self._load()

    def _load(self) -> None:
        for path in self.root.iterdir():
            state = path / "state.json"
            if not path.is_dir() or not JOB_ID.fullmatch(path.name) or not state.exists():
                continue
            try:
                job = json.loads(state.read_text(encoding="utf-8"))
                if job.get("status") in ACTIVE:
                    job["status"] = "failed"
                    job["error"] = "Server restart hua tha. Retry karein; completed audio chunks reuse honge."
                    job["error_code"] = "restarted"
                    job["cancel_requested"] = False
                self.jobs[path.name] = job
                self._persist(job)
            except (OSError, ValueError, KeyError):
                continue

    def _dir(self, job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id):
            raise JobError("Invalid job ID.", 404)
        return self.root / job_id

    def _persist(self, job: dict[str, Any]) -> None:
        path = self._dir(job["id"]) / "state.json"
        part = path.with_suffix(".tmp")
        part.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(part, path)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.update(fields)
            job["updated_at"] = time.time()
            self._persist(job)

    def _check_capacity(self, owner: str) -> None:
        active = [j for j in self.jobs.values() if j["status"] in ACTIVE]
        if sum(j["owner"] == owner for j in active) >= MAX_ACTIVE_PER_SESSION:
            raise JobError(f"Ek saath {MAX_ACTIVE_PER_SESSION} jobs tak. Kisi job ke complete/cancel hone ka wait karein.", 429)
        if len(active) >= MAX_PENDING_GLOBAL:
            raise JobError("Server abhi busy hai. Thodi der baad try karein.", 429)

    def _new(self, session: str, filename: str) -> dict[str, Any]:
        with self.lock:
            if self._closed:
                raise JobError("Server band ho raha hai.", 503)
            owner = session_hash(session)
            self._check_capacity(owner)
            job_id = uuid.uuid4().hex
            path = self.root / job_id
            path.mkdir()
            (path / "chunks").mkdir()
            now = time.time()
            job = {
                "id": job_id, "owner": owner, "filename": safe_filename(filename),
                "status": "queued", "stage": "extract", "created_at": now, "updated_at": now,
                "pages": 0, "char_count": 0, "revision": 0, "warnings": [],
                "ocr_pages": [], "empty_pages": [], "progress": {"done": 0, "total": 0},
                "settings": None, "render_key": None, "audio": None,
                "error": None, "error_code": None, "cancel_requested": False,
            }
            self.jobs[job_id] = job
            self.events[job_id] = threading.Event()
            self._persist(job)
            return job

    def create_pdf(self, session: str, filename: str, data: bytes, ocr: bool) -> dict[str, Any]:
        if not data.startswith(b"%PDF-"):
            raise JobError("Sirf valid PDF upload karein. File ka header PDF nahi hai.")
        job = self._new(session, filename)
        path = self._dir(job["id"])
        (path / "original.pdf").write_bytes(data)
        self._update(job["id"], ocr=ocr, pdf_bytes=len(data))
        self._submit_extract(job["id"])
        return self.public(job["id"], session)

    def create_text(self, session: str, text: str) -> dict[str, Any]:
        cleaned = validate_text(text)
        job = self._new(session, "pasted-text.txt")
        self._write_text(job["id"], cleaned)
        self._update(
            job["id"], status="ready", char_count=len(cleaned),
            warnings=["Yeh paste kiya hua text hai; audio banane se pehle review karein."],
        )
        return self.public(job["id"], session)

    def get(self, job_id: str, session: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["owner"] != session_hash(session):
                raise JobError("Job nahi mili, ya is browser session ki nahi hai.", 404)
            return job

    def public(self, job_id: str, session: str) -> dict[str, Any]:
        with self.lock:
            job = self.get(job_id, session)
            out = {k: v for k, v in job.items() if k not in {"owner", "render_key", "ocr"}}
            out["download_url"] = f"/api/jobs/{job_id}/download" if job["status"] == "completed" else None
            out["text_url"] = f"/api/jobs/{job_id}/text"
            return out

    def list(self, session: str) -> list[dict[str, Any]]:
        with self.lock:
            owner = session_hash(session)
            ids = sorted(
                (j["id"] for j in self.jobs.values() if j["owner"] == owner),
                key=lambda i: self.jobs[i]["created_at"], reverse=True,
            )[:20]
        return [self.public(i, session) for i in ids]

    def _write_text(self, job_id: str, text: str) -> None:
        path = self._dir(job_id) / "text.txt"
        part = path.with_suffix(".tmp")
        part.write_text(text, encoding="utf-8")
        os.replace(part, path)

    def read_text(self, job_id: str, session: str) -> str:
        self.get(job_id, session)
        path = self._dir(job_id) / "text.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def edit_text(self, job_id: str, session: str, text: str) -> dict[str, Any]:
        cleaned = validate_text(text)
        with self.lock:
            job = self.get(job_id, session)
            if job["status"] in ACTIVE:
                raise JobError("Active job ka text edit nahi kar sakte. Pehle cancel karein.", 409)
            self._write_text(job_id, cleaned)
            self._dir(job_id).joinpath("audio.mp3").unlink(missing_ok=True)
            self._update(
                job_id, status="ready", stage="edit", char_count=len(cleaned),
                revision=job["revision"] + 1, audio=None, render_key=None,
                error=None, error_code=None, progress={"done": 0, "total": 0},
            )
        return self.public(job_id, session)

    def _submit_extract(self, job_id: str) -> None:
        with self.lock:
            event = self.events.setdefault(job_id, threading.Event())
            event.clear()
            self._update(job_id, status="extracting", stage="extract", error=None, error_code=None, cancel_requested=False)
            self.executor.submit(self._extract_worker, job_id, event)

    def _extract_worker(self, job_id: str, event: threading.Event) -> None:
        try:
            job = self.get_internal(job_id)
            def progress(done: int, total: int) -> None:
                if event.is_set():
                    raise Cancelled()
                self._update(job_id, pages=total, progress={"done": done, "total": total})

            result = extract_pdf(
                self._dir(job_id) / "original.pdf", ocr=bool(job.get("ocr", True)),
                progress=progress, cancelled=event.is_set,
            )
            cleaned = validate_text(result.text)
            if event.is_set():
                raise Cancelled()
            self._write_text(job_id, cleaned)
            self._update(
                job_id, status="ready", text_ready=True, char_count=len(cleaned), pages=result.pages,
                warnings=result.warnings, ocr_pages=result.ocr_pages, empty_pages=result.empty_pages,
                progress={"done": result.pages, "total": result.pages},
            )
        except Cancelled:
            self._update(job_id, status="cancelled", error=None, error_code=None)
        except TextError as exc:
            self._update(job_id, status="failed", error=str(exc), error_code="extraction")
        except Exception:
            self._update(job_id, status="failed", error="PDF process nahi ho payi. File check karke retry karein.", error_code="extraction")

    def get_internal(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            return dict(self.jobs[job_id])

    def request_generate(
        self, job_id: str, session: str, voice: str, speed: float, *, retry: bool = False
    ) -> dict[str, Any]:
        if voice not in VOICE_OPTIONS:
            raise JobError("Yeh voice available nahi hai.")
        if not isinstance(speed, (int, float)) or not 0.75 <= float(speed) <= 1.5:
            raise JobError("Speed 0.75x se 1.5x ke beech rakhein.")
        speed = round(float(speed), 2)
        with self.lock:
            job = self.get(job_id, session)
            if job["status"] in ACTIVE:
                raise JobError("Job pehle se chal rahi hai.", 409)
            if self._closed:
                raise JobError("Server band ho raha hai.", 503)
            text = self.read_text(job_id, session)
            if not text:
                raise JobError("Pehle PDF extract karein ya text paste karein.", 409)
            self._check_capacity(job["owner"])
            key = "v1:" + render_key(text, voice, speed) + f":{CHUNK_CHARS}"
            if job.get("render_key") != key:
                shutil.rmtree(self._dir(job_id) / "chunks", ignore_errors=True)
                (self._dir(job_id) / "chunks").mkdir()
                self._dir(job_id).joinpath("audio.mp3").unlink(missing_ok=True)
            event = self.events.setdefault(job_id, threading.Event())
            event.clear()
            self._update(
                job_id, status="queued", stage="generate", settings={"voice": voice, "speed": speed},
                render_key=key, audio=None, error=None, error_code=None, cancel_requested=False,
            )
            self.executor.submit(self._generate_worker, job_id, event)
        return self.public(job_id, session)

    def _generate_worker(self, job_id: str, event: threading.Event) -> None:
        try:
            if event.is_set():
                raise Cancelled()
            job = self.get_internal(job_id)
            text = (self._dir(job_id) / "text.txt").read_text(encoding="utf-8")
            chunks = chunk_text(text)
            if not chunks:
                raise TextError("Audio ke liye text khaali hai.")
            voice = job["settings"]["voice"]
            speed = job["settings"]["speed"]
            ext = chunk_extension(voice)
            folder = self._dir(job_id) / "chunks"
            folder.mkdir(exist_ok=True)
            self._update(job_id, status="generating", progress={"done": 0, "total": len(chunks)})
            paths: list[Path] = []
            for index, chunk in enumerate(chunks):
                if event.is_set():
                    raise Cancelled()
                path = folder / f"{index:05d}{ext}"
                if not valid_chunk(path):
                    synthesize_chunk(chunk, voice, speed, path, cancelled=event.is_set)
                paths.append(path)
                self._update(job_id, progress={"done": index + 1, "total": len(chunks)})
            if event.is_set():
                raise Cancelled()
            title = Path(job["filename"]).stem + " — Dhvani"
            audio = finalize_mp3(paths, self._dir(job_id) / "audio.mp3", title)
            stem = re.sub(r"[^\w\-]+", "-", Path(job["filename"]).stem, flags=re.UNICODE).strip("-")[:80] or "dhvani"
            audio["filename"] = f"{stem}-dhvani.mp3"
            self._update(job_id, status="completed", audio=audio, error=None, error_code=None)
        except Cancelled:
            self._update(job_id, status="cancelled", error=None, error_code=None)
        except (TextError, TTSError) as exc:
            job = self.get_internal(job_id)
            edge = job.get("settings", {}).get("voice", "").startswith("hi-IN-")
            code = "edge_unavailable" if edge else "synthesis"
            self._update(job_id, status="failed", error=str(exc), error_code=code)
        except Exception:
            self._update(job_id, status="failed", error="Audio banate waqt error aaya. Retry karein; completed chunks safe hain.", error_code="synthesis")

    def cancel(self, job_id: str, session: str) -> dict[str, Any]:
        with self.lock:
            job = self.get(job_id, session)
            if job["status"] in ACTIVE:
                self.events.setdefault(job_id, threading.Event()).set()
                self._update(job_id, cancel_requested=True)
        return self.public(job_id, session)

    def retry(self, job_id: str, session: str, voice: str | None = None, speed: float | None = None) -> dict[str, Any]:
        job = self.get(job_id, session)
        if job["status"] in ACTIVE:
            raise JobError("Job abhi chal rahi hai.", 409)
        if job["stage"] == "extract" and not (self._dir(job_id) / "text.txt").exists():
            with self.lock:
                self._check_capacity(job["owner"])
                self._submit_extract(job_id)
            return self.public(job_id, session)
        settings = job.get("settings") or {"voice": "priyamvada", "speed": 1.0}
        return self.request_generate(job_id, session, voice or settings["voice"], speed if speed is not None else settings["speed"], retry=True)

    def delete(self, job_id: str, session: str) -> None:
        with self.lock:
            job = self.get(job_id, session)
            if job["status"] in ACTIVE:
                raise JobError("Active job delete nahi hoti. Pehle cancel karein.", 409)
            shutil.rmtree(self._dir(job_id))
            del self.jobs[job_id]
            self.events.pop(job_id, None)

    def cleanup(self) -> int:
        cutoff = time.time() - JOB_TTL_SECONDS
        with self.lock:
            stale = [j["id"] for j in self.jobs.values() if j["status"] not in ACTIVE and j["updated_at"] < cutoff]
            for job_id in stale:
                shutil.rmtree(self._dir(job_id), ignore_errors=True)
                self.jobs.pop(job_id, None)
                self.events.pop(job_id, None)
        return len(stale)

    def shutdown(self) -> None:
        with self.lock:
            self._closed = True
            for event in self.events.values():
                event.set()
            self.executor.shutdown(wait=False, cancel_futures=True)
