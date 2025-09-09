import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import requests
from llm_client import LLMClient, sanitize_summary, PROMPT_TEMPLATES


def test_ping_success() -> None:
    client = LLMClient("http://fake")
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    with patch("requests.get", return_value=mock_response) as get:
        assert client.ping() is True
        get.assert_called_once_with("http://fake", timeout=2.0)
        mock_response.raise_for_status.assert_called_once()


def test_ping_failure() -> None:
    client = LLMClient("http://fake")
    with patch("requests.get", side_effect=requests.exceptions.RequestException("fail")):
        with pytest.raises(ConnectionError):
            client.ping()

def test_summarize_retries_and_returns_summary() -> None:
    client = LLMClient("http://fake")
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "choices": [
            {"message": {"content": "You can run this.\nDefines a class."}}
        ]
    }
    with patch("llm_client.requests.post") as post, patch("llm_client.time.sleep") as sleep:
        post.side_effect = [requests.exceptions.RequestException("boom"), mock_response]
        result = client.summarize("text", "module")
        assert result == "Defines a class."
        assert post.call_count == 2
        sleep.assert_called_once_with(1)
        sent_prompt = post.call_args_list[1][1]["json"]["messages"][1]["content"]
        assert sent_prompt == PROMPT_TEMPLATES["module"].format(text="text")


def test_summarize_raises_runtime_error_with_message() -> None:
    client = LLMClient("http://fake")
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
    mock_response.json.side_effect = ValueError()
    mock_response.text = "server exploded"
    with patch("llm_client.requests.post", return_value=mock_response), patch("llm_client.time.sleep"):
        with pytest.raises(RuntimeError, match="server exploded"):
            client.summarize("text", "module")


def test_sanitize_summary_filters_phrases() -> None:
    text = (
        "You can run this.\n"
        "Note that it is simple.\n"
        "Summarize the following function.\n"
        "You are a documentation engine.\n"
        "Defines a class.\n"
        "This summary does not include disclaimers.\n"
        "This script does nothing.\n"
        "It prints output."
    )
    assert sanitize_summary(text) == "Defines a class.\nIt prints output."


def test_sanitize_summary_removes_fim_tokens() -> None:
    """FIM reserved tokens should be stripped to avoid tokenizer errors."""
    text = "Defines <|fim_middle|>a class."
    assert sanitize_summary(text) == "Defines a class."


def test_sanitize_summary_filters_ai_language_model() -> None:
    text = "As an AI language model, I cannot help.\nIt prints output."
    assert sanitize_summary(text) == "It prints output."


def test_sanitize_summary_removes_prompt_lines() -> None:
    text = (
        "Summarize the module below.\n"
        "- Do not refer to yourself, the summary, or the response.\n"
        "Defines a class.\n"
        "- Do not include instructions, usage advice, or disclaimers."
    )
    assert sanitize_summary(text) == "Defines a class."


def test_prompt_varies_by_type() -> None:
    client = LLMClient("http://fake")
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "x"}}]}

    with patch("llm_client.requests.post", return_value=mock_response) as post:
        client.summarize("foo", "class")
        class_prompt = post.call_args[1]["json"]["messages"][1]["content"]

    with patch("llm_client.requests.post", return_value=mock_response) as post:
        client.summarize("foo", "function")
        func_prompt = post.call_args[1]["json"]["messages"][1]["content"]

    assert class_prompt == PROMPT_TEMPLATES["class"].format(text="foo")
    assert func_prompt == PROMPT_TEMPLATES["function"].format(text="foo")
    assert class_prompt != func_prompt


def test_readme_prompt_template_used() -> None:
    client = LLMClient("http://fake")
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "x"}}]}

    with patch("llm_client.requests.post", return_value=mock_response) as post:
        client.summarize("foo", "readme")
        readme_prompt = post.call_args[1]["json"]["messages"][1]["content"]

    assert readme_prompt == PROMPT_TEMPLATES["readme"].format(text="foo")

