"""Tool to be used for http-related tests"""

from unittest.mock import patch


def mock_http(saved_requests, fake_response_maker=None):
    """Intercepts http calls and saves them for future analyses.

    Context manager.
    Arguments:
    - saved_requests: list to append saved request. When
        urllib.request.Request is prepared it will be appended to this
        list instead of actually being sent out.
    - fake_response_maker: optional method which accepts urllib.request.Request
        object and returns desired code and data for response.
        Types of returned values should be:
        - code: int (it's a usual http response code)
        - data: either bytes (will be returned as is), or string (will be
        converted to bytes), or python structure, which will be dumped to
        json.
    """
    def mocked_opener(self, request):
        """mock for urllib.request.OpenerDirector.open."""
        saved_requests.append(request)

        method = request.method
        if callable(fake_response_maker):
            code, data = fake_response_maker(request)
        else:
            code = 200
            data = b''

        if hasattr(data, 'encode'):
            data = data.encode()

        return _FakeHttpResponse(method, code, data)

    return patch('urllib.request.OpenerDirector.open', mocked_opener)


class _FakeHttpResponse:
    # mocks behavior of http Response object
    def __init__(self, method, code, data):
        self.data = data
        self._method = method
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        pass

    def read(self):
        return self.data

    def getheaders(self):
        return {}
