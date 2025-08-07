from __future__ import annotations

"""Utility functions for tokenization and text chunking."""

import sys

try:  # optional dependency used for token counting
    import tiktoken
except Exception:  # pragma: no cover - optional import
    tiktoken = None


def get_tokenizer():
    """Return a tokenizer object used for estimating token counts."""

    if tiktoken is not None:  # pragma: no cover - optional branch
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:  # pragma: no cover - fallback if model unknown or offline
            try:
                return tiktoken.encoding_for_model("gpt-3.5-turbo")
            except Exception:
                pass

    print(
        "[WARNING] tiktoken is not installed or could not be loaded; token counts will be approximate.",
        file=sys.stderr,
    )

    class _Simple:
        def encode(self, text: str):
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    return _Simple()


def chunk_text(text: str, tokenizer, chunk_size_tokens: int):
    """Split ``text`` into chunks roughly ``chunk_size_tokens`` each."""

    tokens = tokenizer.encode(text)
    chunks = []
    for i in range(0, len(tokens), chunk_size_tokens):
        chunk = tokens[i : i + chunk_size_tokens]
        chunks.append(tokenizer.decode(chunk))
    return chunks
