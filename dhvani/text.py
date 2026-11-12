from __future__ import annotations

import hashlib
import re
import unicodedata

from .config import CHUNK_CHARS, MAX_TEXT_CHARS

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE = re.compile(r"[^\S\n]+")
_SENTENCE = re.compile(r"(?<=[।॥.!?])\s+")


class TextError(ValueError):
    """User-facing input error."""


def clean_text(text: str) -> str:
    """Normalize whitespace without deleting or summarizing document content."""
    text = unicodedata.normalize("NFC", text)
    text = _CTRL.sub("", text).replace("\u00ad", "").replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Join words split by a line-ending hyphen; keep other line breaks for review.
    text = re.sub(r"([A-Za-z\u0900-\u097F])-\n([A-Za-z\u0900-\u097F])", r"\1\2", text)
    text = _SPACE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def validate_text(text: str) -> str:
    if not isinstance(text, str):
        raise TextError("Text string hona chahiye.")
    cleaned = clean_text(text)
    if not cleaned:
        raise TextError("PDF se koi text nahi mila. OCR on karke dobara upload karein, ya text paste karein.")
    if len(cleaned) > MAX_TEXT_CHARS:
        raise TextError(f"Text bahut bada hai ({len(cleaned):,} characters). Limit {MAX_TEXT_CHARS:,} hai; PDF ko parts mein baantein.")
    return cleaned


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Cover all text, in order, with bounded chunks and no mid-word cuts when avoidable."""
    text = clean_text(text)
    if not text:
        return []
    if limit < 1:
        raise ValueError("limit must be positive")
    pieces: list[str] = []
    for paragraph in re.split(r"\n+", text):
        for sentence in _SENTENCE.split(paragraph):
            sentence = sentence.strip()
            while len(sentence) > limit:
                window = sentence[: limit + 1]
                cut = window.rfind(" ", 0, limit + 1)
                if cut <= 0:
                    cut = limit
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                pieces.append(sentence)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > limit:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ॲ": "a",
}
_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh",
    "ज": "j", "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh",
    "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p",
    "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l",
    "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}
_SIGNS = {"ं": "n", "ँ": "n", "ः": "h", "ऽ": "", "़": ""}
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def roman_hindi(text: str) -> str:
    """Hindi-aware approximate Roman preview (not academic IAST or translation).

    Keeps Latin text as-is. Deletes only a word-final inherent schwa, which is
    normal Hindi pronunciation: किताब -> kitaab, आज -> aaj, यह -> yah.
    """
    text = unicodedata.normalize("NFC", text).translate(_DIGITS)
    out: list[str] = []
    pending_schwa = -1

    def flush_schwa() -> None:
        nonlocal pending_schwa
        if pending_schwa >= 0 and pending_schwa == len(out) - 1 and out[-1] == "a":
            out.pop()
        pending_schwa = -1

    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _CONSONANTS:
            out.append(_CONSONANTS[ch])
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if nxt == "्":
                i += 2
                continue
            if nxt in _MATRAS:
                out.append(_MATRAS[nxt])
                i += 2
                continue
            out.append("a")
            pending_schwa = len(out) - 1
            i += 1
            continue
        flush_schwa()
        if ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _SIGNS:
            out.append(_SIGNS[ch])
        elif ch == "।":
            out.append(".")
        elif ch == "॥":
            out.append("..")
        elif ch in {"्", "\u200c", "\u200d"}:
            pass
        else:
            out.append(ch)
        i += 1
    flush_schwa()
    return "".join(out)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_key(text: str, voice: str, speed: float) -> str:
    return text_hash(f"{text}\n{voice}\n{speed:.2f}")
