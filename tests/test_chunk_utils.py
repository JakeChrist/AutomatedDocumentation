from chunk_utils import get_tokenizer, chunk_text


def test_get_tokenizer_roundtrip() -> None:
    tokenizer = get_tokenizer()
    text = "hello world"
    tokens = tokenizer.encode(text)
    assert isinstance(tokens, list)
    decoded = tokenizer.decode(tokens)
    assert decoded.strip() == "hello world"


def test_chunk_text_reconstructs_tokens() -> None:
    tokenizer = get_tokenizer()
    text = "word " * 50
    tokens = tokenizer.encode(text)
    chunks = chunk_text(text, tokenizer, 10)
    rebuilt = []
    for chunk in chunks:
        rebuilt.extend(tokenizer.encode(chunk))
    assert rebuilt == tokens
    assert len(chunks) == 5
