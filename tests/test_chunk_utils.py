from chunk_utils import chunk_text, get_tokenizer


def test_get_tokenizer_roundtrip() -> None:
    tokenizer = get_tokenizer()
    text = "hello world"
    tokens = tokenizer.encode(text)
    assert isinstance(tokens, list)
    decoded = tokenizer.decode(tokens)
    assert decoded.strip() == "hello world"


def test_get_tokenizer_strips_fim_tokens() -> None:
    tokenizer = get_tokenizer()
    text = "hello <|fim_prefix|> world <|fim_suffix|>"
    tokens = tokenizer.encode(text)
    decoded = tokenizer.decode(tokens)
    assert "<|fim_prefix|>" not in decoded
    assert "<|fim_suffix|>" not in decoded
    assert " ".join(decoded.split()) == "hello world"


def test_chunk_text_reconstructs_content() -> None:
    tokenizer = get_tokenizer()
    text = "word " * 50
    chunks = chunk_text(text, tokenizer, 10)
    assert "".join(chunks) == text.strip()
    assert len(chunks) > 1


def test_chunk_text_splits_markdown_headings() -> None:
    tokenizer = get_tokenizer()
    text = "# H1\npara1\n\n# H2\npara2"
    chunks = chunk_text(text, tokenizer, 4)
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

