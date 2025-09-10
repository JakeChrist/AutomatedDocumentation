from __future__ import annotations

import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Set

from cache import ResponseCache
from chunk_utils import chunk_text, get_tokenizer
from llm_client import LLMClient, sanitize_summary


TOKENIZER = get_tokenizer()

CHUNK_SYSTEM_PROMPT = (
    "You are generating part of a user manual. Based on the context provided, "
    "write a section of the guide covering purpose, usage, inputs, outputs, and behavior. "
    "Do not describe individual functions or implementation details. Focus on user-level instructions."
)

MERGE_SYSTEM_PROMPT = (
    "You are compiling a user manual. Combine the provided sections into a cohesive guide. "
    "Ensure the manual includes sections for Overview, Purpose & Problem Solving, How to Run, "
    "Inputs, Outputs, System Requirements, and Examples. If information for any section is "
    "missing, insert the corresponding placeholder token such as [[NEEDS_RUN_INSTRUCTIONS]]. "
    "Do not describe individual functions or implementation details; concentrate on user-level instructions."
)


def _count_tokens(text: str) -> int:
    """Return the approximate token count for ``text``."""
    return len(TOKENIZER.encode(text))


def _split_text(text: str, max_tokens: int = 2000, max_chars: int = 6000) -> list[str]:
    """Split ``text`` into chunks respecting ``max_tokens`` and ``max_chars``."""
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    token_count = 0
    char_count = 0
    sep_tokens = max(_count_tokens("\n\n"), 1)
    sep_chars = 2
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        ptokens = _count_tokens(para)
        pchars = len(para)
        if ptokens > max_tokens or pchars > max_chars:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                token_count = 0
                char_count = 0
            for piece in chunk_text(para, TOKENIZER, max_tokens):
                chunks.append(piece.strip())
            continue
        extra_tokens = ptokens if not current else ptokens + sep_tokens
        extra_chars = pchars if not current else pchars + sep_chars
        if token_count + extra_tokens > max_tokens or char_count + extra_chars > max_chars:
            if current:
                chunks.append("\n\n".join(current).strip())
            current = [para]
            token_count = ptokens
            char_count = pchars
        else:
            current.append(para)
            token_count += extra_tokens
            char_count += extra_chars
    if current:
        chunks.append("\n\n".join(current).strip())
    return chunks


def chunk_docs(docs: list[str], token_limit: int = 2000) -> list[str]:
    """Split ``docs`` into roughly ``token_limit`` sized chunks."""
    text = "\n\n".join(d.strip() for d in docs if d and d.strip())
    if not text:
        return []
    return _split_text(text, max_tokens=token_limit, max_chars=token_limit * 3)


PLACEHOLDER_RE = re.compile(r"\[\[[^\[\]]+\]\]")


def find_placeholders(text: str) -> Set[str]:
    """Return placeholder tokens of the form ``[[TOKEN]]`` found in ``text``."""
    return set(PLACEHOLDER_RE.findall(text))


