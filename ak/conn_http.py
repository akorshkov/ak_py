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
# http connections
#
# Send http requests to specified address and process responses
#
# Different types of connections (f.e. connection which sends requests with
# basic authentication) are implemented as wrappers: such connection adds
# RequestAdapter object to request processing sequence and delegates
# actual call to the http connection it wraps.
#
# Finally the request is processed by _HttpConnImpl object.


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
    """Base class for adapters, used when processing requests by HttpConn"""

    AUTH_TYPE = None

    def process_req_args(self, req_args):
        """pre-process http request"""
        pass

    def process_response(self, return_value):
        """process value returned by http request"""
        # pylint: disable=unused-argument
        return return_value

    def mk_descr(self):
        """Prepare adapter's description to be included into connection description"""
        return None


class _HttpConnImpl:
    # actually makes http requests and process results
    #
    # it is supposed to be used by 'public' classes (HttpConn, BAuthConn, etc.)

    def __init__(self, address, _send_request_ids=True):
        self.address = address
        self.adapters = []  # dummy value. Child connections expect this property
        self.conn_impl = self

        self._reqid_generator_guard = threading.Lock()
        self._reqid_connection_part = "".join(
            random.choice(string.hexdigits.lower()) for _ in range(4))
        self._cur_req_id = 0 if _send_request_ids else None

        is_https = address.lower().startswith("https://")
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

    def do_request(self, adapters, path, method=None,
                    params=None, data=None, headers=None, raw_response=False):
        """Method which makes the request.

        To be used by the owner connection object. (owner just keeps list of
        adapters and calls this method with these adapters)

        Descriptions of other arguments are same as in _HttpConnBase.get()
        """

        # 1. use adapters to pre-process arguments
        req_args = RequestArguments(
            self.address, path, method, params, data, headers)

        for adapter in adapters:
            adapter.process_req_args(req_args)

        address, path, method, params, data, headers = req_args.args()

        # 2. prepare url
        if params:
            path += "?" + urlencode(params)
        if not address.endswith('/') and not path.startswith('/'):
            path = '/' + path
        url = address + path

        # 2. headers
        if self._cur_req_id is not None:
            # means req_id should be autogenerated if not specified
            if 'X-Request-ID' not in headers:
                headers['X-Request-ID'] = self._generate_request_id()

        # 3. method (autodetect)
        if not method:
            method = 'POST' if data else 'GET'
        else:
            method = str(method).upper()

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
                if 'Content-Type' not in headers:
                    headers['Content-Type'] = 'application/json'
            req_data = str_data.encode(encoding='utf-8')

        request = urllib.request.Request(
            url,
            data=req_data,
            method=method,
            headers=headers)

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
        for adapter in adapters[::-1]:
            ret_val = adapter.process_response(ret_val)

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


class _HttpConnBase:
    # Base class for http connection objects.
    #
    # Derived classes have only to implement apropriate request adapters

    def __init__(self, adapters, conn_data):
        # Arguments:
        # - adapters: list of RequestAdapter objects or a single such object
        # - conn_data: either another _HttpConnBase object to wrap, or arguments
        #              for _HttpConnImpl

        if not isinstance(adapters, (list, tuple)):
            # 'adapters' is not a list, but a single adapter. Make it a list
            adapters = [adapters, ]

        if isinstance(conn_data, _HttpConnBase):
            # conn_data is another connection object, self will wrap it
            parent_conn = conn_data
        elif isinstance(conn_data, str):
            # conn_data is an address
            address = conn_data
            if address.endswith('/'):
                address = address[:-1]
            parent_conn = _HttpConnImpl(address)
        elif isinstance(conn_data, (list, tuple)):
            # conn_data is a list of arguments for connection
            parent_conn = _HttpConnImpl(*conn_data)
        elif isinstance(conn_data, dict):
            # conn_data is a dict of arguments for connection
            parent_conn = _HttpConnImpl(**conn_data)
        else:
            assert False, (
                f"Unexpected value of 'conn_data' arg (type {type(conn_data)}): "
                f"{conn_data}")

        self.parent_conn = parent_conn
        self.conn_impl = parent_conn.conn_impl

        self.own_adapters = adapters
        # prepare final list of adapters(including own adapters and those
        # used by parent connection)
        self.adapters = self.own_adapters + self.parent_conn.adapters

        self.descr = None  # to be evaluated on demand

        # string identifier of authentication type used by this connection.
        # to be used to warn about situations when the connection has unexpected
        # auth type.
        # Potentially several adapters may change authentication of the
        # request - be polite and do not create such connections
        self.auth_type = next(
            (a.AUTH_TYPE for a in self.adapters if a.AUTH_TYPE is not None),
            None)

    def __str__(self):
        if self.descr is None:
            self._prepare_self_descr()
        return self.descr

    def __repr__(self):
        return str(self)

    def _prepare_self_descr(self):
        # create description of self. It includes descriptions of adapters
        def _parts():
            # prepare parts of description
            for adapter in self.own_adapters[::-1]:
                yield adapter.mk_descr()
            yield str(self.parent_conn)

        self.descr = " ".join(part for part in _parts() if part is not None)

    def get_address(self):
        """Get the address of this connection.

        The returned address is the address specified during the connection construction.
        So it may (or may not) contain port/path information.
        """
        if hasattr(self.parent_conn, 'address'):
            return self.parent_conn.address
        return self.parent_conn.get_address()

    def add_adapter(self, adapter):
        """Add adapter to self.

        Adapter is an object that can process request and returned value.
        """
        self.adapters.append(adapter)
        self.descr = None  # to be re-evaluated by demand

    def get(self, path, *,
            params=None, data=None, headers=None, raw_response=False):
        """Make GET https(s) request.

        Arguments:
        - path: request path
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
        # small shortcut: instead of calling self.parent_conn call the final
        # element of the chain immediately
        return self.conn_impl.do_request(
            self.adapters, path, "GET", params, data, headers, raw_response)

    def post(self, path, *,
             params=None, data=None, headers=None, raw_response=False):
        """Make POST https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self.conn_impl.do_request(
            self.adapters, path, "POST", params, data, headers, raw_response)

    def put(self, path, *,
            params=None, data=None, headers=None, raw_response=False):
        """Make PUT https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self.conn_impl.do_request(
            self.adapters, path, "PUT", params, data, headers, raw_response)

    def delete(self, path, *,
               params=None, data=None, headers=None, raw_response=False):
        """Make DELETE https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self.conn_impl.do_request(
            self.adapters, path, "DELETE", params, data, headers, raw_response)

    def patch(self, path, *,
               params=None, data=None, headers=None, raw_response=False):
        """Make PATCH https(s) request.

        Check doc of 'get' method for detailed descr of arguments.
        """
        return self.conn_impl.do_request(
            self.adapters, path, "PATCH", params, data, headers, raw_response)


