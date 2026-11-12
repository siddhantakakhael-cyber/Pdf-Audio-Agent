from __future__ import annotations

import asyncio
import subprocess
import threading
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from mutagen.mp3 import MP3

from .config import (
    ESPEAK_DATA,
    MODEL_PATH,
    TOKENS_PATH,
    VOICE_OPTIONS,
    local_assets_ready,
)
from .pdf import Cancelled


class TTSError(RuntimeError):
    """Safe, actionable speech-generation error."""


class LocalEngine:
    """One cached CPU model; serialize access because the native handle is shared."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tts = None

    def generate(self, text: str, speed: float, output: Path) -> None:
        if not local_assets_ready():
            raise TTSError("Local voice model missing hai. Terminal mein `python scripts/setup_assets.py` chalayein.")
        with self._lock:
            if self._tts is None:
                try:
                    import sherpa_onnx

                    config = sherpa_onnx.OfflineTtsConfig(
                        model=sherpa_onnx.OfflineTtsModelConfig(
                            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                                model=str(MODEL_PATH),
                                tokens=str(TOKENS_PATH),
                                data_dir=str(ESPEAK_DATA),
                            ),
                            num_threads=2,
                            provider="cpu",
                        ),
                        max_num_sentences=1,
                        silence_scale=0.2,
                    )
                    if not config.validate():
                        raise TTSError("Local model config invalid hai. Setup script dobara chalayein.")
                    self._tts = sherpa_onnx.OfflineTts(config)
                except TTSError:
                    raise
                except Exception as exc:
                    raise TTSError("Local voice load nahi hui. Setup script chalayein ya online voice try karein.") from exc
            audio = self._tts.generate(text, sid=0, speed=speed)
            if not audio.samples or audio.sample_rate <= 0:
                raise TTSError("Is text chunk se audio nahi bani. Text review karke dobara try karein.")
            samples = (np.clip(np.asarray(audio.samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
            part = output.with_suffix(output.suffix + ".part")
            with wave.open(str(part), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(audio.sample_rate)
                wav.writeframes(samples.tobytes())
            part.replace(output)


LOCAL_ENGINE = LocalEngine()


async def _edge_chunk(text: str, voice: str, speed: float, output: Path, cancelled) -> None:
    import edge_tts

    part = output.with_suffix(output.suffix + ".part")
    rate = f"{round((speed - 1) * 100):+d}%"
    try:
        with part.open("wb") as file:
            communicate = edge_tts.Communicate(
                text, voice, rate=rate, connect_timeout=10, receive_timeout=25
            )
            received = 0
            async for item in communicate.stream():
                if cancelled and cancelled():
                    raise Cancelled()
                if item["type"] == "audio":
                    file.write(item["data"])
                    received += len(item["data"])
            if received < 512:
                raise edge_tts.exceptions.NoAudioReceived("No audio received")
        part.replace(output)
    except Cancelled:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise TTSError(
            "Online voice service se connect nahi ho paya. Internet/firewall ya service limit ho sakti hai. "
            "Local Priyamvada voice try karein; woh bina internet ke chalti hai."
        ) from exc


def synthesize_chunk(
    text: str, voice: str, speed: float, output: Path, cancelled=None
) -> None:
    if cancelled and cancelled():
        raise Cancelled()
    option = VOICE_OPTIONS.get(voice)
    if not option:
        raise TTSError("Unknown voice. Available voices mein se choose karein.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if option["engine"] == "local":
        temp_wav = output.with_suffix(".tmp.wav")
        try:
            LOCAL_ENGINE.generate(text, speed, temp_wav)
            if cancelled and cancelled():
                raise Cancelled()
            encode_wav_to_mp3(temp_wav, output)
        finally:
            temp_wav.unlink(missing_ok=True)
    else:
        async def run() -> None:
            last: Exception | None = None
            for attempt in range(2):
                try:
                    await asyncio.wait_for(_edge_chunk(text, voice, speed, output, cancelled), timeout=55)
                    return
                except Cancelled:
                    raise
                except Exception as exc:
                    last = exc
                    if attempt == 0:
                        await asyncio.sleep(1.5)
            raise TTSError(str(last)) if last else TTSError("Audio generate nahi hui.")

        asyncio.run(run())
    if cancelled and cancelled():
        output.unlink(missing_ok=True)
        raise Cancelled()


def chunk_extension(voice: str) -> str:
    # Cache compressed chunks so long books do not create huge WAV artifacts.
    return ".mp3"


def valid_chunk(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size < 128:
            return False
        if path.suffix == ".wav":
            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() > 0
        return MP3(path).info.length > 0
    except Exception:
        return False


def _run_ffmpeg(args: list[str]) -> None:
    try:
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        raise TTSError("MP3 join karte waqt timeout hua. Retry karein; completed chunks safe hain.") from exc
    if result.returncode != 0:
        raise TTSError("MP3 join nahi ho payi. Retry karein; completed chunks safe hain.")


def encode_wav_to_mp3(wav_path: Path, output: Path) -> None:
    part = output.with_suffix(".partial.mp3")
    try:
        _run_ffmpeg(
            [
                "-i", str(wav_path), "-map", "0:a:0", "-ac", "1", "-ar", "22050",
                "-c:a", "libmp3lame", "-b:a", "64k", "-map_metadata", "-1", str(part),
            ]
        )
        part.replace(output)
    finally:
        part.unlink(missing_ok=True)


def finalize_mp3(chunks: list[Path], output: Path, title: str) -> dict:
    if not chunks or not all(valid_chunk(p) for p in chunks):
        raise TTSError("Audio chunks incomplete hain. Retry se missing parts dobara banenge.")
    output.parent.mkdir(parents=True, exist_ok=True)
    listing = output.with_suffix(".concat.txt")
    listing.write_text(
        "".join("file '" + str(p.resolve()).replace("'", "'\\''") + "'\n" for p in chunks),
        encoding="utf-8",
    )
    part = output.with_suffix(".partial.mp3")
    try:
        _run_ffmpeg(
            [
                "-f", "concat", "-safe", "0", "-i", str(listing),
                "-map", "0:a:0", "-ac", "1", "-c:a", "copy",
                "-map_metadata", "-1", "-metadata", f"title={title[:180]}",
                str(part),
            ]
        )
        info = MP3(part)
        if not info.info.length or part.stat().st_size < 512:
            raise TTSError("Final MP3 empty hai. Text review karke retry karein.")
        part.replace(output)
        return {
            "filename": output.name,
            "bytes": output.stat().st_size,
            "duration": round(float(info.info.length), 2),
            "chunks": len(chunks),
        }
    finally:
        listing.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
