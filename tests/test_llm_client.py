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
