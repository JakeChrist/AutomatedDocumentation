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

