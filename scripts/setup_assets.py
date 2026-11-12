#!/usr/bin/env python3
"""Download pinned, free-to-download assets into .runtime (never into Git).

Network hosts used: api.github.com and codeload.github.com.
The voice model is mirrored from a public GitHub repo; its original bytes are
SHA-256 checked before sherpa-onnx metadata is added. See THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dhvani.config import (  # noqa: E402
    ESPEAK_DATA, MODEL_CONFIG, MODEL_DIR, MODEL_PATH, RUNTIME, TESSDATA, TOKENS_PATH,
    ensure_dirs, local_assets_ready, ocr_assets_ready,
)

MODEL_REPO = "anmol-shrivastav/tts-hindi"
MODEL_PIN = "1aa621cac173d940536e6d8376779094a122abaf"
MODEL_SHA = "aa63bcf2cd493b55a450f280e23cf77f03afc9af7015e6e5acd43b652f166c88"
CONFIG_SHA = "5efc0ccf7529f3528996d46e0fac1f969f681d44a8e55bfa6236ff8841b5d52d"
ESPEAK_REPO = "iprincegarg/hawkeye-api"
ESPEAK_PIN = "c819e517f1dbacb3b479997a4dd832e681f11139"
ESPEAK_CRITICAL = {
    "hi_dict": "c612100bc5a6a59e0d6d00341093a9ddc7dd1d88",
    "phontab": "5c25ca1f9ffd3d80c0bba5a5dea59edfdb9de573",
    "phondata": "5b3c94a570dc3bdc6500dcd92602faa0640503bc",
    "phonindex": "03ba8068e7ab71932d2d1b2d6e55b5d63447b30d",
    "intonations": "ca2d4b362c3dc1dac7b5da760c33f7ad9c96047a",
}
TESS_REPO = "tesseract-ocr/tessdata_fast"
TESS_PIN = "87416418657359cb625c412a48b6e1d6d41c29bd"
TESS_SHA = {
    "hin": "4c73ffc59d497c186b19d1e90f5d721d678ea6b2e277b719bee4e2af12271825",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def git_blob_sha1(path: pathlib.Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def download(url: str, dest: pathlib.Path, expected: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if expected and dest.exists() and sha256(dest) == expected:
        print(f"  cached {dest.name}")
        return
    print(f"  download {dest.name}")
    part = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github.raw+json", "User-Agent": "Dhvani-setup/1.0"})
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:
            while block := response.read(1024 * 1024):
                out.write(block)
                h.update(block)
        if expected and h.hexdigest() != expected:
            raise RuntimeError(f"Checksum mismatch for {dest.name}; download delete karke retry karein.")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


def raw_url(repo: str, path: str, pin: str) -> str:
    return f"https://api.github.com/repos/{repo}/contents/{path}?ref={pin}"


def prepare_model() -> None:
    download(raw_url(MODEL_REPO, "models/hi_IN-priyamvada-medium.onnx", MODEL_PIN), MODEL_PATH, MODEL_SHA)
    download(raw_url(MODEL_REPO, "models/hi_IN-priyamvada-medium.onnx.json", MODEL_PIN), MODEL_CONFIG, CONFIG_SHA)
    config = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
    import onnx

    model = onnx.load(str(MODEL_PATH))
    existing = {item.key for item in model.metadata_props}
    metadata = {
        "model_type": "vits", "comment": "piper",
        "language": config["language"]["name_english"], "voice": config["espeak"]["voice"],
        "has_espeak": 1, "n_speakers": config["num_speakers"],
        "sample_rate": config["audio"]["sample_rate"],
    }
    changed = False
    for key, value in metadata.items():
        if key not in existing:
            item = model.metadata_props.add()
            item.key, item.value = key, str(value)
            changed = True
    if changed:
        onnx.save(model, str(MODEL_PATH))
    with TOKENS_PATH.open("w", encoding="utf-8") as f:
        for symbol, ids in sorted(config["phoneme_id_map"].items(), key=lambda item: item[1][0]):
            f.write(f"{symbol} {ids[0]}\n")


def espeak_ready() -> bool:
    return all((ESPEAK_DATA / name).exists() and git_blob_sha1(ESPEAK_DATA / name) == digest for name, digest in ESPEAK_CRITICAL.items())


def prepare_espeak() -> None:
    if espeak_ready():
        print("  cached espeak-ng-data")
        return
    url = f"https://codeload.github.com/{ESPEAK_REPO}/tar.gz/{ESPEAK_PIN}"
    print("  download espeak-ng-data (sirf data files extract hongi)")
    marker = "/piper/espeak-ng-data/"
    request = urllib.request.Request(url, headers={"User-Agent": "Dhvani-setup/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
        for member in archive:
            if not member.isfile() or marker not in member.name:
                continue
            relative = member.name.split(marker, 1)[1]
            target = (ESPEAK_DATA / relative).resolve()
            if not relative or ".." in pathlib.PurePosixPath(relative).parts or not target.is_relative_to(ESPEAK_DATA.resolve()):
                raise RuntimeError("Unsafe path in espeak archive")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as out:
                while block := source.read(1024 * 1024):
                    out.write(block)
    if not espeak_ready():
        raise RuntimeError("espeak-ng-data critical files verify nahi hue.")


def main() -> None:
    ensure_dirs()
    manifest_path = RUNTIME / "assets_manifest.json"
    if local_assets_ready() and ocr_assets_ready() and espeak_ready() and manifest_path.exists():
        print("Assets already ready hain. Kuch download nahi hua.")
        return
    print("Dhvani assets setup (~70 MB download; model taiyaar hone par ~85 MB disk):")
    prepare_model()
    prepare_espeak()
    for lang, digest in TESS_SHA.items():
        download(raw_url(TESS_REPO, f"{lang}.traineddata", TESS_PIN), TESSDATA / f"{lang}.traineddata", digest)
    manifest = {
        "model_source": f"{MODEL_REPO}@{MODEL_PIN}", "model_original_sha256": MODEL_SHA,
        "model_prepared_sha256": sha256(MODEL_PATH), "config_sha256": CONFIG_SHA,
        "espeak_source": f"{ESPEAK_REPO}@{ESPEAK_PIN}", "espeak_critical_git_blobs": ESPEAK_CRITICAL,
        "tessdata_source": f"{TESS_REPO}@{TESS_PIN}", "tessdata_sha256": TESS_SHA,
        "note": "Prepared model has sherpa-onnx metadata added; original source hash is recorded above.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Done. Ab `python -m uvicorn dhvani.app:app --host 0.0.0.0 --port 8000` chalayein.")


if __name__ == "__main__":
    main()
