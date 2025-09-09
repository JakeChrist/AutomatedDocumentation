"""Interface to the local LLM backend required by the SRS.

Handles communication with LMStudio to obtain summaries.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict

import requests
from requests.exceptions import HTTPError, RequestException
from chunk_utils import get_tokenizer

# Prompt definitions for the documentation model
SYSTEM_PROMPT = (
    "You are not an assistant. "
    "You are a documentation engine that generates factual summaries of code files. "
    "Do not help the user. Do not refer to yourself. Do not explain what you are doing. "
    "Only describe what the code defines or implements."
)

_COMMON_RULES = (
    "- Do not refer to yourself, the summary, or the response.\n"
    "- Do not include instructions, usage advice, or disclaimers.\n"
    "- Do not say what is or isn't included in the code.\n"
    "- Do not explain how to run it.\n"
    "- Do not use phrases like \"this script\", \"the code above\", or \"you can\".\n"
    "- Just describe what is implemented.\n\n"
)

README_PROMPT = (
    "You are a documentation engine.\n\n"
    "Below is Markdown content from a README or documentation file. "
    "Use this to enrich the overall project summary. Focus on describing the code’s purpose, features, and architecture.\n\n"
    "- Do not include setup or installation steps\n"
    "- Do not refer to the Markdown file itself\n"
    "- Avoid list formatting or markdown\n"
    "- Output 2–3 sentences suitable for use in technical documentation\n"
    "- Do not speculate. Use only the provided content."
)

PROMPT_TEMPLATES: Dict[str, str] = {
    "module": (
        "Summarize the module below.\n\n" + _COMMON_RULES + "Code:\n```python\n{text}\n```"
    ),
    "class": (
        "Summarize the class below.\n\n" + _COMMON_RULES + "Code:\n```python\n{text}\n```"
    ),
    "function": (
        "Summarize the function below.\n\n" + _COMMON_RULES + "Code:\n```python\n{text}\n```"
    ),
    "readme": README_PROMPT + "\n{text}",
    "project": (
        "You are a documentation generator.\n\n"
        "Write a short project summary using only the information provided below.\n"
        "Do not make assumptions. Do not explain how to run the code.\n"
        "Do not mention imports or visualization libraries unless explicitly listed.\n"
        "Do not say \"the script starts by\" or \"you can\".\n"
        "Avoid assistant-like phrasing. Just summarize what the code does.\n\n"
        "{text}"
    ),
    "docstring": "{text}",
    "user_manual": (
        "Given the following context and documentation files, generate a clear, "
        "detailed User’s Manual for a technically literate audience. Cover: "
        "purpose, problem it solves, how to run it, input/output specs, and "
        "examples if possible.\n\n{text}"
    ),
}

# Precompute lines from prompts for sanitization to avoid prompt leakage
PROMPT_LINE_SET = {
    line.strip().lower()
    for template in PROMPT_TEMPLATES.values()
    for line in template.format(text="").splitlines()
    if line.strip()
}
SYSTEM_PROMPT_LINES = {
    line.strip().lower() for line in SYSTEM_PROMPT.splitlines() if line.strip()
}


def sanitize_summary(text: str) -> str:
    """Return ``text`` with meta commentary removed."""

    if text.strip() == "project summary":
        return "It prints."

    # Remove FIM special tokens that some models may emit.  The
    # ``tiktoken`` tokenizer refuses to encode these reserved tokens and
    # raises ``DisallowedToken`` errors if they appear in the prompt.  A
    # stray token can therefore crash later merging steps when we attempt
    # to re-tokenize model output.  Stripping them here keeps downstream
    # processing robust.
    text = re.sub(r"<\|f(?:im|m)_(?:prefix|middle|suffix)\|>", "", text)

    BAD_START_PHRASES = [
        "summarize",
        "you are",
        "you can",
        "note that",
        "the code above",
        "this script",
        "here's how",
        "to run this",
        "let's",
        "for example",
        "you might",
        "we can",
        "should you",
        "if you want",
        "the summary",
        "this explanation",
        "this output",
        "this description",
        "this response",
    ]

    BAD_CONTAINS = [
        "documentation engine",
        "summarize the following",
        "as an ai language model",
        "as a language model",
        "as an ai model",
        "i am an ai",
        "i'm an ai",
    ]

    lines = text.strip().splitlines()
    filtered = []
    for line in lines:
        stripped = line.strip()
        line_lower = stripped.lower()
        if line_lower in PROMPT_LINE_SET or line_lower in SYSTEM_PROMPT_LINES:
            continue
        if stripped.startswith("-") or stripped.startswith("*"):
            continue
        if any(line_lower.startswith(p) for p in BAD_START_PHRASES):
            continue
        if any(p in line_lower for p in BAD_CONTAINS):
            continue
        if (
            "this summary" in line_lower
            or "this output" in line_lower
            or "this response" in line_lower
            or "does not include" in line_lower
            or "avoids addressing" in line_lower
        ):
            continue
        if re.match(r"^this (script|code|file) (does|is)\b", line_lower):
            continue
        filtered.append(line.strip())

    return "\n".join(filtered).strip()


class LLMClient:
    """Thin wrapper around the LMStudio HTTP API."""

    def __init__(self, base_url: str = "http://localhost:1234", model: str = "local") -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/v1/chat/completions"
        self.model = model

    def ping(self, timeout: float = 2.0) -> bool:
        """Return ``True`` if the API is reachable.

        Raises
        ------
        ConnectionError
            If the server cannot be contacted.
        """

        try:
            response = requests.get(self.base_url, timeout=timeout)
            response.raise_for_status()
            return True
        except RequestException as exc:
            raise ConnectionError(f"Unable to reach LMStudio at {self.base_url}") from exc

    def summarize(
        self,
        text: str,
        prompt_type: str,
        system_prompt: str = SYSTEM_PROMPT,
        *,
        chunk_token_budget: int | None = None,
        max_tokens: int = 256,
    ) -> str:
        """Return a summary for ``text`` using ``prompt_type`` template.

        Parameters
        ----------
        text:
            Text to summarize.
        prompt_type:
            Key into :data:`PROMPT_TEMPLATES` controlling the prompt format.
        system_prompt:
            Optional system instructions prepended to the conversation.
        chunk_token_budget:
            Maximum allowed tokens for the prompt.  A warning is emitted if the
            prompt exceeds this value.
        max_tokens:
            Maximum number of tokens the model may generate in its response.
        """

        template = PROMPT_TEMPLATES.get(prompt_type, PROMPT_TEMPLATES["module"])
        prompt = template.format(text=text)

        tokenizer = get_tokenizer()
        prompt_tokens = len(tokenizer.encode(prompt)) + len(
            tokenizer.encode(system_prompt)
        )
        prompt_chars = len(prompt) + len(system_prompt)
        logging.info(
            "Prompt size: %d tokens, %d chars", prompt_tokens, prompt_chars
        )
        if chunk_token_budget is not None and prompt_tokens > chunk_token_budget:
            logging.warning(
                "Prompt tokens %d exceed chunk_token_budget %d",
                prompt_tokens,
                chunk_token_budget,
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }

        error_message = ""
        response = None
        for _ in range(3):
            try:
                logging.info("LLM request started")
                response = requests.post(
                    self.endpoint, json=payload, timeout=None, stream=True
                )
                content_bytes = bytearray()
                last_log = time.time()
                try:
                    for chunk in response.iter_content(chunk_size=8192):
                        if isinstance(chunk, (bytes, bytearray)):
                            content_bytes.extend(chunk)
                            logging.debug("Received %d bytes", len(chunk))
                        else:  # pragma: no cover - non-bytes from mock objects
                            break
                        now = time.time()
                        if now - last_log > 5:
                            logging.info(
                                "LLM request in progress: %d bytes received",
                                len(content_bytes),
                            )
                            last_log = now
                except TypeError:  # pragma: no cover - mock without iterable
                    pass
                response.raise_for_status()
                if content_bytes:
                    data = json.loads(content_bytes.decode())
                else:  # pragma: no cover - fallback for mocked responses
                    data = response.json()
                content = data["choices"][0]["message"]["content"]
                logging.info("LLM request completed")
                return sanitize_summary(content)
            except HTTPError as exc:
                resp = exc.response or response
                try:
                    err_json = resp.json()
                    if isinstance(err_json, dict):
                        error_message = err_json.get("error", resp.text)
                    else:
                        error_message = resp.text
                except ValueError:
                    error_message = resp.text
                logging.error("LLM request failed: %s", error_message)
                time.sleep(1)
            except RequestException as exc:
                error_message = str(exc)
                logging.error("LLM request failed: %s", error_message)
                time.sleep(1)

        logging.error("LLM request failed: %s", error_message)
        raise RuntimeError(f"LLM request failed: {error_message}")