class HttpConn(_HttpConnBase):
    """Send plain http requests"""
    def __init__(self, conn_data, *, adapters=None):
        if adapters is None:
            adapters = []
        super().__init__(adapters, conn_data)


class BAuthConn(_HttpConnBase):
    """Send http requests with basic authentication"""

    class Adapter(RequestAdapter):
        """Add Basic Authorization header to http(s) request."""
        AUTH_TYPE = "basic"

        def __init__(self, login, password):
            self.login = login
            self.password = password
            self.bauth_header = b"Basic " + base64.b64encode(
                f"{login}:{password}".encode('utf-8'))

        def process_req_args(self, req_args):
            """Pre-process http(s) request: add auth header"""
            assert 'Authorization' not in req_args.headers
            req_args.headers['Authorization'] = self.bauth_header

        def mk_descr(self):
            """Prepare part for connection description"""
            return f"BAuth by '{self.login}'"

    def __init__(self, conn_data, login, password):
        super().__init__(self.Adapter(login, password), conn_data)


class ClientAuthConn(_HttpConnBase):
    """Send http requests with client basic authentication"""

    class Adapter(RequestAdapter):
        """Add Client authorization to http(s) request."""
        AUTH_TYPE = "client"

        def __init__(self, client_name, client_id, client_secret):
            self.client_name = client_name
            self.client_id = client_id
            self.client_secret = client_secret

            self.bauth_header = b"Basic " + base64.b64encode(
                f"{client_id}:{client_secret}".encode('utf-8'))

        def process_req_args(self, req_args):
            """Pre-process http(s) request: add auth header"""
            assert 'Authorization' not in req_args.headers
            req_args.headers['Authorization'] = self.bauth_header

        def mk_descr(self):
            """Prepare part for connection description"""
            return f"with BAuth by client '{self.client_name}'"

    def __init__(self, conn_data, client_name, client_id, client_secret):
        super().__init__(
            self.Adapter(client_name, client_id, client_secret),
            conn_data)


class TokenAuthConn(_HttpConnBase):
    """Send http requests with token authentication"""

    class Adapter(RequestAdapter):
        """Add token authorization to http(s) request."""
        AUTH_TYPE = "token"

        def __init__(self, token, token_descr=None):
            self.token_descr = token_descr
            self.header = f"Bearer {token}"

        def process_req_args(self, req_args):
            """Pre-process http(s) request: add auth header"""
            assert 'Authorization' not in req_args.headers
            req_args.headers['Authorization'] = self.header

        def mk_descr(self):
            """Prepare part for connection description"""
            descr = "with auth by token"
            if self.token_descr is not None:
                descr += f" '{self.token_descr}'"
            return descr

    def __init__(self, conn_data, token, token_descr=None):
        super().__init__(
            self.Adapter(token, token_descr),
            conn_data)


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

    def mk_descr(self):
        return f"with path prefix '{self.prefix}'"
