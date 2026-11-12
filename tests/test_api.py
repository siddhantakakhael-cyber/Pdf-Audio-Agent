import uuid

from dhvani.tts import TTSError
from tests.conftest import HEADERS, SESSION, requires_local, wait_job
from tests.test_tts import fake_mp3


def test_health_and_static(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["default_voice"] == "priyamvada"
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert "X-Content-Type-Options" in r.headers


def test_session_and_csrf_guards(client):
    assert client.get("/api/jobs", headers={"X-Dhvani-Session": ""}).status_code == 400
    assert client.post("/api/text-jobs", json={"text": "नमस्ते"}, headers={"X-Dhvani-Session": SESSION, "X-Dhvani-Client": ""}).status_code == 403
    job = client.post("/api/text-jobs", json={"text": "नमस्ते दुनिया"}).json()
    other = str(uuid.uuid4())
    assert client.get(f"/api/jobs/{job['id']}", headers={**HEADERS, "X-Dhvani-Session": other}).status_code == 404
    client.delete(f"/api/jobs/{job['id']}")


def test_invalid_pdf(client):
    r = client.post("/api/jobs", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 400


def test_upload_edit_roman_and_generate(client, hindi_pdf):
    r = client.post("/api/jobs", files={"file": ("हिन्दी-किताब.pdf", hindi_pdf.read_bytes(), "application/pdf")}, data={"ocr": "false"})
    assert r.status_code == 200, r.text
    job = wait_job(client, r.json()["id"])
    assert job["status"] == "ready", job
    assert "नमस्ते" in client.get(f"/api/jobs/{job['id']}/text").json()["text"]
    edited = client.put(f"/api/jobs/{job['id']}/text", json={"text": "नमस्ते। यह edited किताब है।"})
    assert edited.status_code == 200 and edited.json()["revision"] == 1
    roman = client.get(f"/api/jobs/{job['id']}/text?roman=true&download=true")
    assert roman.status_code == 200 and "namaste" in roman.text
    assert "filename*=UTF-8" in roman.headers["content-disposition"]
    if client.get("/api/health").json()["local_ready"]:
        r = client.post(f"/api/jobs/{job['id']}/generate", json={"voice": "priyamvada", "speed": 1.0})
        assert r.status_code == 200
        done = wait_job(client, job["id"])
        assert done["status"] == "completed", done
        audio = client.get(done["download_url"])
        assert audio.status_code == 200 and audio.content[:3] in {b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}
        assert audio.headers["content-type"].startswith("audio/mpeg")
    client.delete(f"/api/jobs/{job['id']}")


def test_failed_chunk_resumes_without_redoing_completed(client, monkeypatch):
    text = "यह परीक्षण वाक्य है। " * 160
    job = client.post("/api/text-jobs", json={"text": text}).json()
    calls = []
    fail_second = True

    def flaky(chunk, voice, speed, path, cancelled=None):
        calls.append(path.name)
        if fail_second and path.stem == "00001":
            raise TTSError("Simulated provider failure")
        fake_mp3(path)

    monkeypatch.setattr("dhvani.jobs.synthesize_chunk", flaky)
    r = client.post(f"/api/jobs/{job['id']}/generate", json={"voice": "priyamvada", "speed": 1.0})
    assert r.status_code == 200
    failed = wait_job(client, job["id"])
    assert failed["status"] == "failed"
    assert failed["progress"]["done"] == 1
    first_calls = list(calls)
    fail_second = False
    calls.clear()
    r = client.post(f"/api/jobs/{job['id']}/retry", json={})
    assert r.status_code == 200
    done = wait_job(client, job["id"])
    assert done["status"] == "completed", done
    assert "00000.mp3" in first_calls and "00000.mp3" not in calls
    assert done["audio"]["chunks"] == len(set(first_calls + calls))
    assert done["progress"]["done"] == done["audio"]["chunks"]
    client.delete(f"/api/jobs/{job['id']}")


@requires_local
def test_sample_endpoint(client):
    r = client.post("/api/sample", json={"voice": "priyamvada", "speed": 1.0, "text": "नमस्ते, यह आवाज़ का नमूना है।"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert len(r.content) > 1000


def test_bad_voice_and_speed(client):
    job = client.post("/api/text-jobs", json={"text": "नमस्ते"}).json()
    assert client.post(f"/api/jobs/{job['id']}/generate", json={"voice": "unknown"}).status_code == 400
    assert client.post(f"/api/jobs/{job['id']}/generate", json={"voice": "priyamvada", "speed": 9}).status_code == 400
    assert client.post("/api/sample", json={"voice": []}).status_code == 400
    client.delete(f"/api/jobs/{job['id']}")


def test_online_failure_can_switch_to_local(client, monkeypatch):
    job = client.post("/api/text-jobs", json={"text": "यह ऑनलाइन fallback का परीक्षण है।"}).json()

    def online_fail(chunk, voice, speed, path, cancelled=None):
        raise TTSError("Online service unavailable")

    monkeypatch.setattr("dhvani.jobs.synthesize_chunk", online_fail)
    client.post(f"/api/jobs/{job['id']}/generate", json={"voice": "hi-IN-SwaraNeural"})
    failed = wait_job(client, job["id"])
    assert failed["status"] == "failed" and failed["error_code"] == "edge_unavailable"

    monkeypatch.setattr("dhvani.jobs.synthesize_chunk", lambda chunk, voice, speed, path, cancelled=None: fake_mp3(path))
    r = client.post(f"/api/jobs/{job['id']}/retry", json={"voice": "priyamvada"})
    assert r.status_code == 200
    done = wait_job(client, job["id"])
    assert done["status"] == "completed" and done["settings"]["voice"] == "priyamvada"
    client.delete(f"/api/jobs/{job['id']}")


def test_edit_completed_text_invalidates_old_mp3(client, monkeypatch):
    monkeypatch.setattr("dhvani.jobs.synthesize_chunk", lambda chunk, voice, speed, path, cancelled=None: fake_mp3(path))
    job = client.post("/api/text-jobs", json={"text": "पुराना text"}).json()
    client.post(f"/api/jobs/{job['id']}/generate", json={"voice": "priyamvada"})
    done = wait_job(client, job["id"])
    assert done["status"] == "completed"
    edited = client.put(f"/api/jobs/{job['id']}/text", json={"text": "नया text"})
    assert edited.json()["status"] == "ready" and edited.json()["audio"] is None
    assert client.get(f"/api/jobs/{job['id']}/download").status_code == 409
    client.delete(f"/api/jobs/{job['id']}")
