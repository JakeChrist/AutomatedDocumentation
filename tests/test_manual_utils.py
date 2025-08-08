import manual_utils


def _count(text: str) -> int:
    return len(manual_utils.TOKENIZER.encode(text))


def test_chunk_docs_respects_token_limit() -> None:
    docs = ["a " * 1000, "b " * 1000, "c " * 1000]
    chunks = manual_utils.chunk_docs(docs, token_limit=2000)
    assert len(chunks) == 2
    assert all(_count(c) <= 2000 for c in chunks)


def test_find_placeholders() -> None:
    text = "Intro [[NEEDS_OVERVIEW]] middle [[FOO]] end"
    tokens = manual_utils.find_placeholders(text)
    assert tokens == {"[[NEEDS_OVERVIEW]]", "[[FOO]]"}
