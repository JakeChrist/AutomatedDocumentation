from chunk_utils import get_tokenizer, chunk_text


def test_get_tokenizer_roundtrip() -> None:
    tokenizer = get_tokenizer()
    text = "hello world"
    tokens = tokenizer.encode(text)
    assert isinstance(tokens, list)
    decoded = tokenizer.decode(tokens)
    assert decoded.strip() == "hello world"


def test_chunk_text_reconstructs_content() -> None:
    tokenizer = get_tokenizer()
    text = "word " * 50
    chunks = chunk_text(text, tokenizer, 10)
    assert "".join(chunks) == text.strip()
    assert len(chunks) > 1


def test_chunk_text_splits_markdown_headings() -> None:
    tokenizer = get_tokenizer()
    text = "# H1\npara1\n\n# H2\npara2"
    # The lightweight tokenizer overestimates token counts by splitting into
    # very small pieces, so use a slightly larger chunk size here to ensure the
    # heading and following paragraph stay together.
    chunks = chunk_text(text, tokenizer, 8)
    assert len(chunks) == 2
    assert chunks[0].startswith("# H1")
    assert chunks[1].startswith("# H2")


def test_chunk_text_preserves_code_blocks() -> None:
    tokenizer = get_tokenizer()
    text = "Intro\n\n```python\nprint('hi')\n```\n\nConclusion"
    chunks = chunk_text(text, tokenizer, 4)
    assert any("```python\nprint('hi')\n```" in chunk for chunk in chunks)
    for chunk in chunks:
        assert chunk.count("```") in (0, 2)
