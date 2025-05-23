"""Tools for creation of "methods caller" objects for http calls."""

from ak import conn_http
from ak.color import CHText
from ak.hdoc import BoundMethodNotes
from ak.mcaller import MCaller


class MCallerMetaHttpMethod:
    """Properties of MethodsCaller method, which wraps http call.

    Created by 'method_http' decorator.
    """

    # name of the method, which will prepare BoundMethodNotes for
    # methods decorated with this decorator
    _MAKE_BM_NOTES_METHOD = '_make_bm_notes_http'

    __slots__ = 'auth_types', 'components'

    def __init__(self, auth_types, components=None):
        if auth_types is None or isinstance(auth_types, str):
            self.auth_types = [auth_types, ]
        else:
            self.auth_types = auth_types
        self.components = components
        if isinstance(self.components, str):
            self.components = [self.components]


def method_http(auth_types, components=None):
    """decorator to mark method of MCallerHttp as a 'wrapper' around http request.

    Arguments:
    - auth_types: expected auth type of the http connection (*). May be one of
        the following values or a collection of them:
        - None: method can be called via connection with no authentication
        - 'basic': can be called via basic-auth connection
        - 'client': can be called via client-auth connection
        - 'token': can be called via token-auth connection
        (See ak.conn_http.RequestAdapter-derived classes for more details)
    - components: names of the external components (**)

    Notes (*)(**):
      The MCallerHttp object owns a connection (HttpConn). This connection
    may be authorized (f.e. the requests sent through it will have basic
    authorization with credentials of mr. Root).
      Decorated method should get the connetion object using self.get_conn().
    and use it as is (w/o changing authorization).
      The connection returned by self.get_conn() depends on the method's components.
    MCallerHttp will check if it can provide connection to one of the components
    expected by the method. Depending on chosen component some prefix may be added
    to request path.
      If auth type of connetion does not match method's 'auth_types' a warning
    will be issued, (but it is still possible to call methods with 'incorrect'
    authorization - f.e. for test purposes).
    """

    if callable(auth_types) and components is None:
        # decorator was used w/o parameters. auth_types is actually a
        # method to decorate
        method = auth_types
        dec = method_http(None, None)
        return dec(method)

    def decorator(method):
        method._mcaller_meta = MCallerMetaHttpMethod(auth_types, components)
        return method

    return decorator


class MCallerHttp(MCaller):
    """Base class for "http method callers".

    Base for classes, whose methods are python wrappers of http calls.

    Derived class should look like:
    class MyCaller(MCallerHttp):
        _HTTP_PREFIX_MAP = {
            'componentA': "/path/prefix/for/componentA",
        }

        @method_http('basic', 'componentA')
        def get_example(self):
            conn = self.get_conn()
            return conn.post("path/for/this/method", data=some_data)
    """
    _HTTP_PREFIX_MAP = {}  # {component: http_prefix}

    __slots__ = 'http_conn', '_mc_conns_by_prefix'

    def __init__(self, address):
        """Create MCallerHttp object.

        Arguments:
        - address: http address or the conn_http.HttpConn object
        """
        if isinstance(address, conn_http.HttpConn):
            self.http_conn = address
        else:
            self.http_conn = conn_http.HttpConn(address)

        self._mc_conns_by_prefix = {}

    def clone(self, http_conn_adapters=None):
        """Create a new MCallerHttp with a same method but modified connection.

        F.e. we have a method caller which sends unauthorized http requests,
        and we want to create a new caller, which would send requests with
        basic authorization using John's credentials.

        Argument:
        - http_conn_adapters: list of conn_http.RequestAdapter objects (or
        a single such object)
        """
        if http_conn_adapters is None:
            http_conn_adapters = []
        elif isinstance(http_conn_adapters, (list, tuple)):
            # it's a single adapter
            http_conn_adapters = [http_conn_adapters]

        cloned_http_conn = conn_http.HttpConn(
            self.http_conn, adapters=http_conn_adapters)
        return type(self)(cloned_http_conn)

    def get_conn(self):
        """returns HttpConn to be used in currnt http wrapper method.

        Returned HttpConn depends on 'method_http' metadata of caller.
        So this method uses some 'inspect' magic to find this metadata.
        """
        # pylint: disable=no-member
        method_meta = self.get_mcaller_meta()  # 'inspect' magic is in there

        assert isinstance(method_meta, MCallerMetaHttpMethod), (
            "Method 'get_conn' can only be called from HttpConn wrappers"
        )

        base_conn = self.http_conn

        if method_meta.components is not None:
            matching_components = [
                c for c in method_meta.components if c in self._HTTP_PREFIX_MAP]
            assert len(matching_components) == 1, (
                f"http method expects connection to one of the following "
                f"components: {method_meta.components}. "
                f"Class {type(self)} has configured http prefixes for "
                f"components : {self._HTTP_PREFIX_MAP}."
                f"Expected to have exactly one match; actual matching "
                f"componets: {matching_components}")
            component = matching_components[0]
            prefix = self._HTTP_PREFIX_MAP[component]
            conns_by_prefix = self._mc_conns_by_prefix
            if prefix in conns_by_prefix:
                conn = conns_by_prefix[prefix]
            else:
                if prefix:
                    adapter = conn_http.RequestAdapterAddPathPrefix(prefix)
                    conn = conn_http.HttpConn(base_conn, adapters=adapter)
                else:
                    conn = base_conn
                conns_by_prefix[prefix] = conn
        else:
            conn = base_conn

        return conn

    def _make_bm_notes_http(self, bound_method, _c) -> BoundMethodNotes:
        # create BoundMethodNotes for bound http method (method
        # decorated with 'method_http')
        assert hasattr(bound_method, '_mcaller_meta')
        method_meta = bound_method._mcaller_meta
        for attr in ['auth_types', 'components']:
            # '_make_bm_notes_http' must have been specified in method_meta,
            # so method_meta must have these attributes
            assert hasattr(method_meta, attr)

        if not hasattr(self, 'http_conn'):
            return BoundMethodNotes(
                False,
                CHText(_c.warn('<n/a>')),
                "object has no 'http_conn' attribute")

        auth_ok = self.http_conn.auth_type in method_meta.auth_types
        auth_descr = (
            f"wrong connection auth type "
            f"('{self.http_conn.auth_type}' not in '{method_meta.auth_types}')")

        component_ok = True
        component_problem_descr = ""
        if method_meta.components is not None:
            matching_components = [
                c for c in method_meta.components if c in self._HTTP_PREFIX_MAP]
            if not matching_components:
                component_ok = False
                component_problem_descr = (
                    f"object has no http connection to any of components "
                    f"'{method_meta.components}'")
            elif len(matching_components) > 1:
                component_ok = False
                component_problem_descr = (
                    f"ambiguous components {matching_components}")

        method_available = auth_ok and component_ok
        note_short = ""
        note_line = ""
        if not method_available:
            note_short = CHText(_c.warn('<n/a>'))
            note_line = "; ".join(
                s for s in [auth_descr, component_problem_descr] if s)

        return BoundMethodNotes(method_available, note_short, note_line)
