from __future__ import annotations

import sys
from typing import List

from cache import ResponseCache
from chunk_utils import chunk_text, get_tokenizer
from llm_client import LLMClient, PROMPT_TEMPLATES, SYSTEM_PROMPT, sanitize_summary


def _summarize(
    client: LLMClient,
    cache: ResponseCache,
    key: str,
    text: str,
    prompt_type: str,
    *,
    system_prompt: str,
) -> str:
    cached = cache.get(key)
    if cached is not None:
        return cached
    summary = client.summarize(text, prompt_type, system_prompt=system_prompt)
    cache.set(key, summary)
    return summary


def summarize_chunked(
    client: LLMClient,
    cache: ResponseCache,
    key_prefix: str,
    text: str,
    prompt_type: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    max_context_tokens: int = 4096,
    chunk_token_budget: int = 3072,
) -> str:
    """Summarize ``text`` by chunking if necessary."""

    tokenizer = get_tokenizer()
    template = PROMPT_TEMPLATES.get(prompt_type, PROMPT_TEMPLATES["module"])
    overhead_tokens = len(tokenizer.encode(system_prompt)) + len(
        tokenizer.encode(template.format(text=""))
    )
    available_tokens = max(1, max_context_tokens - overhead_tokens)

    if len(tokenizer.encode(text)) <= available_tokens:
        key = ResponseCache.make_key(key_prefix, text)
        return _summarize(
            client, cache, key, text, prompt_type, system_prompt=system_prompt
        )

    chunk_size_tokens = min(chunk_token_budget, available_tokens)
    try:
        parts = chunk_text(text, tokenizer, chunk_size_tokens)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[WARN] Chunking failed: {exc}", file=sys.stderr)
        key = ResponseCache.make_key(key_prefix, text)
        try:
            return _summarize(
                client, cache, key, text, prompt_type, system_prompt=system_prompt
            )
        except Exception:
            return sanitize_summary("")

    partials: List[str] = []
    for idx, part in enumerate(parts):
        key = ResponseCache.make_key(f"{key_prefix}:part{idx}", part)
        try:
            partials.append(
                _summarize(
                    client,
                    cache,
                    key,
                    part,
                    prompt_type,
                    system_prompt=system_prompt,
                )
            )
        except Exception as exc:  # pragma: no cover - network failure
            print(
                f"[WARN] Summarization failed for chunk {idx}: {exc}",
                file=sys.stderr,
            )
    if not partials:
        return sanitize_summary("")

    instructions = (
        "You are a documentation generator.\n\n"
        "Combine the following summaries into a single technical paragraph.\n"
        "Do not critique, evaluate, or offer suggestions.\n"
        "Do not speculate or use uncertain language.\n"
        "Only summarize what the text explicitly states.\n\n"
    )
    instr_tokens = len(tokenizer.encode(instructions))
    merge_budget = max(1, available_tokens - instr_tokens)

    def _merge_recursive(items: List[str], depth: int = 0) -> str:
        merge_text = "\n".join(f"- {p}" for p in items)
        prompt = instructions + merge_text
        if len(tokenizer.encode(prompt)) <= available_tokens:
            key = ResponseCache.make_key(f"{key_prefix}:merge{depth}", prompt)
            return _summarize(
                client,
                cache,
                key,
                prompt,
                "docstring",
                system_prompt=system_prompt,
            )
        if len(items) == 1:
            single = items[0]
            key = ResponseCache.make_key(f"{key_prefix}:merge{depth}:solo", single)
            return summarize_chunked(
                client,
                cache,
                key,
                single,
                "docstring",
                system_prompt=system_prompt,
                max_context_tokens=max_context_tokens,
                chunk_token_budget=chunk_token_budget,
            )
        groups: List[List[str]] = []
        current: List[str] = []
        current_tokens = 0
        for p in items:
            bullet = f"- {p}\n"
            b_tokens = len(tokenizer.encode(bullet))
            if current and current_tokens + b_tokens > merge_budget:
                groups.append(current)
                current = [p]
                current_tokens = b_tokens
            else:
                current.append(p)
                current_tokens += b_tokens
        if current:
            groups.append(current)

        merged: List[str] = []
        for idx, grp in enumerate(groups):
            merged.append(_merge_recursive(grp, depth + 1))
        return _merge_recursive(merged, depth + 1)

    try:
        final_summary = _merge_recursive(partials)
    except Exception as exc:  # pragma: no cover - network failure
        print(f"[WARN] Merge failed: {exc}", file=sys.stderr)
        return sanitize_summary("\n".join(partials))
    return sanitize_summary(final_summary)

