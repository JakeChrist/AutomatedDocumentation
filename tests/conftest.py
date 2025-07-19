import types
from unittest.mock import Mock
import sys

# Provide a minimal 'requests' stub so modules import without the real library
requests_stub = types.ModuleType('requests')
requests_stub.get = Mock()
requests_stub.post = Mock()

class _RequestException(Exception):
    pass

class _HTTPError(Exception):
    def __init__(self, *args, response=None, **kwargs):
        super().__init__(*args)
        self.response = response

exceptions_module = types.ModuleType('requests.exceptions')
exceptions_module.RequestException = _RequestException
exceptions_module.HTTPError = _HTTPError
requests_stub.exceptions = exceptions_module

sys.modules.setdefault('requests', requests_stub)
sys.modules.setdefault('requests.exceptions', exceptions_module)
