import importlib
import json
import sys
from urllib import error as url_error
from urllib import request as url_request


class Response:
    def __init__(self, status_code: int, data: bytes) -> None:
        self.status_code = status_code
        self._data = data

    @property
    def text(self) -> str:
        return self._data.decode("utf-8")

    def json(self) -> object:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if 400 <= self.status_code:
            raise RequestException(f"HTTP {self.status_code}")

try:
    _real_requests = importlib.import_module("requests")
    if _real_requests is sys.modules[__name__]:
        raise ImportError
    from requests.exceptions import RequestException
except Exception:  # pragma: no cover - fallback when real requests isn't available
    _real_requests = None
    from .exceptions import RequestException


def _fallback_get(url: str, timeout: float | None = None):
    try:
        with url_request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
            code = resp.getcode()
        return Response(code, data)
    except url_error.URLError as exc:  # pragma: no cover - network failures
        raise RequestException(str(exc)) from exc


def get(url: str, timeout: float | None = None):
    if _real_requests is not None:
        return _real_requests.get(url, timeout=timeout)
    return _fallback_get(url, timeout)


def _fallback_post(url: str, payload: dict | None = None, timeout: float | None = None):
    data = payload if payload is not None else {}
    body = json.dumps(data).encode("utf-8")
    req = url_request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with url_request.urlopen(req, timeout=timeout) as resp:
            resp_data = resp.read()
            code = resp.getcode()
        return Response(code, resp_data)
    except url_error.URLError as exc:  # pragma: no cover - network failures
        raise RequestException(str(exc)) from exc


def post(url: str, json: dict | None = None, timeout: float | None = None):
    if _real_requests is not None:
        return _real_requests.post(url, json=json, timeout=timeout)
    return _fallback_post(url, json, timeout)


class exceptions:
    RequestException = RequestException
