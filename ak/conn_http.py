"""Http requests library."""

import threading
import random
import string
import base64
import logging

import urllib
import urllib.request
import urllib.error
from urllib.parse import urlencode
import ssl
import json


logger = logging.getLogger(__name__)


#########################
# http connection
#
# Send http requests to specified address and process responses

class HttpConn:
    """Allowes to make http(s) requests."""

    def __init__(self, address,
                 *, _send_request_ids=True, adapters=None):
        self.address = address
        self.adapters = adapters or []

        self._reqid_generator_guard = threading.Lock()
        self._reqid_connection_part = "".join(
            random.choice(string.hexdigits.lower()) for _ in range(4))
        self._cur_req_id = 0 if _send_request_ids else None

        is_https = address.lower().startswith("https://")
        self.opener = self._make_opener(is_https)

        self.descr = None

    def __str__(self):
        # return f"Connection to {self.address}"
        if self.descr is None:
            self._prepare_self_descr()
        return self.descr

    def __repr__(self):
        return str(self)

    def _prepare_self_descr(self):
        # create description of self. It includes descriptions of adapters
        def _parts():
            # prepare parts of description
            yield f"Connection to '{self.address}'"
            for adapter in self.adapters:
                yield adapter.mk_descr()

        self.descr = " ".join(part for part in _parts() if part is not None)

    def add_adapter(self, adapter):
        """Add adapter to self.

        Adapter is an object that can process request and returned value.
        """
        self.adapters.append(adapter)
        self.descr = None  # to be evaluated when necessary

    @staticmethod
    def _make_opener(is_https, if_http_debug=False):
        # if_http_debug - make library print raw http data
        #                 printed data may contain more accurate data than what
        #                 gets into logs, but it is printed to stdout, so
        #                 it's difficult to use.
        debuglevel = 1 if if_http_debug else 0
        if is_https:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            http_handler = urllib.request.HTTPSHandler(
                context=ctx, debuglevel=debuglevel)
        else:
            http_handler = urllib.request.HTTPHandler(debuglevel=debuglevel)
        return urllib.request.build_opener(http_handler)

    def __call__(self, path, method=None, *,
                 params=None, data=None, headers=None, raw_response=False):
        """Make specified https(s) request.

        Arguments:
        - path: request path
        - method: request method. By default is "GET" or "POST" (if 'data' provided)
        - params: dictionary of request parameters
        - data: data for request. Can be bytes, string or any python object, which
            can be dumped to json.
        - headers: dict, explicit headers for request
        - raw_response: specifies how response is handled.
            False - (default) method expects that response contains a valid
               json (or no data) and returns decoded json (or empty str). Exception
               is thrown if request was not successful.
            True - urllib Response object is returned "as-is".
        """

        # 1. params
        if params:
            path += "?" + urlencode(params)
        if not self.address.endswith('/') and not path.startswith('/'):
            path = '/' + path
        url = self.address + path

        # 2. headers
        req_headers = {} if not headers else headers.copy()
        if self._cur_req_id is not None:
            # means req_id should be autogenerated if not specified
            if 'X-Request-ID' not in req_headers:
                req_headers['X-Request-ID'] = self._generate_request_id()

        # 3. method (autodetect)
        if not method:
            method = 'POST' if data else 'GET'
        else:
            method = method.upper()

        # 4. data
        if data is None:
            req_data = None
        elif isinstance(data, bytes):
            req_data = data
        else:
            if isinstance(data, str):
                str_data = data
            else:
                str_data = json.dumps(data)
                if 'Content-Type' not in req_headers:
                    req_headers['Content-Type'] = 'application/json'
            req_data = str_data.encode(encoding='utf-8')

        request = urllib.request.Request(
            url,
            data=req_data,
            method=method,
            headers=req_headers)

        # custom pre-process request. (f.e. add auth headers)
        for adapter in self.adapters:
            adapter.process_request(request)

        # log request.
        # !request is not final yet, urllib may add some headers during the call!
        self._log_request(request)

        # actual call
        try:
            response = self.opener.open(request)
            is_error = False
        except urllib.error.HTTPError as err:
            if not raw_response:
                raise
            response = err
            is_error = True

        with response:
            response.data = response.read()

        self._log_response(response, url)

        if not raw_response and not is_error:
            ret_val = response.data.decode('utf-8')
            if ret_val:
                ret_val = json.loads(ret_val)
        else:
            ret_val = response

        # process return value
        for adapter in self.adapters[::-1]:
            ret_val = adapter.process_response(ret_val, is_error)

        return ret_val

    def _generate_request_id(self):
        # generate request id
        with self._reqid_generator_guard:
            next_req_id = self._cur_req_id
            self._cur_req_id += 1
        return None if next_req_id is None else "{}{}-0000-0000-0000-{}".format(
            self._reqid_connection_part,
            "{:04}".format(next_req_id%10000),
            "{:012}".format(next_req_id))

    @staticmethod
    def _log_request(request):
        # log the request

        headers_descr = "\n".join(
            f"> {h_name}: {h_value!r}"
            for h_name, h_value in request.header_items())

        data = request.data
        if data is None:
            logger.debug(
                "request %s %s\n%s",
                request.get_method(), request.get_full_url(), headers_descr)
        else:
            logger.debug(
                "request %s %s\n%s\n data: %s",
                request.get_method(), request.get_full_url(), headers_descr, data)

    @staticmethod
    def _log_response(response, req_path):
        # log the response

        headers_descr = "\n".join(
            f"< {h_name}: {h_value}"
            for h_name, h_value in response.getheaders())

        logger.debug(
            "%s %s <- %s\n%s\n%s",
            response._method, req_path, response.code, headers_descr, response.data)


