import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import requests
from llm_client import LLMClient


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
            {"message": {"content": " summary "}}
        ]
    }
    with patch("llm_client.requests.post") as post, patch("llm_client.time.sleep") as sleep:
        post.side_effect = [requests.exceptions.RequestException("boom"), mock_response]
        result = client.summarize("text", "prompt")
        assert result == "summary"
        assert post.call_count == 2
        sleep.assert_called_once_with(1)


def test_summarize_raises_runtime_error_with_message() -> None:
    client = LLMClient("http://fake")
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
    mock_response.json.side_effect = ValueError()
    mock_response.text = "server exploded"
    with patch("llm_client.requests.post", return_value=mock_response), patch("llm_client.time.sleep"):
        with pytest.raises(RuntimeError, match="server exploded"):
            client.summarize("text", "prompt")

