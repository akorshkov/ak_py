"""Tools for creation of "methods caller" objects for http calls."""

from ak import conn_http
from ak.hdoc import BoundMethodNotes
from ak.mcaller import MCaller


class MCallerMetaHttpMethod:
    """Properties of MethodsCaller method, which wraps http call.

    Created by 'method_http' decorator.
    """

    # name of the method, which will prepare BoundMethodNotes for
    # methods decorated with this decorator
    _MAKE_BM_NOTES_METHOD = '_make_bm_notes_http'

    __slots__ = 'auth_type', 'component'

    def __init__(self, auth_type, component=None):
        self.auth_type = auth_type
        self.component = component


def method_http(auth_type, component=None):
    """decorator to mark method as a 'wrapper' around http method."""

    if callable(auth_type) and component is None:
        # decorator was used w/o parameters. auth_type is actually a
        # method to decorate
        method = auth_type
        dec = method_http(None, None)
        return dec(method)

    def decorator(method):
        method._mcaller_meta = MCallerMetaHttpMethod(auth_type, component)
        return method

    return decorator


class MCallerHttp(MCaller):
    """Base class for "http method callers".

    Base for classes, whose methods are python wrappers of http calls.

    Derived class should look like:
    class MyCaller(MCallerHttp):
        def __init__(self, ...):
            self.http_conn = ...  # required for get_conn() method to work
            # required for get_conn() if components are specied in
            # method_http decorators.
            self.http_prefixes = {
                'componentA': "/path/prefix/for/componentA",
                ...
            }

        @method_http('bauth', 'componentA')
        def get_example(self):
            conn = self.get_conn()
            return conn("path/for/this/method")
    """

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

        if not hasattr(self, 'http_conn'):
            raise NotImplementedError(
                f"obj of class {type(self)} has a method decorated by "
                f"'method_http' but it does not have "
                f"'http_conn' attribute. "
            )
        base_conn = self.http_conn

        if method_meta.component is not None:
            if not hasattr(self, 'http_prefixes'):
                raise NotImplementedError(
                    f"obj of class {type(self)} has a method decorated by "
                    f"'method_http' with specified component name "
                    f"'{method_meta.component}', but it does not have "
                    f"'http_prefixes' attribute. "
                )
            prefix = self.http_prefixes[method_meta.component]
            if getattr(self, '_mc_conns_by_prefix', None) is None:
                setattr(self, '_mc_conns_by_prefix', {})
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

    def _make_bm_notes_http(self, bound_method, palette) -> BoundMethodNotes:
        # create BoundMethodNotes for bound http method (method
        # decorated with 'method_http')
        assert hasattr(bound_method, '_mcaller_meta')
        method_meta = bound_method._mcaller_meta
        for attr in ['auth_type', 'component']:
            # '_make_bm_notes_http' must have been specified in method_meta,
            # so method_meta must have these attributes
            assert hasattr(method_meta, attr)

        if not hasattr(self, 'http_conn'):
            return BoundMethodNotes(
                False, '<n/a>', "object has no 'http_conn' attribute")

        auth_descr = ""
        if isinstance(method_meta.auth_type, (list, tuple)):
            auth_ok = self.http_conn.auth_type in method_meta.auth_type
            auth_descr = (
                f"wrong connection auth type "
                f"('{self.http_conn.auth_type}' not in '{method_meta.auth_type}')")
        else:
            auth_ok = self.http_conn.auth_type == method_meta.auth_type
            auth_descr = (
                f"wrong connection auth type "
                f"('{self.http_conn.auth_type}' != '{method_meta.auth_type}')")

        component_ok = True
        component_problem_descr = ""
        if method_meta.component is not None:
            if method_meta.component not in getattr(self, 'http_prefixes', []):
                component_ok = False
                component_problem_descr = (
                    f"object has no http connection to component "
                    f"'{method_meta.component}'")

        method_available = auth_ok and component_ok
        note_short = ""
        note_line = None
        if not method_available:
            note_short = "<n/a"
            note_line = "; ".join(
                s for s in [auth_descr, component_problem_descr] if s)

        return BoundMethodNotes(method_available, note_short, note_line)