class _HttpConnAdapter:
    # base class for adapters, which can be used when processing requests
    # by HttpConn objects
    def process_request(self, request):
        """pre-process http request"""
        pass

    def process_response(self, return_value, is_error):
        """process value returned by http request"""
        # pylint: disable=unused-argument
        return return_value

    def mk_descr(self):
        """Prepare adapter's description to be included into connection description"""
        return None


class BAuthAdapter(_HttpConnAdapter):
    """Add Basic Authorization header to http(s) request."""
    def __init__(self, login, password):
        self.login = login
        self.password = password
        self.bauth_header = b"Basic " + base64.b64encode(
            f"{login}:{password}".encode('utf-8'))

    def process_request(self, request):
        """Pre-process http(s) request: add auth header"""
        assert not request.has_header('Authorization')
        request.add_header('Authorization', self.bauth_header)

    def mk_descr(self):
        """Prepare adapter's description to be included into connection description"""
        return f"with bauth by '{self.login}'"


class ClientAuthAdapter(_HttpConnAdapter):
    """Add Client authorization to http(s) request."""
    def __init__(self, client_name, client_id, client_secret):
        self.client_name = client_name
        self.client_id = client_id
        self.client_secret = client_secret

        self.bauth_header = b"Basic " + base64.b64encode(
            f"{client_id}:{client_secret}".encode('utf-8'))

    def process_request(self, request):
        """Pre-process http(s) request: add auth header"""
        assert not request.has_header('Authorization')
        request.add_header('Authorization', self.bauth_header)

    def mk_descr(self):
        """Prepare adapter's description to be included into connection description"""
        return f"with bauth by client '{self.client_name}'"


class TokenAuthAdapter(_HttpConnAdapter):
    """Add token authorization to http(s) request."""
    def __init__(self, token, token_descr=None):
        self.token_descr = token_descr
        self.header = f"Bearer {token}"

    def process_request(self, request):
        """Pre-process http(s) request: add auth header"""
        assert not request.has_header('Authorization')
        request.add_header('Authorization', self.header)

    def mk_descr(self):
        """Prepare adapter's description to be included into connection description"""
        descr = "with auth by token"
        if self.token_descr is not None:
            descr += f" '{self.token_descr}'"
        return descr


def bauth_conn(address, login, password, **kwargs):
    """Create HttpConn with basic authorization."""
    adapters = kwargs.pop('adapters', [])
    bauth_adapter = BAuthAdapter(login, password)
    adapters.append(bauth_adapter)

    conn = HttpConn(
        address,
        adapters=adapters,
        **kwargs)

    return conn
