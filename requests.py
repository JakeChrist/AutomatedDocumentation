import sys
from pip._vendor import requests as _requests

sys.modules[__name__] = _requests
