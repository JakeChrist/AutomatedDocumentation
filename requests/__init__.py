from .exceptions import RequestException


def get(*args, **kwargs):
    raise NotImplementedError("requests stub: get")


def post(*args, **kwargs):
    raise NotImplementedError("requests stub: post")


class exceptions:
    RequestException = RequestException
