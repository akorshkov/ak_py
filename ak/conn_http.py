"""Http requests library.

Wrapper for standard python urlib; makes it more convenient to make rest api requests.
"""

import threading
import random
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
# HttpConn - http connection
#
# Send http requests to specified address and process responses.

class RequestIDGenerator:
    """Generator of requests ids.

    Generator object generates strings with common prefix and a suffix containing counter.
    Example:
        bf89954f-6bc6-8177-d574-b2a580000000
        bf89954f-6bc6-8177-d574-b2a580000001
    """
    _CHARS_SET = "0123456789abcdef"

    __slots__ = 'prefix', 'counter', '_counter_as_hex', '_reqid_generator_guard'

    def __init__(self, _counter_as_hex=False):
        """Constructor of RequestIDGenerator.

        Arguments:
        - _counter_as_hex: if True formats counter suffix as hex number.
        """
        self._reqid_generator_guard = threading.Lock()
        self._counter_as_hex = _counter_as_hex

        _rand_s = lambda n : "".join(random.choice(self._CHARS_SET) for _ in range(n))
        self.prefix = "-".join(_rand_s(n) for n in [8, 4, 4, 4, 5])

        self.counter = 0

    def generate_id(self) -> str:
        """Generate and return next request id"""
        with self._reqid_generator_guard:
            request_n = self.counter
            self.counter += 1

        if self._counter_as_hex:
            n = request_n & 0xfffffff
            str_counter = f"{n:07x}"
        else:
            n = request_n % 10000000
            str_counter = f"{n:07}"

        return f"{self.prefix}{str_counter}"


class RequestArguments:
    """Arguments for building urllib Request.

    RequestAdapters process objects of this class to modify arguments
    of Request constructor.
    """

    __slots__ = 'address', 'path', 'method', 'params', 'data', 'headers'

    def __init__(self, address, path, method, params, data, headers):
        self.address = address
        self.path = path
        self.method = method
        self.params = params
        self.data = data
        self.headers = headers.copy() if headers else {}

    def args(self):
        """Return self as tuple"""
        return (self.address, self.path, self.method,
                self.params, self.data, self.headers)


class RequestAdapter:
    """Base class for request adapters.

    HttpConn may be configured to use RequestAdapters to pre-process requests
    """

    AUTH_TYPE = None

    def process_req_args(self, req_args):
        """pre-process http request"""
        pass

    def process_response(self, return_value):
        """process value returned by http request"""
        # pylint: disable=unused-argument
        return return_value


