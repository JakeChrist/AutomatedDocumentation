
class HTTPError(Exception):
    """Stub HTTPError for tests."""

    def __init__(self, response=None):
        super().__init__("HTTPError")
        self.response = response

class RequestException(Exception):
    pass

def get(url, timeout=0, **kwargs):
    raise NotImplementedError

def post(url, json=None, timeout=None, **kwargs):
    raise NotImplementedError


import sys
import types

exceptions = types.ModuleType("requests.exceptions")
exceptions.HTTPError = HTTPError
exceptions.RequestException = RequestException
sys.modules[__name__ + ".exceptions"] = exceptions
