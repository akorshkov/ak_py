"""Tools for creation of "methods caller" objects for http calls."""

from ak.mcaller import Meta_MethodsCaller
from ak import conn_http


class MCallerMetaHttpMethod:
    """Properties of MethodsCaller method, which wraps http call.

    Created by decorator of http method wrapper.
    """
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


class MCallerHttp(metaclass=Meta_MethodsCaller):
    """Base class for "http method collers".

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
