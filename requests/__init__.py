import importlib
import sys

try:
    _real_requests = importlib.import_module("requests")
    if _real_requests is sys.modules[__name__]:
        raise ImportError
    from requests.exceptions import RequestException
except Exception:  # pragma: no cover - fallback when real requests isn't available
    _real_requests = None
    from .exceptions import RequestException


def get(*args, **kwargs):
    if _real_requests is None:
        raise NotImplementedError("requests stub: get")
    return _real_requests.get(*args, **kwargs)


def post(*args, **kwargs):
    if _real_requests is None:
        raise NotImplementedError("requests stub: post")
    return _real_requests.post(*args, **kwargs)


class exceptions:
    RequestException = RequestException
