from __future__ import annotations

"""Utility functions for tokenization and text chunking.

The :func:`chunk_text` helper attempts to split text on natural boundaries such
as blank lines, Markdown headings, or fenced code blocks.  Only when a single
section exceeds the desired size does it fall back to a simple character based
split.  This keeps paragraphs and code fences intact which is important when
sending chunks to a language model for processing.
"""

import re
import sys
from typing import List, Optional, Protocol

try:  # optional dependency used for token counting
    import tiktoken
except Exception:  # pragma: no cover - optional import
    tiktoken = None

FIM_RE = re.compile(r"<\|fim_(?:prefix|middle|suffix)\|>")


def strip_fim_tokens(text: str) -> str:
    """Return ``text`` with any FIM special tokens removed."""

    return FIM_RE.sub("", text)


class _TokenizerProtocol(Protocol):
    """Minimal protocol representing the tokenizer interface we rely on."""

    def encode(self, text: str, **kwargs):  # pragma: no cover - structural
        ...

    def decode(self, tokens, **kwargs):  # pragma: no cover - structural
        ...


def get_tokenizer() -> _TokenizerProtocol:
    """Return a tokenizer object used for estimating token counts."""

    if tiktoken is not None:  # pragma: no cover - optional branch
        enc = None
        # ``tiktoken`` may attempt network access when loading encodings which
        # can trigger unraisable ``ProxyError`` warnings under pytest.  Temporarily
        # override the unraisable hook to swallow such errors.
        old_hook = getattr(sys, "unraisablehook", None)
        try:
            if old_hook is not None:
                sys.unraisablehook = lambda *a, **k: None
            try:
                enc = tiktoken.get_encoding("cl100k_base")
            except Exception:  # pragma: no cover - fallback if model unknown or offline
                try:
                    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
                except Exception:
                    enc = None
        finally:
            if old_hook is not None:
                sys.unraisablehook = old_hook

        if enc is not None:
            class _EncodingWrapper:
                def __init__(self, enc):
                    self._enc = enc

                def encode(self, text: str, **kwargs):
                    text = strip_fim_tokens(text)
                    kwargs.setdefault("disallowed_special", ())
                    return self._enc.encode(text, **kwargs)

                def decode(self, tokens, **kwargs):
                    return self._enc.decode(tokens, **kwargs)

            return _EncodingWrapper(enc)

    print(
        "[WARNING] tiktoken is not installed or could not be loaded; token counts will be approximate.",
        file=sys.stderr,
    )

    class _Simple:
        def encode(self, text: str):
            text = strip_fim_tokens(text)
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    return _Simple()


def _split_blocks(text: str) -> List[str]:
    """Return Markdown ``text`` separated into paragraphs, headings and fences."""

    blocks: List[str] = []
    lines = text.splitlines()
    current: List[str] = []
    in_code = False

    for line in lines:
        if line.startswith("```"):
            if in_code:  # closing fence
                current.append(line)
                blocks.append("\n".join(current).strip())
                current = []
                in_code = False
            else:  # opening fence
                if current:
                    blocks.append("\n".join(current).strip())
                    current = []
                current.append(line)
                in_code = True
            continue

        if in_code:
            current.append(line)
            continue

        if line.strip() == "":
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue

        if line.lstrip().startswith("#"):
            if current:
                blocks.append("\n".join(current).strip())
            blocks.append(line.strip())
            current = []
            continue

        current.append(line)

    if current:
        blocks.append("\n".join(current).strip())

    return [b for b in blocks if b]


def _split_long_block(block: str, tokenizer, chunk_size_tokens: int) -> List[str]:
    """Fallback splitter that uses a character based approximation."""

    tokens = tokenizer.encode(block)
    if len(tokens) <= chunk_size_tokens:
        return [block]

    avg_chars = max(len(block) // len(tokens), 1)
    max_chars = max(chunk_size_tokens * avg_chars, 1)
    return [block[i : i + max_chars] for i in range(0, len(block), max_chars)]


def chunk_text(
    text: Optional[str],
    tokenizer: Optional[_TokenizerProtocol],
    chunk_size_tokens: int,
) -> List[str]:
    """Split ``text`` into chunks roughly ``chunk_size_tokens`` each.

    Natural break points such as blank lines, Markdown headings and fenced code
    blocks are honoured.  If a single block still exceeds ``chunk_size_tokens``
    the function falls back to splitting that block by approximate character
    length.  ``text`` and ``tokenizer`` are optional for convenience; passing
    ``None`` for either will default to an empty string and the shared
    :func:`get_tokenizer` respectively.
    """

    if text is None:
        text = ""

    if tokenizer is None:
        tokenizer = get_tokenizer()

    blocks = _split_blocks(text)
    chunks: List[str] = []
    current: List[str] = []
    token_count = 0

    for block in blocks:
        block_tokens = len(tokenizer.encode(block))
        if token_count + block_tokens > chunk_size_tokens and current:
            chunks.append("\n\n".join(current))
            current = []
            token_count = 0

        if block_tokens > chunk_size_tokens:
            chunks.extend(_split_long_block(block, tokenizer, chunk_size_tokens))
            continue

        current.append(block)
        token_count += block_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks
