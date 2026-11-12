import subprocess
import sys

from mutagen.mp3 import MP3

from tests.conftest import ROOT, requires_local


@requires_local
def test_cli_pdf_to_full_mp3(hindi_pdf, tmp_path):
    output = tmp_path / "book.mp3"
    roman = tmp_path / "book-hinglish.txt"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pdf_to_mp3.py"), str(hindi_pdf), "-o", str(output), "--roman-text", str(roman)],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert output.exists() and MP3(output).info.length > 3
    assert "namaste" in roman.read_text(encoding="utf-8")
    assert "MP3 ready" in result.stdout