class HttpConn:
    """Sends http requests.

    Convenient for rest api calls.
    """

    _HDR_NAME_REQ_ID = 'X-request-id'
    _HDR_NAME_CONT_TYPE = 'Content-type'

    def __init__(
        self,
        conn_data,
        *,
        headers=None,
        adapters=None,
        auto_json_cont_type=None,
        request_ids_generator=None, # None - default, False - do not use
    ):
        """HttpConn constructor.

        Arguments:
        - conn_data: can be either url string or another HttpConn object. In the second case
            connection configuration is inherited from it.
        - headers: headers to be sent with each request. May be:
            - {header_name: value}
            - [(header_name, value), ]
            value == None means that the header should not be sent (thus it is possible to
            remove header inherited from another HttpConn.
            Note: value of some headers (for example 'X-request-id' and 'Content-type') can
            be calculated during actual request.
        - adapters: list of RequestAdapter-derived objects. Can be used to pre-process request
        - auto_json_cont_type: HttpConn may automatically add "Content-type" =
            "application/json" header if the header is not specified with request explicitely
            and request contains data and the data is not a string or bytes.
            - True/False: turn on/off this feature
            - None: use parent's value if it is specified; else True
        - request_ids_generator: optional RequestIDGenerator object. Other possible values:
            - False: do not auto-generate 'X-request-id' headers
            - None: share generator with parent if parent is specified; else create a new
            generator.
        """
        if isinstance(conn_data, str):
            is_cloning = False
            self.address = conn_data
        elif isinstance(conn_data, HttpConn):
            is_cloning = True
            self.address = conn_data.address
        else:
            raise ValueError(
                f"HttpConn constructor arg 'conn_data' must be either string or "
                f"HttpConn. Actual arg: {type(conn_data)} {conn_data}")

        arg_headers = self.make_headers_dict(headers)
        self.headers = {**conn_data.headers, **arg_headers} if is_cloning else arg_headers
        if any(v is None for v in self.headers):
            self.headers = {n: v for n, v in self.headers.items() if v is not None}

        self.adapters = conn_data.adapters[:] if is_cloning else []
        if adapters is not None:
            if not isinstance(adapters, (list, tuple)):
                adapters = [adapters, ]
            self.adapters.extend(adapters)

        self.auto_json_cont_type = auto_json_cont_type
        if self.auto_json_cont_type is None:
            self.auto_json_cont_type = conn_data.auto_json_cont_type if is_cloning else True

        if request_ids_generator is None:
            if is_cloning:
                self.request_ids_generator = conn_data.request_ids_generator
            else:
                self.request_ids_generator = RequestIDGenerator()
        elif not request_ids_generator:
            self.request_ids_generator = None
        else:
            self.request_ids_generator = request_ids_generator

        is_https = self.address.lower().startswith("https://")
        self.opener = self._make_opener(is_https)

    def __str__(self):
        return f"Connection to {self.address}"

    def __repr__(self):
        return str(self)

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

    @classmethod
    def make_headers_dict(cls, headers, _ignore_duplicates=False):
        """Create a dictionary of headers values.

        Headers names are case-insensitive. urllib.request converts headers names to
        some 'standard' form: first letter is capital, all others are not.
        Keys of the dictionary returned by this method are converted to this 'standard' form.

        Arguments:
        - headers: either {name: value} or [(name, value), ]
        - _ignore_duplicates: do not fail in case headers argument contain headers with
        equivalent names (for example "X-Request-ID" and "X-request-id"). All but one of
        such headers will be ignored.
        """
        result = {}
        fixed_names = {}
        def _iter_headers():
            if headers is None:
                return
            if isinstance(headers, dict):
                yield from headers.items()
            else:
                yield from headers

        for n, v in _iter_headers():
            std_name = cls.mk_std_header_name(n)
            if not _ignore_duplicates and std_name in fixed_names:
                raise ValueError(
                    f"Duplicate header names '{n}' and '{fixed_names[std_name]}' detected")
            fixed_names[std_name] = n
            result[std_name] = v

        return result

    @classmethod
    def mk_std_header_name(cls, header_name) -> str:
        """Return 'standard' form of header_name.

        Headers names are case-insensitive, HttpConn.headers contains header names in some
        'standard' form.
        """
        return header_name.title()

    def set_auth_basic(self, login, password):
        """Add Authorization header with Basic authorization value."""
        auth_header_val = b"Basic " + base64.b64encode(f"{login}:{password}".encode('utf-8'))
        self.headers[self.mk_std_header_name('Authorization')] = auth_header_val
        return self

    def set_auth_token(self, token):
        """Add Authorization header with Bearer authorization value."""
        auth_header_val = f"Bearer {token}"
        self.headers[self.mk_std_header_name('Authorization')] = auth_header_val
        return self

    def patch_headers(self, headers):
        """Update connection headers.

        Argument:
        - headers: May be
            - {header_name: value}
            - [(header_name, value), ]
            value = None means that the header should not be sent.
        """
        self.headers = {**self.headers, **self.make_headers_dict(headers)}
        if any(v is None for v in headers.values()):
            self.headers = {n: v for n, v in self.headers.items() if v is not None}
        return self

    def get(self, path, *, params=None, data=None, headers=None, raw_response=False):
        """Make GET http(s) request.

        Arguments:
        - path: request path
        - params: dictionary of request parameters
        - data: data for request. Can be bytes, string or any python object, which
            can be dumped to json.
        - headers: dict, explicit headers for the request. Will be merged with connection
            headers. Header value = None means that the header will not be sent.
        - raw_response: specifies how response is handled.
            False - (default) method expects that response contains a valid
               json (or no data) and returns decoded json (or empty str). Exception
               is thrown if request was not successful.
            True - urllib Response object is returned "as-is".
        """
        return self._do_request(path, 'GET', params, data, headers, raw_response)

    def post(self, path, *, params=None, data=None, headers=None, raw_response=False):
        """Make POST https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self._do_request(path, 'POST', params, data, headers, raw_response)

    def put(self, path, *, params=None, data=None, headers=None, raw_response=False):
        """Make PUT https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self._do_request(path, 'PUT', params, data, headers, raw_response)

    def delete(self, path, *, params=None, data=None, headers=None, raw_response=False):
        """Make DELETE https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self._do_request(path, 'DELETE', params, data, headers, raw_response)

    def patch(self, path, *, params=None, data=None, headers=None, raw_response=False):
        """Make PATCH https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self._do_request(path, 'PATCH', params, data, headers, raw_response)

    def _do_request(
            self, path, method,
            params=None, data=None, headers=None, raw_response=False):
        # do the request

        # 1. use adapters to pre-process arguments
        req_args = RequestArguments(
            self.address, path, method, params, data, headers)

        for adapter in self.adapters:
            adapter.process_req_args(req_args)

        address, path, method, params, data, headers = req_args.args()

        # 2. prepare url
        if params:
            path += "?" + urlencode(params)
        if not address.endswith('/') and not path.startswith('/'):
            path = '/' + path
        url = address + path

        # 2. headers
        arg_headers = self.make_headers_dict(headers)
        req_headers = {**self.headers, **arg_headers}
        if any(v is None for v in req_headers.values()):
            req_headers = {n: v for n, v in req_headers.items() if v is not None}

        # 2.1. request id header
        if (self.request_ids_generator is not None
            and self._HDR_NAME_REQ_ID not in req_headers
        ):
            req_headers[self._HDR_NAME_REQ_ID] = self.request_ids_generator.generate_id()

        # 3. data
        if data is None:
            req_data = None
        elif isinstance(data, bytes):
            req_data = data
        else:
            if isinstance(data, str):
                str_data = data
            else:
                str_data = json.dumps(data)
                if self.auto_json_cont_type and self._HDR_NAME_CONT_TYPE not in req_headers:
                    req_headers[self._HDR_NAME_CONT_TYPE] = 'application/json'
            req_data = str_data.encode(encoding='utf-8')

        request = urllib.request.Request(
            url,
            data=req_data,
            method=method,
            headers=req_headers)

        # log request.
        # !request is not final yet, urllib may add some headers during the call!
        self._log_request(request)

        # actual call
        try:
            response = self.opener.open(request)
        except urllib.error.HTTPError as err:
            with err:
                err.data = err.read()
            self._log_response(err, url)
            raise

        with response:
            response.data = response.read()

        self._log_response(response, url)

        if not raw_response:
            ret_val = response.data.decode('utf-8')
            if ret_val:
                ret_val = json.loads(ret_val)
        else:
            ret_val = response

        # process return value
        for adapter in self.adapters[::-1]:
            ret_val = adapter.process_response(ret_val)

        return ret_val

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


#########################
# Request adapters
#

class RequestAdapterAddPathPrefix(RequestAdapter):
    """Request adapter which adds specified prefix to request path."""

    __slots__ = ('prefix', )

    def __init__(self, prefix):
        self.prefix = prefix

    def process_req_args(self, req_args):
        suffix_path = req_args.path
        if suffix_path and suffix_path.startswith('/') and self.prefix.endswith('/'):
            suffix_path = suffix_path[1:]

        req_args.path = self.prefix + suffix_path