def _summarize_manual(
    client: LLMClient,
    cache: ResponseCache,
    text: str,
    chunking: str = "auto",
    source: str = "combined",
    post_chunk_hook: Callable[[list[str]], list[str]] | None = None,
) -> str:
    """Return a manual summary for ``text`` using ``chunking`` strategy."""
    if not text:
        return ""

    from explaincode import infer_sections  # imported lazily to avoid circular dependency

    within_limits = _count_tokens(text) <= 2000 and len(text) <= 6000

    if chunking == "manual" or (chunking == "auto" and not within_limits):
        try:
            parts = _split_text(text)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] Chunking failed: {exc}", file=sys.stderr)
            sections = infer_sections(text)
            return "\n".join(f"{k}: {v}" for k, v in sections.items())

        total = len(parts)
        partials: dict[int, str] = {}
        work: list[tuple[int, str, str]] = []
        for idx, part in enumerate(parts, 1):
            logging.debug(
                "Chunk %s/%s from %s: %s tokens, %s characters",
                idx,
                total,
                source,
                _count_tokens(part),
                len(part),
            )
            key = ResponseCache.make_key(f"{source}:chunk{idx}", part)
            cached = cache.get(key)
            if cached is not None:
                # Cached responses may predate sanitization; clean them to
                # avoid reserved-token issues downstream.
                cached = sanitize_summary(cached)
                partials[idx] = cached
                logging.debug(
                    "LLM response %s/%s length: %s characters",
                    idx,
                    total,
                    len(cached),
                )
            else:
                work.append((idx, part, key))

        if work:
            with ThreadPoolExecutor() as executor:
                future_map = {
                    executor.submit(
                        client.summarize,
                        part,
                        "docstring",
                        system_prompt=CHUNK_SYSTEM_PROMPT,
                    ): (idx, key)
                    for idx, part, key in work
                }
                for future in as_completed(future_map):
                    idx, key = future_map[future]
                    try:
                        resp = future.result()
                    except Exception as exc:  # pragma: no cover - network failure
                        print(
                            f"[WARN] Summarization failed for chunk {idx}/{total}: {exc}",
                            file=sys.stderr,
                        )
                        continue
                    cache.set(key, resp)
                    logging.debug(
                        "LLM response %s/%s length: %s characters",
                        idx,
                        total,
                        len(resp),
                    )
                    partials[idx] = resp

        if not partials:
            sections = infer_sections(text)
            return "\n".join(f"{k}: {v}" for k, v in sections.items())

        if post_chunk_hook:
            try:
                ordered = [partials[i] for i in sorted(partials)]
                ordered = post_chunk_hook(ordered)
                partials = {i + 1: v for i, v in enumerate(ordered)}
            except Exception as exc:  # pragma: no cover - defensive
                logging.debug("Chunk post-processing failed: %s", exc)

        merge_input = "\n\n".join(partials[i] for i in sorted(partials))
        tokens = _count_tokens(merge_input)
        chars = len(merge_input)
        iteration = 0
        while tokens > 2000 or chars > 6000:
            iteration += 1
            logging.info(
                "Hierarchical merge pass %s: %s tokens, %s characters",
                iteration,
                tokens,
                chars,
            )
            try:
                sub_parts = _split_text(merge_input)
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[WARN] Hierarchical split failed: {exc}", file=sys.stderr)
                break
            new_partials: list[str] = []
            total = len(sub_parts)
            for idx, piece in enumerate(sub_parts, 1):
                logging.debug(
                    "Merge chunk %s/%s: %s tokens, %s characters",
                    idx,
                    total,
                    _count_tokens(piece),
                    len(piece),
                )
                key = ResponseCache.make_key(
                    f"{source}:merge{iteration}:chunk{idx}", piece
                )
                cached = cache.get(key)
                if cached is not None:
                    resp = sanitize_summary(cached)
                else:
                    try:
                        resp = client.summarize(
                            piece, "docstring", system_prompt=MERGE_SYSTEM_PROMPT
                        )
                    except Exception as exc:  # pragma: no cover - network failure
                        print(
                            f"[WARN] Hierarchical summarization failed for chunk {idx}/{total}: {exc}",
                            file=sys.stderr,
                        )
                        continue
                    cache.set(key, resp)
                new_partials.append(resp)
            if not new_partials:
                break
            merge_input = "\n\n".join(new_partials)
            tokens = _count_tokens(merge_input)
            chars = len(merge_input)
        key = ResponseCache.make_key(f"{source}:final", merge_input)
        cached = cache.get(key)
        if cached is not None:
            final_resp = sanitize_summary(cached)
        else:
            try:
                final_resp = client.summarize(
                    merge_input, "docstring", system_prompt=MERGE_SYSTEM_PROMPT
                )
                cache.set(key, final_resp)
            except Exception as exc:  # pragma: no cover - network failure
                print(f"[WARN] Merge failed: {exc}", file=sys.stderr)
                return merge_input
        logging.debug("Merged LLM response length: %s characters", len(final_resp))
        return sanitize_summary(final_resp)

    if chunking == "none" and not within_limits:
        print(
            "[WARN] Content exceeds token or character limits; chunking disabled.",
            file=sys.stderr,
        )
    key = ResponseCache.make_key(f"{source}:full", text)
    cached = cache.get(key)
    if cached is not None:
        return sanitize_summary(cached)
    resp = client.summarize(text, "user_manual", system_prompt=MERGE_SYSTEM_PROMPT)
    cache.set(key, resp)
    return sanitize_summary(resp)
