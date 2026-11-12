#!/usr/bin/env python3
"""Dhvani skill CLI: poori Hindi PDF/text se ek MP3, bina summary ke."""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dhvani.config import CACHE, VOICE_OPTIONS  # noqa: E402
from dhvani.pdf import extract_pdf  # noqa: E402
from dhvani.text import chunk_text, roman_hindi, validate_text  # noqa: E402
from dhvani.tts import chunk_extension, finalize_mp3, synthesize_chunk, valid_chunk  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Hindi PDF/text -> full MP3 (default: free local neural voice)")
    parser.add_argument("input", type=pathlib.Path, help=".pdf, .txt, ya .md file")
    parser.add_argument("-o", "--output", type=pathlib.Path, help="Output .mp3 path")
    parser.add_argument("--voice", choices=list(VOICE_OPTIONS), default="priyamvada")
    parser.add_argument("--speed", type=float, default=1.0, help="0.75–1.5")
    parser.add_argument("--no-ocr", action="store_true", help="Scanned-page OCR band karein")
    parser.add_argument("--roman-text", type=pathlib.Path, help="Approximate Hinglish preview bhi save karein")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"Input file nahi mili: {args.input}")
    if not 0.75 <= args.speed <= 1.5:
        parser.error("--speed 0.75–1.5 ke beech rakhein")
    output = args.output or args.input.with_suffix(".mp3")
    if output.suffix.lower() != ".mp3":
        parser.error("Output filename .mp3 honi chahiye")
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.input.suffix.lower() == ".pdf":
        print("PDF padhi ja rahi hai…", flush=True)
        result = extract_pdf(args.input, ocr=not args.no_ocr, progress=lambda d, t: print(f"\rPages {d}/{t}", end="", flush=True))
        print()
        text = result.text
        for warning in result.warnings:
            print(f"Note: {warning}")
    else:
        text = args.input.read_text(encoding="utf-8")
    text = validate_text(text)
    if args.roman_text:
        args.roman_text.parent.mkdir(parents=True, exist_ok=True)
        args.roman_text.write_text(roman_hindi(text), encoding="utf-8")
    chunks = chunk_text(text)
    key = hashlib.sha256(f"{text}\n{args.voice}\n{args.speed:.2f}\nv1".encode()).hexdigest()[:20]
    folder = CACHE / "cli" / key
    folder.mkdir(parents=True, exist_ok=True)
    ext = chunk_extension(args.voice)
    paths = []
    start = time.time()
    for index, chunk in enumerate(chunks):
        path = folder / f"{index:05d}{ext}"
        if not valid_chunk(path):
            synthesize_chunk(chunk, args.voice, args.speed, path)
        paths.append(path)
        print(f"\rAudio chunks {index + 1}/{len(chunks)}", end="", flush=True)
    print()
    audio = finalize_mp3(paths, output, args.input.stem + " — Dhvani")
    print(f"MP3 ready: {output.resolve()}")
    print(f"Duration: {audio['duration']:.1f}s · Size: {audio['bytes'] / 1024 / 1024:.2f} MB · Time: {time.time() - start:.1f}s")
    print("Poora reviewed text include hua; koi summary nahi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
