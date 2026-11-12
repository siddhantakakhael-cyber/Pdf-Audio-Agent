import re

import pytest

from dhvani.text import TextError, chunk_text, clean_text, render_key, roman_hindi, validate_text


def test_clean_preserves_content_and_joins_hyphenation():
    assert clean_text("  नमस्ते   दुनिया  \r\n यह किता-\nब है। \n\n\n अगला ") == "नमस्ते दुनिया\nयह किताब है।\n\nअगला"


def test_empty_and_oversize(monkeypatch):
    with pytest.raises(TextError):
        validate_text(" \n ")
    monkeypatch.setattr("dhvani.text.MAX_TEXT_CHARS", 10)
    with pytest.raises(TextError):
        validate_text("यह दस से बड़ा text है")


def test_chunks_cover_every_character_in_order():
    text = ("यह एक लंबा वाक्य है। " * 300) + "अंतिमशब्दबिनास्पेस" * 200 + "\n\nThe end."
    chunks = chunk_text(text, limit=177)
    assert chunks
    assert all(len(c) <= 177 for c in chunks)
    assert re.sub(r"\s+", "", "".join(chunks)) == re.sub(r"\s+", "", text)


def test_chunk_sentence_boundaries_when_possible():
    chunks = chunk_text("पहला वाक्य। दूसरा वाक्य। तीसरा वाक्य।", limit=18)
    assert all(c.endswith("।") for c in chunks)
    assert "दूसरा" in "".join(chunks)


def test_roman_hindi_is_readable_not_academic():
    out = roman_hindi("नमस्ते। यह एक किताब है। आज हम इसे आवाज़ में बदलेंगे। मैं हिन्दी पढ़ रहा हूँ। १२३ PDF audio")
    assert "namaste" in out and "yah ek kitaab" in out and "aaj ham" in out
    assert "main" in out and "123 PDF audio" in out
    assert "|" not in out and "ā" not in out


def test_render_key_changes_with_inputs():
    assert render_key("क", "priyamvada", 1.0) == render_key("क", "priyamvada", 1.0)
    assert render_key("क", "priyamvada", 1.0) != render_key("ख", "priyamvada", 1.0)
    assert render_key("क", "priyamvada", 1.0) != render_key("क", "priyamvada", 1.1)
