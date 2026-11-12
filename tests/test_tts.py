import pathlib
import wave

import numpy as np
import pytest
from mutagen.mp3 import MP3

from dhvani.config import SAMPLE_TEXT
from dhvani.tts import chunk_extension, encode_wav_to_mp3, finalize_mp3, synthesize_chunk, valid_chunk
from tests.conftest import requires_local


def fake_wav(path: pathlib.Path, seconds=0.15):
    rate = 22050
    t = np.arange(int(rate * seconds)) / rate
    samples = (np.sin(2 * np.pi * 220 * t) * 8000).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(samples.tobytes())


def fake_mp3(path: pathlib.Path, seconds=0.15):
    wav = path.with_suffix(".fake.wav")
    try:
        fake_wav(wav, seconds)
        encode_wav_to_mp3(wav, path)
    finally:
        wav.unlink(missing_ok=True)


def test_finalize_multiple_chunks(tmp_path):
    chunks = []
    for i in range(3):
        path = tmp_path / f"{i}.mp3"
        fake_mp3(path)
        assert valid_chunk(path)
        chunks.append(path)
    out = tmp_path / "full.mp3"
    info = finalize_mp3(chunks, out, "Test")
    assert out.exists() and info["bytes"] > 512
    # Concatenated MP3 chunks can include a little encoder padding per chunk.
    assert 0.44 <= MP3(out).info.length < 0.9
    assert info["chunks"] == 3


@requires_local
def test_local_neural_hindi_roundtrip(tmp_path):
    chunk = tmp_path / ("sample" + chunk_extension("priyamvada"))
    synthesize_chunk(SAMPLE_TEXT, "priyamvada", 1.0, chunk)
    assert valid_chunk(chunk)
    assert chunk.stat().st_size < 200000  # compressed cache, not a large WAV
    out = tmp_path / "sample.mp3"
    info = finalize_mp3([chunk], out, "Dhvani test")
    assert info["duration"] > 3
    assert MP3(out).info.sample_rate == 22050
